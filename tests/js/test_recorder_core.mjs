import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  LIMITS,
  SerialChunkWriter,
  chooseMimeType,
  createStatus,
  formatDuration,
  nextState,
} from "../../browser_recorder_component/recorder_core.mjs";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function numberedBlob(number) {
  return {
    number,
    size: number,
    type: "video/webm",
    arrayBuffer: async () => new ArrayBuffer(number),
  };
}

function assertSanitizedError(error, code) {
  assert.equal(error instanceof Error, true);
  assert.equal(error.message, code);
  assert.equal(error.code, code);
  assert.equal(error.cause, undefined);
  assert.equal(String(error).includes("private"), false);
  return true;
}

test("exports the approved recording limits", () => {
  assert.deepEqual(LIMITS, {
    demoMax: 300,
    longWarning: 1800,
    longMax: 2700,
  });
});

test("formats clamped recording durations as MM:SS", () => {
  assert.equal(formatDuration(0), "00:00");
  assert.equal(formatDuration(65), "01:05");
  assert.equal(formatDuration(2700), "45:00");
  assert.equal(formatDuration(-1), "00:00");
  assert.equal(formatDuration(Number.NaN), "00:00");
  assert.equal(formatDuration(Number.POSITIVE_INFINITY), "00:00");
  assert.equal(formatDuration(2701), "45:00");
  assert.equal(formatDuration("65"), "00:00");
});

test("chooses the first supported MIME type in approved order", () => {
  const checked = [];
  const result = chooseMimeType((mimeType) => {
    checked.push(mimeType);
    return mimeType === "video/webm;codecs=vp8,opus";
  });

  assert.equal(result, "video/webm;codecs=vp8,opus");
  assert.deepEqual(checked, [
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
  ]);
});

test("returns null when no approved MIME type is supported", () => {
  const checked = [];
  assert.equal(
    chooseMimeType((mimeType) => {
      checked.push(mimeType);
      return false;
    }),
    null,
  );
  assert.deepEqual(checked, [
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm",
  ]);
});

test("requires exact true from the MIME support predicate", () => {
  const truthyNonBooleans = ["false", {}, Promise.resolve(true)];

  for (const result of truthyNonBooleans) {
    assert.equal(chooseMimeType(() => result), null);
  }
});

test("fails closed when the MIME support predicate throws", () => {
  const result = chooseMimeType(() => {
    throw new Error("private MIME probe detail");
  });

  assert.equal(result, null);
});

test("moves through the recording lifecycle", () => {
  assert.equal(nextState("idle", "permission-granted"), "ready");
  assert.equal(nextState("ready", "record"), "recording");
  assert.equal(nextState("recording", "stop"), "stopped");
  assert.equal(nextState("stopped", "save"), "saved");
});

test("supports deliberate skip, failure, and reset transitions", () => {
  assert.equal(nextState("idle", "skip"), "skipped");
  assert.equal(nextState("recording", "fail"), "failed");
  assert.equal(nextState("failed", "reset"), "idle");
  assert.equal(nextState("saved", "reset"), "idle");
  assert.equal(nextState("skipped", "reset"), "idle");
});

test("rejects forbidden recorder transitions", () => {
  assert.throws(
    () => nextState("idle", "record"),
    /invalid recorder transition/,
  );
  assert.throws(
    () => nextState("unknown", "permission-granted"),
    /invalid recorder transition/,
  );
  assert.throws(
    () => nextState("idle", "toString"),
    /invalid recorder transition/,
  );
  assert.throws(
    () => nextState("__proto__", "toString"),
    /invalid recorder transition/,
  );
});

test("creates exactly the seven approved status fields", () => {
  const status = createStatus({
    mode: "long",
    state: "saved",
    duration_seconds: 42,
    camera_ready: true,
    microphone_ready: true,
    saved_confirmed: true,
    error_code: null,
    chunk: "must not escape",
    detail: "must not escape",
  });

  assert.deepEqual(status, {
    mode: "long",
    state: "saved",
    duration_seconds: 42,
    camera_ready: true,
    microphone_ready: true,
    saved_confirmed: true,
    error_code: null,
  });
  assert.deepEqual(Object.keys(status), [
    "mode",
    "state",
    "duration_seconds",
    "camera_ready",
    "microphone_ready",
    "saved_confirmed",
    "error_code",
  ]);
});

test("fails closed when status fields have unapproved types or values", () => {
  assert.deepEqual(
    createStatus({
      mode: "preview",
      state: "uploading",
      duration_seconds: "42",
      camera_ready: 1,
      microphone_ready: "true",
      saved_confirmed: null,
      error_code: new Error("private device detail"),
    }),
    {
      mode: "demo",
      state: "idle",
      duration_seconds: 0,
      camera_ready: false,
      microphone_ready: false,
      saved_confirmed: false,
      error_code: null,
    },
  );
});

test("reads each status field once and contains hostile getter failures", () => {
  let errorReads = 0;
  const changingInput = {
    get error_code() {
      errorReads += 1;
      return errorReads === 1 ? "write_failed" : "private device detail";
    },
  };
  const throwingInput = new Proxy(
    {},
    {
      get() {
        throw new Error("private getter detail");
      },
    },
  );

  assert.equal(createStatus(changingInput).error_code, "write_failed");
  assert.equal(errorReads, 1);
  assert.deepEqual(createStatus(throwingInput), createStatus());
});

test("normalizes duration to an exact integer inside the long limit", () => {
  assert.equal(createStatus({ duration_seconds: 41.9 }).duration_seconds, 41);
  assert.equal(createStatus({ duration_seconds: -1 }).duration_seconds, 0);
  assert.equal(createStatus({ duration_seconds: 9999 }).duration_seconds, 2700);
  assert.equal(
    createStatus({ duration_seconds: Number.POSITIVE_INFINITY }).duration_seconds,
    0,
  );
});

test("accepts only approved modes, states, booleans, and error categories", () => {
  const errors = [
    null,
    "permission_denied",
    "camera_unavailable",
    "microphone_unavailable",
    "device_lost",
    "unsupported_format",
    "write_failed",
    "close_failed",
  ];

  for (const errorCode of errors) {
    assert.equal(createStatus({ error_code: errorCode }).error_code, errorCode);
  }
  assert.equal(createStatus({ mode: "long" }).mode, "long");
  assert.equal(createStatus({ state: "recording" }).state, "recording");
  assert.equal(createStatus({ camera_ready: true }).camera_ready, true);
  assert.equal(createStatus({ microphone_ready: true }).microphone_ready, true);
  assert.equal(createStatus({ saved_confirmed: true }).saved_confirmed, true);
});

test("sanitizes writable method getter failures during construction", () => {
  for (const failingMethod of ["write", "close"]) {
    const writable = {
      get write() {
        if (failingMethod === "write") {
          throw new Error("private write getter detail");
        }
        return async function write() {};
      },
      get close() {
        if (failingMethod === "close") {
          throw new Error("private close getter detail");
        }
        return async function close() {};
      },
    };

    assert.throws(
      () => new SerialChunkWriter(writable),
      (error) => assertSanitizedError(error, "write_failed"),
    );
  }
});

test("reads writable methods once and preserves their receiver", async () => {
  let writeReads = 0;
  let closeReads = 0;
  const written = [];
  const writable = {
    get write() {
      writeReads += 1;
      return function write(blob) {
        assert.equal(this, writable);
        written.push(blob.number);
      };
    },
    get close() {
      closeReads += 1;
      return function close() {
        assert.equal(this, writable);
      };
    },
  };
  const writer = new SerialChunkWriter(writable);

  await writer.enqueue(numberedBlob(1));
  await writer.close();

  assert.deepEqual(written, [1]);
  assert.equal(writeReads, 1);
  assert.equal(closeReads, 1);
});

test("serializes chunk writes and closes only after the queue drains", async () => {
  const gates = [deferred(), deferred(), deferred()];
  const events = [];
  let closeCalls = 0;
  const writable = {
    write(blob) {
      events.push(`write:${blob.number}`);
      return gates[blob.number - 1].promise;
    },
    close() {
      closeCalls += 1;
      events.push("close");
      return Promise.resolve();
    },
  };
  const writer = new SerialChunkWriter(writable);

  const writes = [1, 2, 3].map((number) => writer.enqueue(numberedBlob(number)));
  const closing = writer.close();
  await Promise.resolve();
  assert.deepEqual(events, ["write:1"]);
  assert.equal(closeCalls, 0);

  gates[0].resolve();
  await writes[0];
  assert.deepEqual(events, ["write:1", "write:2"]);
  assert.equal(closeCalls, 0);

  gates[1].resolve();
  await writes[1];
  assert.deepEqual(events, ["write:1", "write:2", "write:3"]);
  assert.equal(closeCalls, 0);

  gates[2].resolve();
  await closing;
  await writer.close();
  assert.deepEqual(events, ["write:1", "write:2", "write:3", "close"]);
  assert.equal(closeCalls, 1);
  assert.deepEqual(await Promise.all(writes), [undefined, undefined, undefined]);
});

test("sanitizes write failures and does not continue the queue", async () => {
  const written = [];
  let closeCalls = 0;
  const writable = {
    async write(blob) {
      written.push(blob.number);
      if (blob.number === 2) {
        throw new Error("private write failure detail");
      }
    },
    async close() {
      closeCalls += 1;
    },
  };
  const writer = new SerialChunkWriter(writable);
  const writes = [1, 2, 3].map((number) => writer.enqueue(numberedBlob(number)));

  await assert.rejects(writer.close(), (error) =>
    assertSanitizedError(error, "write_failed"),
  );
  const results = await Promise.allSettled(writes);

  assert.deepEqual(written, [1, 2]);
  assert.equal(closeCalls, 0);
  assert.equal(results[0].status, "fulfilled");
  assert.equal(results[1].status, "rejected");
  assert.equal(results[2].status, "rejected");
  assertSanitizedError(results[1].reason, "write_failed");
  assertSanitizedError(results[2].reason, "write_failed");
});

test("reports only close_failed when the final close rejects", async () => {
  let closeCalls = 0;
  const writable = {
    async write() {},
    async close() {
      closeCalls += 1;
      throw new Error("private close failure detail");
    },
  };
  const writer = new SerialChunkWriter(writable);
  await writer.enqueue(numberedBlob(1));

  await assert.rejects(writer.close(), (error) =>
    assertSanitizedError(error, "close_failed"),
  );
  await assert.rejects(writer.close(), (error) =>
    assertSanitizedError(error, "close_failed"),
  );
  assert.equal(closeCalls, 1);
});

test("close owns finalization when abort follows on an empty queue", async () => {
  const closeGate = deferred();
  let closeCalls = 0;
  let abortCalls = 0;
  const writable = {
    async write() {},
    close() {
      closeCalls += 1;
      return closeGate.promise;
    },
    async abort() {
      abortCalls += 1;
    },
  };
  const writer = new SerialChunkWriter(writable);

  const closing = writer.close();
  const firstAbort = writer.abort();
  const secondAbort = writer.abort();
  await Promise.resolve();
  closeGate.resolve();
  const results = await Promise.allSettled([closing, firstAbort, secondAbort]);

  assert.equal(firstAbort, closing);
  assert.equal(secondAbort, closing);
  assert.deepEqual(
    results.map((result) => result.status),
    ["fulfilled", "fulfilled", "fulfilled"],
  );
  assert.equal(closeCalls, 1);
  assert.equal(abortCalls, 0);
});

test("close drains a pending write before an interleaved abort", async () => {
  const writeGate = deferred();
  const events = [];
  let abortCalls = 0;
  const writable = {
    write() {
      events.push("write");
      return writeGate.promise;
    },
    async close() {
      events.push("close");
    },
    async abort() {
      abortCalls += 1;
    },
  };
  const writer = new SerialChunkWriter(writable);
  const writing = writer.enqueue(numberedBlob(1));
  await Promise.resolve();

  const closing = writer.close();
  const aborting = writer.abort();
  assert.deepEqual(events, ["write"]);

  writeGate.resolve();
  const results = await Promise.allSettled([writing, closing, aborting]);

  assert.equal(aborting, closing);
  assert.deepEqual(
    results.map((result) => result.status),
    ["fulfilled", "fulfilled", "fulfilled"],
  );
  assert.deepEqual(events, ["write", "close"]);
  assert.equal(abortCalls, 0);
});

test("aborts idempotently and stops queued writes", async () => {
  const firstWrite = deferred();
  const written = [];
  let abortCalls = 0;
  const writable = {
    write(blob) {
      written.push(blob.number);
      return blob.number === 1 ? firstWrite.promise : Promise.resolve();
    },
    async close() {
      assert.fail("close must not run after abort");
    },
    async abort() {
      abortCalls += 1;
    },
  };
  const writer = new SerialChunkWriter(writable);
  const writes = [1, 2, 3].map((number) => writer.enqueue(numberedBlob(number)));
  await Promise.resolve();
  assert.deepEqual(written, [1]);

  const firstAbort = writer.abort();
  const secondAbort = writer.abort();
  const closing = writer.close();
  assert.equal(firstAbort, secondAbort);
  assert.equal(closing, firstAbort);
  firstWrite.resolve();
  await Promise.all([...writes, firstAbort, closing]);

  assert.deepEqual(written, [1]);
  assert.equal(abortCalls, 1);
});

test("abort then close stays neutral when the underlying abort rejects", async () => {
  let closeCalls = 0;
  let abortCalls = 0;
  const writable = {
    async write() {},
    async close() {
      closeCalls += 1;
    },
    async abort() {
      abortCalls += 1;
      throw new Error("private abort failure detail");
    },
  };
  const writer = new SerialChunkWriter(writable);

  const aborting = writer.abort();
  const closing = writer.close();
  assert.equal(closing, aborting);
  await Promise.all([aborting, closing]);
  assert.equal(abortCalls, 1);
  assert.equal(closeCalls, 0);
});

test("production core has no network, storage, media-link, or identity capability", async () => {
  const source = await readFile(
    new URL("../../browser_recorder_component/recorder_core.mjs", import.meta.url),
    "utf8",
  );
  const forbidden = [
    /fetch\s*\(/,
    /XMLHttpRequest/,
    /WebSocket/,
    /sendBeacon/,
    /RTCPeerConnection/,
    /localStorage/,
    /indexedDB/,
    /console\.log\s*\(/,
    /path/i,
    /filename/i,
  ];

  for (const capability of forbidden) {
    assert.doesNotMatch(source, capability);
  }
  assert.doesNotMatch(source, /^\s*import\s/m);
});

test("recorder app configuration uses only real component render arguments", async () => {
  const source = await readFile(
    new URL("../../browser_recorder_component/recorder_app.mjs", import.meta.url),
    "utf8",
  );

  assert.match(source, /args\?\.initial_mode/);
  assert.doesNotMatch(source, /lifecycle_key|component_key/);
});

class FakeElement {
  constructor(id, properties = {}) {
    this.id = id;
    this.listeners = new Map();
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.srcObject = null;
    this.state = "";
    this.scrollIntoViewCalls = [];
    Object.assign(this, properties);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  emit(type, fields = {}) {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ type, target: this, ...fields });
    }
  }

  replaceChildren(...children) {
    this.children = children;
  }

  removeAttribute(name) {
    delete this[name];
  }

  pause() {}

  load() {}

  play() {
    return Promise.resolve();
  }

  scrollIntoView(options) {
    this.scrollIntoViewCalls.push(options);
  }
}

class FakeWindow {
  constructor(parent) {
    this.parent = parent;
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  emit(type, fields = {}) {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ type, ...fields });
    }
  }
}

function fakeStream() {
  const tracks = ["video", "audio"].map((kind) => ({
    kind,
    onended: null,
    stopCalls: 0,
    stop() {
      this.stopCalls += 1;
    },
  }));
  return {
    tracks,
    get active() {
      return tracks.some((track) => track.stopCalls === 0);
    },
    getTracks: () => tracks,
    getVideoTracks: () => tracks.filter((track) => track.kind === "video"),
    getAudioTracks: () => tracks.filter((track) => track.kind === "audio"),
  };
}

function fakeWritable({ abortGate = null, writeGate = null, closeGate = null } = {}) {
  const calls = { writes: [], close: 0, abort: 0 };
  return {
    calls,
    write(blob) {
      calls.writes.push(blob.size);
      return writeGate?.promise ?? Promise.resolve();
    },
    close() {
      calls.close += 1;
      return closeGate?.promise ?? Promise.resolve();
    },
    abort() {
      calls.abort += 1;
      return abortGate?.promise ?? Promise.resolve();
    },
  };
}

async function settleRecorderApp() {
  for (let turn = 0; turn < 16; turn += 1) {
    await Promise.resolve();
  }
}

let recorderAppImport = 0;

async function recorderAppHarness({
  audioCloseGate = null,
  initialDevices = [],
  getUserMediaGate = null,
  getUserMediaImplementation = null,
  pickerGate = null,
  writable = fakeWritable(),
} = {}) {
  const savedDescriptors = new Map();
  const globalNames = [
    "window",
    "document",
    "navigator",
    "MediaRecorder",
    "Option",
    "requestAnimationFrame",
    "cancelAnimationFrame",
    "setTimeout",
    "clearTimeout",
    "performance",
  ];
  for (const name of globalNames) {
    savedDescriptors.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  }

  const modeDemo = new FakeElement("mode-demo", {
    name: "mode",
    value: "demo",
    checked: true,
  });
  const modeLong = new FakeElement("mode-long", {
    name: "mode",
    value: "long",
  });
  const ids = [
    "preview",
    "preview-placeholder",
    "camera-select",
    "microphone-select",
    "audio-meter",
    "timer",
    "record-button",
    "stop-button",
    "rerecord-button",
    "download-link",
    "skip-button",
    "status",
    "save-panel",
    "save-confirmation",
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, new FakeElement(id)]));
  elements.preview.srcObject = null;
  elements["audio-meter"].value = 0;
  const body = new FakeElement("body");
  const documentListeners = new Map();
  const document = {
    body,
    documentElement: { scrollHeight: 640 },
    getElementById(id) {
      return elements[id] ?? null;
    },
    querySelectorAll(selector) {
      assert.equal(selector, 'input[name="mode"]');
      return [modeDemo, modeLong];
    },
    addEventListener(type, listener) {
      const listeners = documentListeners.get(type) ?? [];
      listeners.push(listener);
      documentListeners.set(type, listeners);
    },
    emit(type, fields = {}) {
      for (const listener of documentListeners.get(type) ?? []) {
        listener({ type, ...fields });
      }
    },
  };

  const messages = [];
  let nowMilliseconds = 0;
  let nextTimerId = 1;
  const timeoutTasks = new Map();
  const parent = {
    postMessage(message) {
      messages.push(message);
    },
  };
  const window = new FakeWindow(parent);
  const stream = fakeStream();
  let getUserMediaCalls = 0;
  const mediaConstraints = [];
  let availableDevices = initialDevices;
  const mediaDeviceListeners = new Map();
  const mediaDevices = {
    getUserMedia(constraints) {
      getUserMediaCalls += 1;
      mediaConstraints.push(constraints);
      if (getUserMediaImplementation !== null) {
        return getUserMediaImplementation({
          call: getUserMediaCalls,
          constraints,
          defaultStream: stream,
        });
      }
      return getUserMediaGate?.promise ?? Promise.resolve(stream);
    },
    enumerateDevices() {
      return Promise.resolve(availableDevices);
    },
    addEventListener(type, listener) {
      const listeners = mediaDeviceListeners.get(type) ?? [];
      listeners.push(listener);
      mediaDeviceListeners.set(type, listeners);
    },
    removeEventListener(type, listener) {
      const listeners = mediaDeviceListeners.get(type) ?? [];
      mediaDeviceListeners.set(
        type,
        listeners.filter((candidate) => candidate !== listener),
      );
    },
  };
  const handleCalls = { picker: 0, createWritable: 0 };
  const handle = {
    createWritable() {
      handleCalls.createWritable += 1;
      return Promise.resolve(writable);
    },
  };
  window.showSaveFilePicker = () => {
    handleCalls.picker += 1;
    return pickerGate?.promise ?? Promise.resolve(handle);
  };
  const audioContexts = [];
  window.AudioContext = class {
    constructor() {
      this.state = "running";
      this.closeCalls = 0;
      audioContexts.push(this);
    }

    createAnalyser() {
      return {
        fftSize: 256,
        getByteTimeDomainData() {},
      };
    }

    createMediaStreamSource() {
      return { connect() {} };
    }

    resume() {
      return Promise.resolve();
    }

    close() {
      this.closeCalls += 1;
      this.state = "closed";
      return audioCloseGate?.promise ?? Promise.resolve();
    }
  };

  const recorderInstances = [];
  class FakeMediaRecorder {
    static isTypeSupported() {
      return true;
    }

    constructor(recorderStream, options) {
      this.stream = recorderStream;
      this.mimeType = options.mimeType;
      this.state = "inactive";
      this.ondataavailable = null;
      this.onerror = null;
      this.onstop = null;
      this.stopCalls = 0;
      recorderInstances.push(this);
    }

    start(timeslice) {
      assert.equal(timeslice, 1000);
      this.state = "recording";
    }

    stop() {
      this.stopCalls += 1;
      this.state = "inactive";
    }

    emitData(blob) {
      this.ondataavailable?.({ data: blob });
    }

    emitStop() {
      this.onstop?.();
    }
  }

  class FakeOption {
    constructor(text, value) {
      this.text = text;
      this.value = value;
    }
  }

  Object.defineProperties(globalThis, {
    window: { configurable: true, writable: true, value: window },
    document: { configurable: true, writable: true, value: document },
    navigator: {
      configurable: true,
      writable: true,
      value: { mediaDevices },
    },
    MediaRecorder: {
      configurable: true,
      writable: true,
      value: FakeMediaRecorder,
    },
    Option: { configurable: true, writable: true, value: FakeOption },
    requestAnimationFrame: {
      configurable: true,
      writable: true,
      value: () => 1,
    },
    cancelAnimationFrame: {
      configurable: true,
      writable: true,
      value: () => undefined,
    },
    setTimeout: {
      configurable: true,
      writable: true,
      value(callback, delay = 0) {
        const id = nextTimerId;
        nextTimerId += 1;
        timeoutTasks.set(id, {
          callback,
          due: nowMilliseconds + Math.max(0, Number(delay) || 0),
        });
        return id;
      },
    },
    clearTimeout: {
      configurable: true,
      writable: true,
      value(id) {
        timeoutTasks.delete(id);
      },
    },
    performance: {
      configurable: true,
      writable: true,
      value: { now: () => nowMilliseconds },
    },
  });

  const moduleUrl = new URL(
    "../../browser_recorder_component/recorder_app.mjs",
    import.meta.url,
  );
  moduleUrl.searchParams.set("test", String((recorderAppImport += 1)));
  await import(moduleUrl.href);

  function latestStatus() {
    const values = messages.filter(
      (message) => message.type === "streamlit:setComponentValue",
    );
    return values.at(-1)?.value ?? null;
  }

  function sendRender(mode) {
    window.emit("message", {
      source: parent,
      data: {
        type: "streamlit:render",
        args: { initial_mode: mode },
      },
    });
  }

  async function render(mode) {
    sendRender(mode);
    await settleRecorderApp();
  }

  async function advanceTime(milliseconds) {
    nowMilliseconds += milliseconds;
    while (true) {
      const due = Array.from(timeoutTasks.entries())
        .filter(([, task]) => task.due <= nowMilliseconds)
        .sort((left, right) => left[1].due - right[1].due);
      if (due.length === 0) {
        break;
      }
      const [id, task] = due[0];
      timeoutTasks.delete(id);
      task.callback();
      await settleRecorderApp();
    }
  }

  function emitDeviceChange() {
    for (const listener of mediaDeviceListeners.get("devicechange") ?? []) {
      listener({ type: "devicechange" });
    }
  }

  function setDevices(devices) {
    availableDevices = devices;
  }

  async function dispose() {
    window.emit("pagehide");
    await settleRecorderApp();
    for (const [name, descriptor] of savedDescriptors) {
      if (descriptor === undefined) {
        delete globalThis[name];
      } else {
        Object.defineProperty(globalThis, name, descriptor);
      }
    }
  }

  return {
    advanceTime,
    audioContexts,
    elements,
    emitDeviceChange,
    getUserMediaCalls: () => getUserMediaCalls,
    handleCalls,
    latestStatus,
    mediaConstraints,
    messages,
    modeInputs: [modeDemo, modeLong],
    recorderInstances,
    render,
    sendRender,
    setDevices,
    stream,
    window,
    writable,
    dispose,
  };
}

test("a configuration reset cancels a pending picker continuation", async () => {
  const pickerGate = deferred();
  const harness = await recorderAppHarness({ pickerGate });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    assert.equal(harness.handleCalls.picker, 1);

    await harness.render("demo");
    pickerGate.resolve({
      createWritable: async () => harness.writable,
    });
    await settleRecorderApp();

    assert.equal(harness.getUserMediaCalls(), 0);
    assert.equal(harness.handleCalls.createWritable, 0);
    assert.equal(harness.recorderInstances.length, 0);
    assert.equal(harness.latestStatus().mode, "demo");
    assert.equal(harness.latestStatus().state, "idle");
  } finally {
    await harness.dispose();
  }
});

test("pagehide disposes media that resolves after cleanup", async () => {
  const getUserMediaGate = deferred();
  const harness = await recorderAppHarness({ getUserMediaGate });
  try {
    await harness.render("demo");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    assert.equal(harness.getUserMediaCalls(), 1);

    harness.window.emit("pagehide");
    getUserMediaGate.resolve(harness.stream);
    await settleRecorderApp();

    assert.equal(harness.recorderInstances.length, 0);
    assert.equal(
      harness.stream.tracks.every((track) => track.stopCalls === 1),
      true,
    );
    assert.equal(harness.latestStatus().state, "idle");
  } finally {
    await harness.dispose();
  }
});

test("a stale close finalizer cannot overwrite reset state", async () => {
  const closeGate = deferred();
  const writable = fakeWritable({ closeGate });
  const harness = await recorderAppHarness({ writable });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    const recorder = harness.recorderInstances[0];
    assert.ok(recorder);

    harness.elements["stop-button"].emit("click");
    recorder.emitData(new Blob(["final"]));
    recorder.emitStop();
    await settleRecorderApp();
    assert.equal(writable.calls.close, 1);

    await harness.render("demo");
    assert.equal(harness.latestStatus().state, "idle");
    closeGate.resolve();
    await settleRecorderApp();

    assert.equal(harness.latestStatus().mode, "demo");
    assert.equal(harness.latestStatus().state, "idle");
  } finally {
    closeGate.resolve();
    await harness.dispose();
  }
});

test("long recording rejects a successful close with zero nonempty output", async () => {
  const writable = fakeWritable();
  const harness = await recorderAppHarness({ writable });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    const recorder = harness.recorderInstances[0];

    harness.elements["stop-button"].emit("click");
    recorder.emitData(new Blob([]));
    recorder.emitStop();
    await settleRecorderApp();

    assert.equal(writable.calls.writes.length, 0);
    assert.equal(writable.calls.close, 0);
    assert.equal(writable.calls.abort, 1);
    assert.equal(harness.latestStatus().state, "failed");
    assert.equal(harness.latestStatus().error_code, "write_failed");
    assert.equal(harness.latestStatus().saved_confirmed, false);
    assert.equal(harness.elements["save-confirmation"].disabled, true);
  } finally {
    await harness.dispose();
  }
});

test("final nonempty data drains before close and explicit confirmation", async () => {
  const writeGate = deferred();
  const writable = fakeWritable({ writeGate });
  const harness = await recorderAppHarness({ writable });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    const recorder = harness.recorderInstances[0];

    harness.elements["stop-button"].emit("click");
    recorder.emitData(new Blob(["final"]));
    recorder.emitStop();
    await settleRecorderApp();
    assert.deepEqual(writable.calls.writes, [5]);
    assert.equal(writable.calls.close, 0);

    writeGate.resolve();
    await settleRecorderApp();
    assert.equal(writable.calls.close, 1);
    assert.equal(harness.latestStatus().state, "stopped");
    assert.equal(harness.latestStatus().saved_confirmed, false);

    harness.elements["save-confirmation"].checked = true;
    harness.elements["save-confirmation"].emit("change");
    assert.equal(harness.latestStatus().state, "saved");
    assert.equal(harness.latestStatus().saved_confirmed, true);
  } finally {
    await harness.dispose();
  }
});

test("local completion panel follows finalized output through confirmation and reset", async () => {
  const harness = await recorderAppHarness();
  try {
    assert.equal(harness.elements["save-panel"].hidden, true);
    assert.deepEqual(harness.elements["save-panel"].scrollIntoViewCalls, []);

    await harness.render("long");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    assert.equal(harness.elements["save-panel"].hidden, true);
    assert.deepEqual(harness.elements["save-panel"].scrollIntoViewCalls, []);

    const recorder = harness.recorderInstances[0];
    recorder.emitData(numberedBlob(4));
    await settleRecorderApp();
    recorder.emitStop();
    await settleRecorderApp();

    assert.equal(harness.elements["save-panel"].hidden, false);
    assert.deepEqual(harness.elements["save-panel"].scrollIntoViewCalls, [
      { block: "nearest", behavior: "auto" },
    ]);
    assert.equal(
      harness.elements.status.textContent,
      "Recording stopped. Complete the three local-save steps below to continue.",
    );
    assert.deepEqual(harness.latestStatus(), {
      mode: "long",
      state: "stopped",
      duration_seconds: 0,
      camera_ready: false,
      microphone_ready: false,
      saved_confirmed: false,
      error_code: null,
    });

    harness.elements["save-confirmation"].checked = true;
    harness.elements["save-confirmation"].emit("change");

    assert.deepEqual(harness.latestStatus(), {
      mode: "long",
      state: "saved",
      duration_seconds: 0,
      camera_ready: false,
      microphone_ready: false,
      saved_confirmed: true,
      error_code: null,
    });
    assert.equal(harness.elements["save-panel"].hidden, false);
    assert.equal(harness.elements["save-panel"].scrollIntoViewCalls.length, 1);
    assert.equal(
      harness.elements.status.textContent,
      "Local recording saved and checked. Continuing to the next step.",
    );

    harness.elements["rerecord-button"].emit("click");
    await settleRecorderApp();
    assert.equal(harness.elements["save-panel"].hidden, true);
    assert.equal(harness.elements["save-panel"].scrollIntoViewCalls.length, 1);
  } finally {
    await harness.dispose();
  }
});

test("picker cancellation returns ready without creating a recorder or file", async () => {
  const pickerGate = deferred();
  const harness = await recorderAppHarness({ pickerGate });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    const cancelled = new Error("cancelled");
    cancelled.name = "AbortError";
    pickerGate.reject(cancelled);
    await settleRecorderApp();

    assert.equal(harness.getUserMediaCalls(), 1);
    assert.equal(harness.handleCalls.createWritable, 0);
    assert.equal(harness.recorderInstances.length, 0);
    assert.equal(harness.latestStatus().state, "ready");
  } finally {
    await harness.dispose();
  }
});

test("demo deadline stops recording when animation frames never run", async () => {
  const harness = await recorderAppHarness();
  try {
    await harness.render("demo");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    const recorder = harness.recorderInstances[0];
    assert.ok(recorder);

    await harness.advanceTime(299_999);
    assert.equal(recorder.stopCalls, 0);
    await harness.advanceTime(1);

    assert.equal(recorder.stopCalls, 1);
    assert.equal(recorder.state, "inactive");
  } finally {
    await harness.dispose();
  }
});

test("long warning and deadline run independently of animation frames", async () => {
  const harness = await recorderAppHarness();
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    const recorder = harness.recorderInstances[0];
    assert.ok(recorder);

    await harness.advanceTime(1_800_000);
    assert.equal(recorder.stopCalls, 0);
    assert.equal(
      harness.elements.status.textContent,
      "Recording is still in progress.",
    );

    await harness.advanceTime(900_000);
    assert.equal(recorder.stopCalls, 1);
    assert.equal(recorder.state, "inactive");
  } finally {
    await harness.dispose();
  }
});

test("a cleared mode deadline cannot stop a replacement recording", async () => {
  const harness = await recorderAppHarness();
  try {
    await harness.render("demo");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    const firstRecorder = harness.recorderInstances[0];
    assert.ok(firstRecorder);

    await harness.advanceTime(100_000);
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    const replacementRecorder = harness.recorderInstances[1];
    assert.ok(replacementRecorder);

    await harness.advanceTime(200_000);
    assert.equal(firstRecorder.stopCalls, 1);
    assert.equal(replacementRecorder.stopCalls, 0);
    assert.equal(replacementRecorder.state, "recording");
  } finally {
    await harness.dispose();
  }
});

test("skip cleanup gates record until a pending audio close completes", async () => {
  const audioCloseGate = deferred();
  const pickerGate = deferred();
  const harness = await recorderAppHarness({ audioCloseGate, pickerGate });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    const cancelled = new Error("cancelled");
    cancelled.name = "AbortError";
    pickerGate.reject(cancelled);
    await settleRecorderApp();
    assert.equal(harness.latestStatus().state, "ready");

    harness.elements["skip-button"].emit("click");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();

    assert.equal(harness.elements["record-button"].disabled, true);
    assert.equal(harness.modeInputs.every((input) => input.disabled), true);
    assert.equal(harness.elements["camera-select"].disabled, true);
    assert.equal(harness.elements["microphone-select"].disabled, true);
    assert.equal(harness.elements["skip-button"].disabled, true);
    assert.equal(harness.handleCalls.picker, 1);
    assert.equal(harness.getUserMediaCalls(), 1);
    assert.equal(harness.recorderInstances.length, 0);

    audioCloseGate.resolve();
    await settleRecorderApp();
    assert.equal(harness.latestStatus().state, "skipped");
    assert.equal(
      harness.stream.tracks.every((track) => track.stopCalls === 1),
      true,
    );
  } finally {
    audioCloseGate.resolve();
    await harness.dispose();
  }
});

test("configuration cleanup does not wait for a pending audio close", async () => {
  const audioCloseGate = deferred();
  const pickerGate = deferred();
  const harness = await recorderAppHarness({ audioCloseGate, pickerGate });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    const cancelled = new Error("cancelled");
    cancelled.name = "AbortError";
    pickerGate.reject(cancelled);
    await settleRecorderApp();
    assert.equal(harness.latestStatus().state, "ready");

    await harness.render("demo");
    assert.equal(harness.latestStatus().mode, "demo");
    assert.equal(harness.latestStatus().state, "idle");
    assert.equal(harness.elements["record-button"].disabled, false);
    assert.equal(harness.audioContexts[0].closeCalls, 1);
    assert.equal(
      harness.stream.tracks.every((track) => track.stopCalls === 1),
      true,
    );

    harness.elements["record-button"].emit("click");
    await settleRecorderApp();

    assert.equal(harness.elements["record-button"].disabled, true);
    assert.equal(harness.modeInputs.every((input) => input.disabled), true);
    assert.equal(harness.elements["camera-select"].disabled, true);
    assert.equal(harness.elements["microphone-select"].disabled, true);
    assert.equal(harness.elements["skip-button"].disabled, true);
    assert.equal(harness.handleCalls.picker, 1);
    assert.equal(harness.getUserMediaCalls(), 2);
    assert.equal(harness.recorderInstances.length, 1);
    assert.equal(harness.latestStatus().state, "recording");

    audioCloseGate.resolve();
    await settleRecorderApp();
    assert.equal(harness.latestStatus().mode, "demo");
    assert.equal(harness.latestStatus().state, "recording");
  } finally {
    audioCloseGate.resolve();
    await harness.dispose();
  }
});

test("configuration cleanup stops recorder and tracks before a hanging writer abort", async () => {
  const abortGate = deferred();
  const writable = fakeWritable({ abortGate });
  const harness = await recorderAppHarness({ writable });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    const recorder = harness.recorderInstances[0];
    assert.ok(recorder);

    harness.sendRender("demo");

    assert.equal(recorder.stopCalls, 1);
    assert.equal(
      harness.stream.tracks.every((track) => track.stopCalls === 1),
      true,
    );
    await settleRecorderApp();
    assert.equal(writable.calls.abort, 1);
    assert.equal(harness.latestStatus().mode, "demo");
    assert.equal(harness.latestStatus().state, "idle");
  } finally {
    abortGate.resolve();
    await harness.dispose();
  }
});

test("pagehide synchronously tears down media despite a hanging writer abort", async () => {
  const abortGate = deferred();
  const writable = fakeWritable({ abortGate });
  const harness = await recorderAppHarness({ writable });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();
    const recorder = harness.recorderInstances[0];

    harness.window.emit("pagehide");

    assert.equal(recorder.stopCalls, 1);
    assert.equal(
      harness.stream.tracks.every((track) => track.stopCalls === 1),
      true,
    );
    await settleRecorderApp();
    assert.equal(writable.calls.abort, 1);
  } finally {
    abortGate.resolve();
    await harness.dispose();
  }
});

test("rapid device changes and record share one pending media setup", async () => {
  const pickerGate = deferred();
  const replacementGate = deferred();
  const firstStream = fakeStream();
  const replacementStream = fakeStream();
  const unexpectedStreams = [];
  const harness = await recorderAppHarness({
    pickerGate,
    getUserMediaImplementation({ call }) {
      if (call === 1) {
        return Promise.resolve(firstStream);
      }
      if (call === 2) {
        return replacementGate.promise;
      }
      const unexpected = fakeStream();
      unexpectedStreams.push(unexpected);
      return Promise.resolve(unexpected);
    },
  });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    const cancelled = new Error("cancelled");
    cancelled.name = "AbortError";
    pickerGate.reject(cancelled);
    await settleRecorderApp();
    assert.equal(harness.latestStatus().state, "ready");

    harness.elements["camera-select"].value = "usb-camera";
    harness.elements["camera-select"].emit("change");
    harness.elements["microphone-select"].value = "usb-microphone";
    harness.elements["microphone-select"].emit("change");
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();

    assert.equal(harness.getUserMediaCalls(), 2);
    assert.equal(harness.elements["record-button"].disabled, true);
    assert.equal(harness.elements["camera-select"].disabled, true);
    assert.equal(harness.elements["microphone-select"].disabled, true);
    assert.equal(harness.recorderInstances.length, 0);

    replacementGate.resolve(replacementStream);
    await settleRecorderApp();
    assert.equal(firstStream.tracks.every((track) => track.stopCalls === 1), true);
    assert.equal(
      replacementStream.tracks.every((track) => track.stopCalls === 0),
      true,
    );
    assert.equal(
      unexpectedStreams.every((candidate) =>
        candidate.tracks.every((track) => track.stopCalls === 1),
      ),
      true,
    );
    assert.equal(
      harness.audioContexts.filter((context) => context.state === "running").length,
      1,
    );
  } finally {
    replacementGate.resolve(replacementStream);
    await harness.dispose();
  }
});

test("a replacement stream resolving after configuration cleanup is stopped", async () => {
  const pickerGate = deferred();
  const replacementGate = deferred();
  const firstStream = fakeStream();
  const replacementStream = fakeStream();
  const harness = await recorderAppHarness({
    pickerGate,
    getUserMediaImplementation({ call }) {
      return call === 1 ? Promise.resolve(firstStream) : replacementGate.promise;
    },
  });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    const cancelled = new Error("cancelled");
    cancelled.name = "AbortError";
    pickerGate.reject(cancelled);
    await settleRecorderApp();

    harness.elements["camera-select"].value = "usb-camera";
    harness.elements["camera-select"].emit("change");
    await settleRecorderApp();
    assert.equal(harness.getUserMediaCalls(), 2);

    harness.sendRender("demo");
    await settleRecorderApp();
    assert.equal(harness.elements["record-button"].disabled, true);
    replacementGate.resolve(replacementStream);
    await settleRecorderApp();

    assert.equal(
      replacementStream.tracks.every((track) => track.stopCalls === 1),
      true,
    );
    assert.equal(harness.latestStatus().mode, "demo");
    assert.equal(harness.latestStatus().state, "idle");
  } finally {
    replacementGate.resolve(replacementStream);
    await harness.dispose();
  }
});

test("devicechange clears a missing exact device and rebuilds with defaults", async () => {
  const pickerGate = deferred();
  const firstStream = fakeStream();
  const usbStream = fakeStream();
  const recoveredStream = fakeStream();
  const harness = await recorderAppHarness({
    pickerGate,
    initialDevices: [
      { kind: "videoinput", deviceId: "usb-camera", label: "USB camera" },
      { kind: "videoinput", deviceId: "built-in-camera", label: "Built-in camera" },
      { kind: "audioinput", deviceId: "built-in-mic", label: "Built-in mic" },
    ],
    getUserMediaImplementation({ call }) {
      return Promise.resolve(
        call === 1 ? firstStream : call === 2 ? usbStream : recoveredStream,
      );
    },
  });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    const cancelled = new Error("cancelled");
    cancelled.name = "AbortError";
    pickerGate.reject(cancelled);
    await settleRecorderApp();

    harness.elements["camera-select"].value = "usb-camera";
    harness.elements["camera-select"].emit("change");
    await settleRecorderApp();
    assert.deepEqual(harness.mediaConstraints[1].video.deviceId, {
      exact: "usb-camera",
    });

    harness.setDevices([
      { kind: "videoinput", deviceId: "built-in-camera", label: "Built-in camera" },
      { kind: "audioinput", deviceId: "built-in-mic", label: "Built-in mic" },
    ]);
    harness.emitDeviceChange();
    await settleRecorderApp();

    assert.equal(harness.elements["camera-select"].value, "");
    assert.equal(harness.getUserMediaCalls(), 3);
    assert.equal(Object.hasOwn(harness.mediaConstraints[2].video, "deviceId"), false);
    assert.equal(usbStream.tracks.every((track) => track.stopCalls === 1), true);
    assert.equal(
      recoveredStream.tracks.every((track) => track.stopCalls === 0),
      true,
    );
    assert.equal(harness.latestStatus().state, "ready");
  } finally {
    await harness.dispose();
  }
});

test("track end clears stale exact device before record-again media setup", async () => {
  const pickerGate = deferred();
  const firstStream = fakeStream();
  const usbStream = fakeStream();
  const recoveredStream = fakeStream();
  const harness = await recorderAppHarness({
    pickerGate,
    initialDevices: [
      { kind: "videoinput", deviceId: "usb-camera", label: "USB camera" },
      { kind: "audioinput", deviceId: "built-in-mic", label: "Built-in mic" },
    ],
    getUserMediaImplementation({ call }) {
      return Promise.resolve(
        call === 1 ? firstStream : call === 2 ? usbStream : recoveredStream,
      );
    },
  });
  try {
    await harness.render("long");
    harness.elements["record-button"].emit("click");
    const cancelled = new Error("cancelled");
    cancelled.name = "AbortError";
    pickerGate.reject(cancelled);
    await settleRecorderApp();

    harness.elements["camera-select"].value = "usb-camera";
    harness.elements["camera-select"].emit("change");
    await settleRecorderApp();
    harness.setDevices([
      { kind: "videoinput", deviceId: "built-in-camera", label: "Built-in camera" },
      { kind: "audioinput", deviceId: "built-in-mic", label: "Built-in mic" },
    ]);

    usbStream.getVideoTracks()[0].onended();
    await settleRecorderApp();
    assert.equal(harness.latestStatus().state, "failed");
    assert.equal(harness.elements["camera-select"].value, "");

    harness.elements["rerecord-button"].emit("click");
    await settleRecorderApp();
    harness.elements["record-button"].emit("click");
    await settleRecorderApp();

    assert.equal(harness.getUserMediaCalls(), 3);
    assert.equal(Object.hasOwn(harness.mediaConstraints[2].video, "deviceId"), false);
    assert.equal(harness.latestStatus().state, "ready");
  } finally {
    await harness.dispose();
  }
});
