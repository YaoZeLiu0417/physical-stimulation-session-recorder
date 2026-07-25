# Privacy-Safe Functional Showcase Design

## Context

The deployed `showcase_app.py` currently demonstrates navigation only. Its
capture step explicitly avoids camera access, and its feedback step contains
only two synthetic sliders. This matches the original static privacy showcase,
but it does not let invited teachers experience the interaction pattern of the
real recorder.

The full `app.py` already contains camera recording, private instruments,
participant workflows, file persistence, and uploads. Deploying that entry
point would expose unreleased study content and operational capabilities, so it
is not suitable for the controlled teacher demonstration.

## Goal

Provide a complete, password-protected teacher demonstration with real browser
camera permission, live video preview, neutral questionnaire interaction, and
completion/restart while keeping research content, participant data, scoring,
recording persistence, and upload capabilities private.

## Selected Approach

Keep `showcase_app.py` as the deployment entry point and extend only the private
synthetic showcase. This preserves the neutral Alto-inspired visual language
and existing four-step navigation while adding functional media and feedback
interactions.

Two alternatives were rejected:

- Deploying `app.py` would provide every production feature but would reveal
  unreleased instruments, study-specific logic, participant operations, local
  persistence, and upload behavior.
- Using `st.camera_input` would request camera access but only capture a still
  image, so it would not demonstrate the recorder's live session experience.

## Experience Flow

### 1. Controlled Access

Retain the existing SHA-256 password gate. Missing configuration fails closed,
wrong passwords remain rejected, and successful access opens the neutral
overview. No credentials are stored in source or rendered after login.

### 2. Live Camera Demonstration

Replace the simulated progress panel with a real `streamlit-webrtc` live camera
preview. The browser requests video permission; audio is disabled. The
component uses `WebRtcMode.SENDRECV` and the existing public STUN pattern so it
works on Community Cloud.

The showcase must not provide a recorder factory, frame callback, media
processor, file path, download, transcoding, upload, or external storage call.
Media exists only for the active WebRTC connection and is discarded when the
component unmounts. UI copy must say that media is not written to a file or
retained in project storage; it must not falsely claim that live WebRTC uses no
network connection.

The normal path lets the teacher start the camera and continue after observing
the preview. Camera denial or device absence must not trap the demonstration:
the user can continue to the synthetic feedback step without exposing a
technical traceback.

### 3. Neutral Synthetic Questionnaire

Show four slider questions covering only the demonstration experience:

- process clarity;
- camera interaction smoothness;
- interface information load;
- willingness to continue using the demonstrated workflow.

The questions are not clinical instruments and do not reproduce study outcome
content. Slider responses remain only in `st.session_state` for the current
browser session. The page does not compute or display a total, interpretation,
risk flag, instrument name, or scoring rule.

### 4. Completion And Restart

Show a neutral completion status and the existing privacy boundary. Do not echo
individual answers. Restart clears all synthetic slider values and camera-step
state, then returns to the overview. Leaving the camera step unmounts the WebRTC
component and ends the live connection.

## Components And Boundaries

Create `showcase_media.py` as the only media boundary. It owns the
`streamlit-webrtc` imports, the STUN configuration, the no-audio constraints,
and the live-preview renderer. It must not import `av`, `aiortc`, questionnaire,
upload, file, or persistence modules.

`showcase_app.py` remains responsible for page layout, authentication, step
navigation, synthetic controls, and session-state cleanup. It calls the media
boundary only on the capture step and does not gain any recording, file, or
network-client APIs.

`showcase_workflow.py` remains unchanged because the approved transition table
already models the required four-step flow.

## Error Handling

- Missing password digest: stop before any camera or questionnaire UI renders.
- Wrong password: remain on the access page.
- Camera permission denied, no device, or component initialization failure:
  show neutral unavailable copy and keep the continue action available.
- Invalid step transitions: continue using the existing fail-closed
  `DemoTransitionError` behavior.
- No failure path may reveal local paths, dependency details, credentials,
  participant identifiers, study names, or questionnaire content.

## Verification

Use TDD and keep the existing privacy tests as hard constraints.

1. Add focused tests for the media boundary: video enabled, audio disabled,
   SENDRECV mode, STUN configuration, stable component key, and absence of
   recorder/callback/file/upload arguments.
2. Update `AppTest` coverage so the four-step flow includes the live-camera
   boundary and all four neutral sliders, then proves restart clears their
   session state.
3. Update the source privacy test to allow only the isolated WebRTC boundary
   while continuing to reject private questionnaire imports, recording,
   persistence, downloads, uploads, external storage, and study terms.
4. Preserve the exact approved color palette, centered responsive layout,
   password behavior, and no-score confirmation page.
5. Run focused showcase tests, the complete private suite, Python compilation,
   dependency contract, and Git patch checks.
6. Release only through a private PR after confirming repository visibility.
7. Verify Community Cloud health, password rejection/acceptance, real camera
   permission and preview, four sliders, completion, restart, and anonymous
   GitHub source denial.

## Operational Retry Policy

An HTTP `429` from the coding-agent service is an execution-capacity event, not
an application feature. During implementation and review, wait 5-10 seconds and
retry the interrupted agent task automatically. Do not add artificial retry
code to the showcase, which makes no rate-limited application API calls.
