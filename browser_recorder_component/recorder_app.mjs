import {
  LIMITS,
  SerialChunkWriter,
  chooseMimeType,
  createStatus,
  formatDuration,
} from "./recorder_core.mjs";

const elements = Object.freeze({
  preview: document.getElementById("preview"),
  previewPlaceholder: document.getElementById("preview-placeholder"),
  modeInputs: Array.from(document.querySelectorAll('input[name="mode"]')),
  cameraSelect: document.getElementById("camera-select"),
  microphoneSelect: document.getElementById("microphone-select"),
  audioMeter: document.getElementById("audio-meter"),
  timer: document.getElementById("timer"),
  recordButton: document.getElementById("record-button"),
  stopButton: document.getElementById("stop-button"),
  rerecordButton: document.getElementById("rerecord-button"),
  downloadLink: document.getElementById("download-link"),
  skipButton: document.getElementById("skip-button"),
  status: document.getElementById("status"),
  saveConfirmation: document.getElementById("save-confirmation"),
});

const ERROR_MESSAGES = Object.freeze({
  permission_denied: "Camera or microphone permission was not granted.",
  camera_unavailable: "A camera is not available.",
  microphone_unavailable: "A microphone is not available.",
  device_lost: "A recording device became unavailable.",
  unsupported_format: "This browser cannot create the local recording format.",
  write_failed: "The local recording could not be written.",
  close_failed: "The local recording could not be finalized.",
});

let status = createStatus();
let configurationKey = null;
let componentHasRendered = false;
let startPending = false;
let lifecycleGeneration = 0;
let mediaStream = null;
let mediaRecorder = null;
let audioContext = null;
let analyser = null;
let meterFrameId = null;
let timerFrameId = null;
let warningTimeoutId = null;
let deadlineTimeoutId = null;
let recordingStartedAt = 0;
let recordingGeneration = null;
let lastTimerSecond = -1;
let longWarningShown = false;
let demoChunks = [];
let localObjectUrl = null;
let writer = null;
let observedWrites = new Set();
let writeFailure = false;
let successfulLongBytes = 0;
let pendingFailureCode = null;
let localCompletionReady = false;
let cleanupPromise = null;
let cleaningUp = false;
let resizeObserver = null;

function isCurrentLifecycle(generation) {
  return generation === lifecycleGeneration;
}

function invalidateLifecycle() {
  lifecycleGeneration += 1;
  startPending = false;
  return lifecycleGeneration;
}

function stopDetachedStream(stream) {
  for (const track of stream.getTracks()) {
    track.onended = null;
    track.stop();
  }
}

function sendStreamlitMessage(type, fields = {}) {
  window.parent.postMessage(
    {
      isStreamlitMessage: true,
      type,
      ...fields,
    },
    "*",
  );
}

function reportFrameHeight() {
  sendStreamlitMessage("streamlit:setFrameHeight", {
    height: Math.ceil(document.documentElement.scrollHeight),
  });
}

function publishStatus() {
  const value = createStatus(status);
  sendStreamlitMessage("streamlit:setComponentValue", { value });
}

function statusMessage() {
  if (status.error_code !== null) {
    return ERROR_MESSAGES[status.error_code];
  }
  if (status.state === "ready") {
    return "Camera and microphone are ready.";
  }
  if (status.state === "recording") {
    return "Recording locally.";
  }
  if (status.state === "stopped") {
    return "Recording stopped. Confirm the local save when ready.";
  }
  if (status.state === "saved") {
    return "Local save confirmed.";
  }
  if (status.state === "skipped") {
    return "Recording skipped.";
  }
  if (status.state === "failed") {
    return "The local recording could not continue.";
  }
  return "Ready to record locally.";
}

function renderControls(message = null) {
  const isRecording = status.state === "recording";
  const canStart =
    componentHasRendered &&
    !startPending &&
    !cleaningUp &&
    cleanupPromise === null &&
    (status.state === "idle" || status.state === "ready");
  const canChangeSetup = canStart && !isRecording;
  const canRecordAgain = ["stopped", "saved", "skipped", "failed"].includes(
    status.state,
  );

  for (const input of elements.modeInputs) {
    input.checked = input.value === status.mode;
    input.disabled = !canChangeSetup;
  }
  elements.cameraSelect.disabled = !mediaStream || !canChangeSetup;
  elements.microphoneSelect.disabled = !mediaStream || !canChangeSetup;
  elements.recordButton.disabled = !canStart;
  elements.stopButton.disabled = !isRecording || cleaningUp;
  elements.rerecordButton.hidden = !canRecordAgain;
  elements.rerecordButton.disabled = cleaningUp;
  elements.skipButton.disabled = !canStart;
  elements.saveConfirmation.disabled =
    cleaningUp || !localCompletionReady || status.state === "saved";
  elements.saveConfirmation.checked = status.saved_confirmed;
  elements.downloadLink.hidden = localObjectUrl === null;
  elements.timer.textContent = formatDuration(status.duration_seconds);
  elements.status.textContent = message ?? statusMessage();
  reportFrameHeight();
}

function updateStatus(fields, message = null, shouldPublish = true) {
  status = createStatus({ ...status, ...fields });
  renderControls(message);
  if (shouldPublish) {
    publishStatus();
  }
}

function selectedMode() {
  return elements.modeInputs.find((input) => input.checked)?.value === "long"
    ? "long"
    : "demo";
}

function makeNeutralDownloadName() {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `session-recording-${stamp}.webm`;
}

function clearLocalPlayback() {
  if (localObjectUrl !== null) {
    URL.revokeObjectURL(localObjectUrl);
    localObjectUrl = null;
  }
  elements.downloadLink.hidden = true;
  elements.downloadLink.removeAttribute("href");
  elements.downloadLink.removeAttribute("download");
  if (elements.preview.srcObject === null) {
    elements.preview.pause();
    elements.preview.removeAttribute("src");
    elements.preview.load();
    elements.preview.controls = false;
    elements.preview.muted = true;
    elements.previewPlaceholder.hidden = false;
  }
}

function cancelRecordingTimer() {
  if (timerFrameId !== null) {
    cancelAnimationFrame(timerFrameId);
    timerFrameId = null;
  }
  if (warningTimeoutId !== null) {
    clearTimeout(warningTimeoutId);
    warningTimeoutId = null;
  }
  if (deadlineTimeoutId !== null) {
    clearTimeout(deadlineTimeoutId);
    deadlineTimeoutId = null;
  }
}

async function stopAudioMeter() {
  if (meterFrameId !== null) {
    cancelAnimationFrame(meterFrameId);
    meterFrameId = null;
  }
  analyser = null;
  elements.audioMeter.value = 0;
  const context = audioContext;
  audioContext = null;
  if (context !== null && context.state !== "closed") {
    await context.close().catch(() => undefined);
  }
}

async function releaseMediaStream() {
  const stream = mediaStream;
  mediaStream = null;
  if (stream !== null) {
    stopDetachedStream(stream);
  }
  if (elements.preview.srcObject === stream) {
    elements.preview.srcObject = null;
    if (localObjectUrl === null) {
      elements.previewPlaceholder.hidden = false;
    }
  }
  await stopAudioMeter();
}

function stopRecorderWithoutFinalizing() {
  const recorder = mediaRecorder;
  mediaRecorder = null;
  if (recorder === null) {
    return;
  }
  recorder.ondataavailable = null;
  recorder.onerror = null;
  recorder.onstop = null;
  if (recorder.state !== "inactive") {
    try {
      recorder.stop();
    } catch {
      // Cleanup is already in progress.
    }
  }
}

async function cleanupLocalResources({ revokePlayback = true } = {}) {
  if (cleanupPromise !== null) {
    return cleanupPromise;
  }

  cleaningUp = true;
  renderControls("Finishing local cleanup.");
  cleanupPromise = (async () => {
    cancelRecordingTimer();
    recordingGeneration = null;
    stopRecorderWithoutFinalizing();
    const activeWriter = writer;
    writer = null;
    observedWrites = new Set();
    if (activeWriter !== null) {
      await activeWriter.abort().catch(() => undefined);
    }
    await releaseMediaStream();
    if (revokePlayback) {
      clearLocalPlayback();
    }
    demoChunks = [];
    pendingFailureCode = null;
    writeFailure = false;
    successfulLongBytes = 0;
    longWarningShown = false;
    localCompletionReady = false;
  })().finally(() => {
    cleaningUp = false;
    cleanupPromise = null;
    renderControls();
  });
  return cleanupPromise;
}

function failWithCode(code, generation = lifecycleGeneration) {
  if (!isCurrentLifecycle(generation)) {
    return;
  }
  updateStatus({
    state: "failed",
    camera_ready: false,
    microphone_ready: false,
    saved_confirmed: false,
    error_code: code,
  });
  invalidateLifecycle();
  void cleanupLocalResources().catch(() => undefined);
}

function mediaErrorCode(error, unavailableCode = "camera_unavailable") {
  const name = typeof error?.name === "string" ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "permission_denied";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return unavailableCode;
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "device_lost";
  }
  return unavailableCode;
}

function recordingConstraints() {
  const video = {
    width: { ideal: 1280 },
    height: { ideal: 720 },
    frameRate: { ideal: 30 },
  };
  const audio = {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  };
  if (elements.cameraSelect.value) {
    video.deviceId = { exact: elements.cameraSelect.value };
  }
  if (elements.microphoneSelect.value) {
    audio.deviceId = { exact: elements.microphoneSelect.value };
  }
  return { video, audio };
}

function replaceSelectOptions(select, devices, defaultText, selectedValue) {
  const options = [new Option(defaultText, "")];
  devices.forEach((device, index) => {
    const fallback = `${defaultText.replace("Default ", "")} ${index + 1}`;
    options.push(new Option(device.label || fallback, device.deviceId));
  });
  select.replaceChildren(...options);
  select.value = devices.some((device) => device.deviceId === selectedValue)
    ? selectedValue
    : "";
}

async function populateDeviceSelectors(generation) {
  const selectedCamera = elements.cameraSelect.value;
  const selectedMicrophone = elements.microphoneSelect.value;
  let devices;
  try {
    devices = await navigator.mediaDevices.enumerateDevices();
  } catch {
    return;
  }
  if (!isCurrentLifecycle(generation)) {
    return;
  }
  replaceSelectOptions(
    elements.cameraSelect,
    devices.filter((device) => device.kind === "videoinput"),
    "Default camera",
    selectedCamera,
  );
  replaceSelectOptions(
    elements.microphoneSelect,
    devices.filter((device) => device.kind === "audioinput"),
    "Default microphone",
    selectedMicrophone,
  );
}

function startAudioMeter(stream) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (typeof AudioContextClass !== "function" || stream.getAudioTracks().length === 0) {
    return;
  }
  try {
    audioContext = new AudioContextClass();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    const source = audioContext.createMediaStreamSource(stream);
    source.connect(analyser);
    void audioContext.resume().catch(() => undefined);
  } catch {
    audioContext = null;
    analyser = null;
    return;
  }

  const samples = new Uint8Array(analyser.fftSize);
  const updateMeter = () => {
    if (analyser === null) {
      return;
    }
    analyser.getByteTimeDomainData(samples);
    let energy = 0;
    for (const sample of samples) {
      const centered = (sample - 128) / 128;
      energy += centered * centered;
    }
    elements.audioMeter.value = Math.min(1, Math.sqrt(energy / samples.length) * 2.5);
    meterFrameId = requestAnimationFrame(updateMeter);
  };
  meterFrameId = requestAnimationFrame(updateMeter);
}

function handleUnexpectedTrackEnd(generation) {
  if (cleaningUp || !isCurrentLifecycle(generation)) {
    return;
  }
  if (status.state === "recording") {
    pendingFailureCode = "device_lost";
    requestRecorderStop();
    return;
  }
  failWithCode("device_lost", generation);
}

async function ensureMediaReady(
  unavailableCode = "camera_unavailable",
  generation = lifecycleGeneration,
) {
  if (!isCurrentLifecycle(generation)) {
    return false;
  }
  if (mediaStream !== null && mediaStream.active) {
    return true;
  }

  clearLocalPlayback();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia(recordingConstraints());
  } catch (error) {
    failWithCode(mediaErrorCode(error, unavailableCode), generation);
    return false;
  }
  if (!isCurrentLifecycle(generation)) {
    stopDetachedStream(stream);
    return false;
  }

  mediaStream = stream;
  for (const track of stream.getTracks()) {
    track.onended = () => handleUnexpectedTrackEnd(generation);
  }
  elements.preview.controls = false;
  elements.preview.muted = true;
  elements.preview.srcObject = stream;
  elements.previewPlaceholder.hidden = true;
  void elements.preview.play().catch(() => undefined);
  await populateDeviceSelectors(generation);
  if (!isCurrentLifecycle(generation)) {
    if (mediaStream === stream) {
      mediaStream = null;
      stopDetachedStream(stream);
      elements.preview.srcObject = null;
      elements.previewPlaceholder.hidden = false;
    }
    return false;
  }
  startAudioMeter(stream);
  const cameraReady = stream.getVideoTracks().length > 0;
  const microphoneReady = stream.getAudioTracks().length > 0;
  if (!cameraReady || !microphoneReady) {
    failWithCode(
      cameraReady ? "microphone_unavailable" : "camera_unavailable",
      generation,
    );
    return false;
  }
  updateStatus({
    state: "ready",
    camera_ready: true,
    microphone_ready: true,
    saved_confirmed: false,
    error_code: null,
  });
  return true;
}

function observeChunkWrite(chunk, generation) {
  if (!isCurrentLifecycle(generation)) {
    return;
  }
  if (writer === null) {
    writeFailure = true;
    pendingFailureCode = "write_failed";
    requestRecorderStop();
    return;
  }
  const observed = writer.enqueue(chunk).then(
    () => {
      if (isCurrentLifecycle(generation)) {
        successfulLongBytes += chunk.size;
      }
    },
    () => {
      if (isCurrentLifecycle(generation)) {
        writeFailure = true;
        pendingFailureCode = "write_failed";
        requestRecorderStop();
      }
    },
  );
  observedWrites.add(observed);
  void observed
    .finally(() => {
      observedWrites.delete(observed);
    })
    .catch(() => undefined);
}

function handleRecordedData(event, mode, generation) {
  if (
    cleaningUp ||
    !isCurrentLifecycle(generation) ||
    !event.data ||
    event.data.size <= 0
  ) {
    return;
  }
  if (mode === "long") {
    observeChunkWrite(event.data, generation);
  } else {
    demoChunks.push(event.data);
  }
}

function requestRecorderStop() {
  recordingGeneration = null;
  cancelRecordingTimer();
  if (mediaRecorder !== null && mediaRecorder.state === "recording") {
    try {
      mediaRecorder.stop();
    } catch {
      pendingFailureCode = pendingFailureCode ?? "device_lost";
    }
  }
}

function recordingDurationSeconds() {
  const maximum = status.mode === "long" ? LIMITS.longMax : LIMITS.demoMax;
  const elapsed = Math.floor((performance.now() - recordingStartedAt) / 1000);
  return Math.min(maximum, Math.max(0, elapsed));
}

function syncRecordingClock(message = null) {
  if (status.state !== "recording") {
    return;
  }
  const duration = recordingDurationSeconds();
  const persistentMessage = longWarningShown
    ? "Recording is still in progress."
    : message;
  if (duration !== lastTimerSecond || persistentMessage !== null) {
    lastTimerSecond = duration;
    updateStatus({ duration_seconds: duration }, persistentMessage);
  }
}

function clearRecordingDeadlineTimeouts() {
  if (warningTimeoutId !== null) {
    clearTimeout(warningTimeoutId);
    warningTimeoutId = null;
  }
  if (deadlineTimeoutId !== null) {
    clearTimeout(deadlineTimeoutId);
    deadlineTimeoutId = null;
  }
}

function armRecordingDeadlines(generation) {
  clearRecordingDeadlineTimeouts();
  if (
    cleaningUp ||
    recordingGeneration !== generation ||
    !isCurrentLifecycle(generation) ||
    status.state !== "recording"
  ) {
    return;
  }

  const now = performance.now();
  if (status.mode === "long" && !longWarningShown) {
    const warningDelay = Math.max(
      0,
      recordingStartedAt + LIMITS.longWarning * 1000 - now,
    );
    warningTimeoutId = setTimeout(() => {
      warningTimeoutId = null;
      reconcileRecordingDeadlines(generation);
    }, warningDelay);
  }
  const maximum = status.mode === "long" ? LIMITS.longMax : LIMITS.demoMax;
  const deadlineDelay = Math.max(
    0,
    recordingStartedAt + maximum * 1000 - now,
  );
  deadlineTimeoutId = setTimeout(() => {
    deadlineTimeoutId = null;
    reconcileRecordingDeadlines(generation);
  }, deadlineDelay);
}

function reconcileRecordingDeadlines(generation) {
  if (
    cleaningUp ||
    recordingGeneration !== generation ||
    !isCurrentLifecycle(generation) ||
    status.state !== "recording"
  ) {
    return;
  }

  const elapsedMilliseconds = Math.max(0, performance.now() - recordingStartedAt);
  if (
    status.mode === "long" &&
    elapsedMilliseconds >= LIMITS.longWarning * 1000
  ) {
    longWarningShown = true;
  }
  syncRecordingClock();
  const maximum = status.mode === "long" ? LIMITS.longMax : LIMITS.demoMax;
  if (elapsedMilliseconds >= maximum * 1000) {
    requestRecorderStop();
    return;
  }
  armRecordingDeadlines(generation);
}

function updateRecordingTimer() {
  if (
    recordingGeneration === null ||
    !isCurrentLifecycle(recordingGeneration) ||
    status.state !== "recording"
  ) {
    return;
  }
  syncRecordingClock();
  timerFrameId = requestAnimationFrame(updateRecordingTimer);
}

async function finishLongRecording(generation) {
  await Promise.all(Array.from(observedWrites));
  if (!isCurrentLifecycle(generation)) {
    return null;
  }
  const activeWriter = writer;
  writer = null;
  if (
    activeWriter === null ||
    writeFailure ||
    pendingFailureCode !== null ||
    successfulLongBytes <= 0
  ) {
    if (activeWriter !== null) {
      await activeWriter.abort().catch(() => undefined);
    }
    if (isCurrentLifecycle(generation)) {
      pendingFailureCode = pendingFailureCode ?? "write_failed";
    }
    return false;
  }
  try {
    await activeWriter.close();
  } catch (error) {
    if (isCurrentLifecycle(generation)) {
      pendingFailureCode =
        error?.code === "close_failed" ? "close_failed" : "write_failed";
    }
    return false;
  }
  if (!isCurrentLifecycle(generation)) {
    return null;
  }
  localCompletionReady = true;
  return true;
}

async function finishDemoRecording(recorder, generation) {
  if (
    !isCurrentLifecycle(generation) ||
    pendingFailureCode !== null ||
    demoChunks.length === 0
  ) {
    pendingFailureCode = pendingFailureCode ?? "unsupported_format";
    return false;
  }
  const recording = new Blob(demoChunks, {
    type: recorder.mimeType || "video/webm",
  });
  clearLocalPlayback();
  localObjectUrl = URL.createObjectURL(recording);
  elements.downloadLink.href = localObjectUrl;
  elements.downloadLink.download = makeNeutralDownloadName();
  elements.downloadLink.hidden = false;
  elements.preview.srcObject = null;
  elements.preview.src = localObjectUrl;
  elements.preview.controls = true;
  elements.preview.muted = false;
  elements.previewPlaceholder.hidden = true;
  elements.preview.load();
  localCompletionReady = true;
  return true;
}

async function finalizeRecording(mode, recorder, generation) {
  if (
    cleaningUp ||
    !isCurrentLifecycle(generation) ||
    recorder !== mediaRecorder
  ) {
    return;
  }
  cancelRecordingTimer();
  recordingGeneration = null;
  mediaRecorder = null;
  recorder.ondataavailable = null;
  recorder.onerror = null;
  recorder.onstop = null;

  let completed = false;
  if (mode === "long") {
    completed = await finishLongRecording(generation);
  } else {
    completed = await finishDemoRecording(recorder, generation);
  }
  if (!isCurrentLifecycle(generation) || completed === null) {
    return;
  }
  await releaseMediaStream();
  if (!isCurrentLifecycle(generation)) {
    return;
  }

  if (!completed) {
    const code = pendingFailureCode ?? "write_failed";
    pendingFailureCode = null;
    failWithCode(code, generation);
    return;
  }
  updateStatus({
    state: "stopped",
    camera_ready: false,
    microphone_ready: false,
    saved_confirmed: false,
    error_code: null,
  });
}

function beginRecording(
  mode,
  activeWriter = null,
  generation = lifecycleGeneration,
) {
  if (!isCurrentLifecycle(generation)) {
    if (activeWriter !== null) {
      void activeWriter.abort().catch(() => undefined);
    }
    return false;
  }
  const mimeType = chooseMimeType((candidate) =>
    MediaRecorder.isTypeSupported(candidate),
  );
  if (mimeType === null || mediaStream === null) {
    if (activeWriter !== null) {
      void activeWriter.abort().catch(() => undefined);
    }
    failWithCode("unsupported_format", generation);
    return false;
  }

  let recorder;
  try {
    recorder = new MediaRecorder(mediaStream, { mimeType });
  } catch {
    if (activeWriter !== null) {
      void activeWriter.abort().catch(() => undefined);
    }
    failWithCode("unsupported_format", generation);
    return false;
  }

  demoChunks = [];
  writer = activeWriter;
  observedWrites = new Set();
  writeFailure = false;
  successfulLongBytes = 0;
  pendingFailureCode = null;
  localCompletionReady = false;
  elements.saveConfirmation.checked = false;
  mediaRecorder = recorder;
  recorder.ondataavailable = (event) =>
    handleRecordedData(event, mode, generation);
  recorder.onerror = () => {
    if (!isCurrentLifecycle(generation)) {
      return;
    }
    pendingFailureCode = "device_lost";
    requestRecorderStop();
  };
  recorder.onstop = () => {
    void finalizeRecording(mode, recorder, generation).catch(() =>
      failWithCode("write_failed", generation),
    );
  };

  try {
    recorder.start(1000);
  } catch {
    mediaRecorder = null;
    if (activeWriter !== null) {
      void activeWriter.abort().catch(() => undefined);
    }
    failWithCode("unsupported_format", generation);
    return false;
  }
  recordingStartedAt = performance.now();
  recordingGeneration = generation;
  lastTimerSecond = -1;
  longWarningShown = false;
  updateStatus({
    mode,
    state: "recording",
    duration_seconds: 0,
    camera_ready: true,
    microphone_ready: true,
    saved_confirmed: false,
    error_code: null,
  });
  armRecordingDeadlines(generation);
  timerFrameId = requestAnimationFrame(updateRecordingTimer);
  return true;
}

async function startDemoRecording(generation) {
  clearLocalPlayback();
  if (!(await ensureMediaReady("camera_unavailable", generation))) {
    return;
  }
  if (!isCurrentLifecycle(generation)) {
    return;
  }
  beginRecording("demo", null, generation);
}

async function abortDetachedWritable(writable) {
  if (typeof writable?.abort === "function") {
    await Promise.resolve(writable.abort()).catch(() => undefined);
  }
}

async function startLongRecording(generation) {
  let handlePromise;
  try {
    handlePromise = window.showSaveFilePicker({
      suggestedName: makeNeutralDownloadName(),
      types: [
        {
          description: "WebM video",
          accept: { "video/webm": [".webm"] },
        },
      ],
      excludeAcceptAllOption: true,
    });
  } catch {
    failWithCode("write_failed", generation);
    return;
  }

  let handle;
  try {
    handle = await handlePromise;
  } catch (error) {
    if (error?.name === "AbortError") {
      if (isCurrentLifecycle(generation)) {
        await ensureMediaReady("camera_unavailable", generation);
      }
      return;
    }
    failWithCode("write_failed", generation);
    return;
  }
  if (!isCurrentLifecycle(generation)) {
    return;
  }
  if (!(await ensureMediaReady("camera_unavailable", generation))) {
    return;
  }
  if (!isCurrentLifecycle(generation)) {
    return;
  }

  let writable;
  try {
    writable = await handle.createWritable();
  } catch {
    failWithCode("write_failed", generation);
    return;
  }
  if (!isCurrentLifecycle(generation)) {
    await abortDetachedWritable(writable);
    return;
  }
  let chunkWriter;
  try {
    chunkWriter = new SerialChunkWriter(writable);
  } catch {
    await abortDetachedWritable(writable);
    failWithCode("write_failed", generation);
    return;
  }
  if (!isCurrentLifecycle(generation)) {
    await chunkWriter.abort().catch(() => undefined);
    return;
  }
  beginRecording("long", chunkWriter, generation);
}

async function replaceMediaStream(unavailableCode, generation) {
  await releaseMediaStream();
  if (!isCurrentLifecycle(generation)) {
    return;
  }
  updateStatus(
    {
      state: "idle",
      camera_ready: false,
      microphone_ready: false,
      error_code: null,
    },
    "Preparing recording devices.",
  );
  await ensureMediaReady(unavailableCode, generation);
}

async function resetRecorder(mode = status.mode) {
  const generation = invalidateLifecycle();
  await cleanupLocalResources();
  if (!isCurrentLifecycle(generation)) {
    return;
  }
  status = createStatus({ mode });
  renderControls();
  publishStatus();
}

function configurationIdentity(args) {
  const mode = args?.initial_mode === "long" ? "long" : "demo";
  const lifecycle =
    typeof args?.lifecycle_key === "string"
      ? args.lifecycle_key
      : typeof args?.component_key === "string"
        ? args.component_key
        : "component";
  return `${lifecycle}\u0000${mode}`;
}

async function applyStreamlitRender(args) {
  const nextConfigurationKey = configurationIdentity(args);
  const mode = args?.initial_mode === "long" ? "long" : "demo";
  if (!componentHasRendered) {
    componentHasRendered = true;
    configurationKey = nextConfigurationKey;
    status = createStatus({ mode });
    renderControls();
    publishStatus();
    return;
  }

  // Status updates cause Streamlit rerenders. Reused configuration must not touch media.
  if (nextConfigurationKey === configurationKey) {
    reportFrameHeight();
    return;
  }
  configurationKey = nextConfigurationKey;
  await resetRecorder(mode);
}

elements.recordButton.addEventListener("click", () => {
  if (
    !componentHasRendered ||
    startPending ||
    cleaningUp ||
    cleanupPromise !== null
  ) {
    return;
  }
  const generation = lifecycleGeneration;
  startPending = true;
  renderControls("Preparing the local recording.");
  const operation =
    status.mode === "long"
      ? startLongRecording(generation)
      : startDemoRecording(generation);
  void operation
    .catch(() => failWithCode("device_lost", generation))
    .finally(() => {
      if (isCurrentLifecycle(generation)) {
        startPending = false;
        renderControls();
      }
    });
});

elements.stopButton.addEventListener("click", requestRecorderStop);

elements.rerecordButton.addEventListener("click", () => {
  if (cleaningUp || cleanupPromise !== null) {
    return;
  }
  const operation = resetRecorder();
  const generation = lifecycleGeneration;
  void operation.catch(() => failWithCode("device_lost", generation));
});

elements.skipButton.addEventListener("click", () => {
  if (cleaningUp || cleanupPromise !== null) {
    return;
  }
  const generation = invalidateLifecycle();
  void cleanupLocalResources()
    .then(() => {
      if (!isCurrentLifecycle(generation)) {
        return;
      }
      updateStatus({
        state: "skipped",
        camera_ready: false,
        microphone_ready: false,
        saved_confirmed: false,
        error_code: null,
      });
    })
    .catch(() => failWithCode("device_lost", generation));
});

elements.saveConfirmation.addEventListener("change", () => {
  if (!elements.saveConfirmation.checked || !localCompletionReady) {
    return;
  }
  updateStatus({ state: "saved", saved_confirmed: true, error_code: null });
});

for (const input of elements.modeInputs) {
  input.addEventListener("change", () => {
    if (
      cleaningUp ||
      cleanupPromise !== null ||
      (status.state !== "idle" && status.state !== "ready")
    ) {
      renderControls();
      return;
    }
    updateStatus({ mode: selectedMode(), error_code: null });
  });
}

elements.cameraSelect.addEventListener("change", () => {
  if (cleaningUp || cleanupPromise !== null) {
    return;
  }
  const generation = lifecycleGeneration;
  void replaceMediaStream("camera_unavailable", generation).catch(() =>
    failWithCode("camera_unavailable", generation),
  );
});

elements.microphoneSelect.addEventListener("change", () => {
  if (cleaningUp || cleanupPromise !== null) {
    return;
  }
  const generation = lifecycleGeneration;
  void replaceMediaStream("microphone_unavailable", generation).catch(() =>
    failWithCode("microphone_unavailable", generation),
  );
});

window.addEventListener("message", (event) => {
  if (event.source !== window.parent || event.data?.type !== "streamlit:render") {
    return;
  }
  const operation = applyStreamlitRender(event.data.args ?? {});
  const generation = lifecycleGeneration;
  void operation.catch(() =>
    failWithCode("device_lost", generation),
  );
});

function reconcileActiveRecording() {
  if (recordingGeneration !== null) {
    reconcileRecordingDeadlines(recordingGeneration);
  }
}

document.addEventListener("visibilitychange", reconcileActiveRecording);
window.addEventListener("focus", reconcileActiveRecording);

function cleanupForPageExit() {
  invalidateLifecycle();
  void cleanupLocalResources().catch(() => undefined);
  resizeObserver?.disconnect();
}

window.addEventListener("pagehide", cleanupForPageExit);
window.addEventListener("beforeunload", cleanupForPageExit);

if (typeof window.ResizeObserver === "function") {
  resizeObserver = new window.ResizeObserver(reportFrameHeight);
  resizeObserver.observe(document.body);
}

renderControls();
sendStreamlitMessage("streamlit:componentReady", { apiVersion: 1 });
