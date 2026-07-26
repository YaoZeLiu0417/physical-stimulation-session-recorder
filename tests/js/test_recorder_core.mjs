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
