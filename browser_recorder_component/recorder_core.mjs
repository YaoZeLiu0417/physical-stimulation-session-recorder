export const LIMITS = Object.freeze({
  demoMax: 300,
  longWarning: 1800,
  longMax: 2700,
});

const MIME_TYPES = Object.freeze([
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
]);

const MODES = new Set(["demo", "long"]);
const STATES = new Set([
  "idle",
  "ready",
  "recording",
  "stopped",
  "saved",
  "skipped",
  "failed",
]);
const ERROR_CODES = new Set([
  "permission_denied",
  "camera_unavailable",
  "microphone_unavailable",
  "device_lost",
  "unsupported_format",
  "write_failed",
  "close_failed",
]);

const TRANSITIONS = Object.freeze({
  idle: Object.freeze({
    "permission-granted": "ready",
    skip: "skipped",
    fail: "failed",
  }),
  ready: Object.freeze({
    record: "recording",
    skip: "skipped",
    fail: "failed",
  }),
  recording: Object.freeze({
    stop: "stopped",
    fail: "failed",
  }),
  stopped: Object.freeze({
    save: "saved",
    fail: "failed",
  }),
  saved: Object.freeze({ reset: "idle" }),
  skipped: Object.freeze({ reset: "idle" }),
  failed: Object.freeze({ reset: "idle" }),
});

function clampDuration(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }
  return Math.min(LIMITS.longMax, Math.max(0, Math.trunc(value)));
}

export function formatDuration(seconds) {
  const duration = clampDuration(seconds);
  const minutes = Math.floor(duration / 60);
  const remainder = duration % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

export function chooseMimeType(isSupported) {
  if (typeof isSupported !== "function") {
    return null;
  }
  try {
    for (const mimeType of MIME_TYPES) {
      if (isSupported(mimeType) === true) {
        return mimeType;
      }
    }
  } catch {
    return null;
  }
  return null;
}

export function nextState(state, event) {
  if (
    typeof state !== "string" ||
    typeof event !== "string" ||
    !Object.hasOwn(TRANSITIONS, state) ||
    !Object.hasOwn(TRANSITIONS[state], event)
  ) {
    throw new Error("invalid recorder transition");
  }
  return TRANSITIONS[state][event];
}

function readStatusField(candidate, key) {
  try {
    return candidate[key];
  } catch {
    return undefined;
  }
}

export function createStatus(input = {}) {
  const candidate = input !== null && typeof input === "object" ? input : {};
  const mode = readStatusField(candidate, "mode");
  const state = readStatusField(candidate, "state");
  const durationSeconds = readStatusField(candidate, "duration_seconds");
  const cameraReady = readStatusField(candidate, "camera_ready");
  const microphoneReady = readStatusField(candidate, "microphone_ready");
  const savedConfirmed = readStatusField(candidate, "saved_confirmed");
  const errorCode = readStatusField(candidate, "error_code");
  return {
    mode: MODES.has(mode) ? mode : "demo",
    state: STATES.has(state) ? state : "idle",
    duration_seconds: clampDuration(durationSeconds),
    camera_ready: typeof cameraReady === "boolean" ? cameraReady : false,
    microphone_ready:
      typeof microphoneReady === "boolean" ? microphoneReady : false,
    saved_confirmed:
      typeof savedConfirmed === "boolean" ? savedConfirmed : false,
    error_code:
      errorCode === null || ERROR_CODES.has(errorCode) ? errorCode : null,
  };
}

function sanitizedError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

export class SerialChunkWriter {
  #writable;
  #write;
  #close;
  #tail = Promise.resolve();
  #closePromise = null;
  #abortPromise = null;
  #closing = false;
  #aborted = false;

  constructor(writable) {
    if (writable === null || typeof writable !== "object") {
      throw sanitizedError("write_failed");
    }
    let write;
    let close;
    try {
      write = writable.write;
      close = writable.close;
    } catch {
      throw sanitizedError("write_failed");
    }
    if (typeof write !== "function" || typeof close !== "function") {
      throw sanitizedError("write_failed");
    }
    this.#writable = writable;
    this.#write = write;
    this.#close = close;
  }

  enqueue(chunk) {
    if (this.#closing || this.#aborted || this.#writable === null) {
      return Promise.reject(sanitizedError("write_failed"));
    }

    const queued = this.#tail.then(async () => {
      if (this.#aborted) {
        return;
      }
      try {
        await this.#write.call(this.#writable, chunk);
      } catch {
        throw sanitizedError("write_failed");
      }
    });
    this.#tail = queued;
    return queued;
  }

  close() {
    if (this.#closePromise !== null) {
      return this.#closePromise;
    }
    if (this.#aborted) {
      return this.#abortPromise;
    }

    this.#closing = true;
    const writable = this.#writable;
    const close = this.#close;
    this.#closePromise = this.#tail
      .then(
        async () => {
          try {
            await close.call(writable);
          } catch {
            throw sanitizedError("close_failed");
          }
        },
        () => {
          throw sanitizedError("write_failed");
        },
      )
      .finally(() => {
        this.#tail = Promise.resolve();
        this.#writable = null;
        this.#write = null;
        this.#close = null;
      });
    return this.#closePromise;
  }

  abort() {
    if (this.#closePromise !== null) {
      return this.#closePromise;
    }
    if (this.#abortPromise !== null) {
      return this.#abortPromise;
    }

    this.#aborted = true;
    this.#closing = true;
    const writable = this.#writable;
    this.#writable = null;
    this.#write = null;
    this.#close = null;
    this.#tail = Promise.resolve();
    this.#abortPromise = Promise.resolve()
      .then(() => {
        if (typeof writable?.abort === "function") {
          return writable.abort();
        }
      })
      .catch(() => undefined);
    return this.#abortPromise;
  }
}
