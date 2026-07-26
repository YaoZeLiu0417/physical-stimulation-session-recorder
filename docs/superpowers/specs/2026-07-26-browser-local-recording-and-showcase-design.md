# Browser-Local Recording And Showcase Design

## Status

Approved in conversation on 2026-07-26. This design supersedes the Twilio TURN
camera path described in
`2026-07-26-twilio-turn-camera-reliability-design.md` after the user declined
services that require telephone verification.

## Goal

Replace the deployed WebRTC relay preview with a Chrome-native audio/video
recorder that works without Twilio, TURN, a third-party account, or server-side
media handling. Preserve the complete private questionnaire workflow and the
approved quiet, Alto Neuroscience-inspired visual direction. Upgrade the
separate public README-only showcase into a polished, privacy-safe product
walkthrough with animated media and a complete tutorial.

## Confirmed Product Boundaries

- Desktop Chrome is the supported browser.
- Camera and microphone are both required for recording.
- The user manually saves the recording to their own computer.
- Media bytes never pass through Streamlit, project storage, an upload API, or
  an external relay.
- Both a short teacher demonstration and a 20-30 minute operational recording
  must be supported.
- The private operational application retains its full questionnaires,
  conditional follow-ups, and formal visit logic.
- Participants never see item scores, total scores, thresholds, or
  interpretations.
- The teacher showcase uses only neutral synthetic questions and never exposes
  real study content.
- No page, screenshot, animation, README, filename, or visible copy uses an
  unpublished study name or the prior intervention abbreviation.

## Selected Architecture

Build one browser-local recording component using Chrome's standard
`getUserMedia`, `MediaRecorder`, and File System Access APIs. The component is
the only code allowed to handle media streams or media bytes.

```text
Camera + microphone
        |
        v
Chrome MediaRecorder
        |
        +--> short mode: browser chunks --> Blob --> local download
        |
        +--> long mode: browser chunks --> local writable file stream

Streamlit receives status metadata only; it never receives media bytes.
```

The Streamlit/Python boundary may receive only a small typed status object:

- recording mode;
- lifecycle status (`idle`, `ready`, `recording`, `stopped`, `saved`,
  `skipped`, or `failed`);
- elapsed duration in seconds;
- whether camera and microphone tracks were acquired;
- whether the user confirmed local save completion;
- a sanitized error category.

The boundary must never receive a Blob, ArrayBuffer, media chunk, object URL,
local file handle, file path, real filename, device label, participant
identifier, ICE configuration, or credential.

## Chrome Capability Gate

Implementation begins with a minimal deployed capability test on the same
private Streamlit Community Cloud application. It must prove all of the
following in desktop Chrome before the existing path is removed:

1. the component iframe can request camera and microphone permission;
2. a live, nonblank muted preview renders at a stable 16:9 size;
3. `MediaRecorder` produces video plus an Opus audio track;
4. `showSaveFilePicker` can be invoked directly from a user gesture;
5. a writable file stream accepts ordered recording chunks and closes cleanly.

If the deployed component cannot use the file picker, long recording moves to
a dedicated same-origin recorder page opened by a user command. It retains the
same local-only status protocol. The fallback must not reintroduce server-side
recording, a TURN provider, media upload, or a shared public recorder service.

## Recording Modes

### Demonstration Mode

- Intended for a teacher walkthrough and limited to five minutes.
- Holds encoded chunks in browser memory.
- On stop, assembles one local Blob, shows an in-browser playback control, and
  enables an explicit download command.
- Supports discard and re-record before the user confirms the download.
- Revokes old object URLs whenever a recording is discarded or replaced.

### Long Recording Mode

- Intended for 20-30 minute operational sessions and capped at 45 minutes.
- Requires the user to choose a local destination before recording starts.
- Uses a one-second MediaRecorder timeslice and a serialized write queue so
  chunks cannot be reordered or written concurrently.
- Warns at 30 minutes and stops automatically at 45 minutes.
- On stop, waits for the final `dataavailable` event, drains queued writes,
  closes the local stream, then reports `saved`.
- A cancelled picker never starts media recording.
- A write or close failure immediately stops all media tracks and reports a
  sanitized failure without claiming success.

Both modes default to a neutral timestamp filename such as
`session-20260726-193000.webm`. The default contains no participant or study
identifier. The user may choose a different local name in Chrome.

## Media Configuration

- Request one video and one audio track.
- Prefer a 1280x720, 30 fps camera stream while allowing Chrome to negotiate a
  compatible device mode.
- Record audio with echo cancellation, noise suppression, and automatic gain
  control enabled where the selected device supports them.
- Keep live preview muted to prevent acoustic feedback while retaining audio in
  the recording.
- Select MIME types in this order when supported:
  `video/webm;codecs=vp9,opus`, `video/webm;codecs=vp8,opus`, then
  `video/webm`.
- If Chrome supports none of these types, do not begin recording and show a
  neutral compatibility message.
- MP4 conversion, transcoding, and automatic compression are outside this
  iteration.

## Recorder Interaction Design

The recorder is a full-width, unframed tool surface inside the existing
centered workflow, not a decorative nested card. Stable responsive constraints
prevent layout movement:

- a 16:9 preview with a neutral empty state;
- a segmented control for demonstration versus long recording;
- camera and microphone selectors populated after permission is granted;
- a microphone input-level indicator that never stores samples;
- a fixed-width `00:00` timer;
- familiar record, stop, re-record, download, and device-refresh controls with
  accessible names and tooltips;
- an unmistakable active-recording state;
- a local-save confirmation gate before continuing.

Recording and mode/device changes are mutually exclusive. The user cannot
advance while recording. After a successful local save, the user explicitly
confirms that the file is present before continuing. A failed or skipped
recording may continue to the questionnaires, but the private record stores
only the sanitized status, never the file location or media content.

## Error And Cleanup Behavior

- Permission denial distinguishes camera, microphone, and both-device denial
  without exposing browser exception text.
- Missing or disconnected devices return the component to a non-recording
  state and stop every remaining track.
- Cancelling the local save picker is a neutral cancellation, not a failure.
- Disk write, quota, encoder, or stream-close failure stops media immediately
  and never displays a saved state.
- Refresh, component unmount, workflow restart, and page close perform a
  best-effort recorder stop, track stop, timer cleanup, audio-context cleanup,
  object-URL revocation, and writable-stream close or abort.
- An interrupted short recording is lost. An interrupted long recording may
  leave an incomplete local file; the UI and tutorial must state this plainly.
- No raw exception, path, device identifier, media metadata payload, or browser
  fingerprint is logged or rendered.

## Questionnaire And Workflow Integration

The recorder replaces only the camera/TURN stage. It must not delete, flatten,
rename, or reinterpret questionnaire fields.

The private operational flow remains:

1. secure access and participant identification;
2. daily context;
3. local recording;
4. daily dense questions, conditional details, and scheduled formal visits;
5. confirmation.

All required NSSI fields and raw responses remain recorded in the private
structured record according to the approved CRF protocol. Scoring and derived
metrics remain available only to authorized research/admin workflows. The
participant confirmation screen never echoes answers, scores, risk labels, or
interpretations.

The teacher showcase remains:

1. controlled access;
2. neutral overview;
3. browser-local recording demonstration;
4. neutral synthetic feedback;
5. privacy-safe confirmation.

No real questionnaire labels, scoring rules, study names, intervention
parameters, or participant data enter the showcase.

## Visual Direction

Retain the approved Alto Neuroscience-inspired palette and interaction style:

- deep navy `#000035` for primary text;
- violet `#2D2674` for secondary structure;
- pink `#DD1D86` for the principal command and active state;
- blue `#33B0E4` and peach `#FFBC7D` for restrained status accents;
- white and neutral gray for the page surface.

The application remains quiet, credible, and low in cognitive load. It uses a
step-based flow, compact headings, slider-based neutral ratings, stable control
dimensions, clear focus states, and no green-dominated palette, gradients,
decorative orbs, nested cards, marketing hero, or score visualization.

## Twilio Removal And Migration

Twilio remains in production until the deployed Chrome capability gate and
the replacement recorder tests pass. The migration then:

1. integrates the recorder into the neutral showcase;
2. integrates the same media boundary into the private operational flow while
   preserving all questionnaire behavior;
3. removes the WebRTC TURN resolver, server media renderer, Twilio dependency,
   dependency contract entry, and both Twilio Secret reads;
4. leaves any existing remote Secret values unused so the user can delete them
   manually after deployment verification;
5. releases through a private pull request and verifies the real Chrome flow;
6. preserves the prior merge commit as the rollback point.

There is no media or questionnaire data migration. No existing recording or
response file is automatically moved, renamed, uploaded, or deleted.

## Public README-Only Showcase

The separate public showcase repository is
`physical-stimulation-session-recorder-showcase`. It remains documentation
only and contains no private application source.

The README uses the same palette and a polished product-documentation
composition:

1. product-name first viewport with a sanitized full-flow animation;
2. three concise signals: Chrome-local recording, no media upload, and
   step-based questionnaires;
3. an eight-step walkthrough covering access, context, permission, mode
   selection, recording, local save, questionnaires, and confirmation;
4. a comparison of demonstration and long recording modes;
5. a Mermaid privacy/data-flow diagram;
6. a complete Chrome usage tutorial;
7. permissions, device, interrupted-file, and disk-write troubleshooting;
8. a design-system section explaining palette, step layout, sliders, and the
   no-score participant boundary;
9. an access notice that exposes neither a password nor private repository
   details.

Approved visual assets include:

- `assets/workflow-demo.gif` for the end-to-end synthetic flow;
- `assets/local-recording.gif` for record, stop, and local save controls;
- one sanitized static image per documented step;
- a static fallback image and descriptive alt text for each animation.

Animations use only synthetic content and a generated/test camera scene. They
must not contain a real face, real voice, password, credential, real
questionnaire, research name, participant identifier, local path, browser
account information, or notification content. Assets are cropped to the app,
optimized for GitHub loading, and visually checked at desktop and mobile README
widths.

The public repository allowlist is limited to `.gitignore`, `README.md`, and
the approved files below `assets/`. Source, tests, configs, study documents,
questionnaires, scoring logic, secrets, deployment metadata, and local paths
are prohibited.

## Test Strategy

Tests are written before production changes and cover four layers.

### Recorder Unit Contract

- lifecycle state transitions and forbidden transitions;
- MIME fallback ordering;
- five-, thirty-, and forty-five-minute timing behavior;
- sequential chunk writes and final write draining;
- permission, picker cancellation, device loss, write failure, and close
  failure;
- complete cleanup of tracks, timers, audio contexts, object URLs, and file
  handles;
- status payload allowlist and rejection of media/path/device fields;
- absence of `fetch`, XMLHttpRequest, WebSocket, beacon, WebRTC peer
  connections, recorder factories, and server media writes.

### Chrome Browser Contract

- fake camera frames produce a nonblank, correctly framed preview;
- fake microphone input creates an audio track and visible level response;
- demonstration recording produces a nonempty playable WebM download;
- long mode requests a destination only from a user gesture and writes ordered
  nonempty chunks through a controlled writable-file test double;
- stop, re-record, restart, and page close release camera and microphone;
- desktop and narrow viewport screenshots contain no overlap or clipped
  controls.

### Streamlit Workflow Contract

- recorder success, skip, and failure statuses integrate without media bytes;
- questionnaire field inventories, conditional branches, and raw answer
  persistence are unchanged;
- participant pages never show score or answer summaries;
- synthetic showcase confirmation remains exact and privacy-safe;
- restart clears recorder status and questionnaire/session-only controls;
- the Alto palette and green-free design gate remain intact.

### Release And Documentation Contract

- focused and full Python tests, component tests, compilation/build, and diff
  checks pass;
- source repository is private before and after merge;
- the deployed Chrome short and long flows pass with real devices;
- microphone is present in the downloaded media and live preview remains
  muted;
- no network request carries media during recording;
- the README repository matches its strict allowlist;
- GIFs and screenshots are nonblank, optimized, responsive, and free of
  prohibited content.

## Non-Goals

- Safari, Firefox, mobile browser, or in-app-browser recording support.
- Server-side recording, media upload, cloud synchronization, or remote media
  recovery.
- Automatic MP4 conversion or video editing.
- Background recording after Chrome or the page closes.
- Video/audio analysis, transcription, face processing, or AI inference.
- Displaying participant scores, interpretations, risk labels, or research
  details in the showcase or public README.
