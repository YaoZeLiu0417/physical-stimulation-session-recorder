# Twilio TURN Camera Reliability Design

## Goal

Make the password-protected showcase display a reliable live camera preview on
Streamlit Community Cloud without enabling microphone capture, recording,
storage, upload, or research-specific content.

## Confirmed Failure

The browser requested camera permission and the user allowed it, but the page
remained at `waiting for camera connection`. In `streamlit-webrtc` 0.63.4,
`playing` becomes true only after the peer connection reaches `connected`, and
the SENDRECV video element is populated only after a remote track returns from
the server. The current deployment supplies only Google's public STUN server.
The library's version-matched deployment guidance states that Streamlit
Community Cloud can require TURN even when STUN is configured.

The white preview is therefore an ICE/NAT traversal failure, not evidence that
the browser skipped `getUserMedia`. The missing default video width is a
separate display defect that matters only after a remote track arrives.

## Selected Approach

Use Twilio Network Traversal Service through the credential helper already
provided by `streamlit-webrtc`. This is preferred over a public shared TURN
server, which is not reliable enough for a teacher demonstration, and over a
new client-only camera component, which would create a larger custom frontend
surface.

Add a focused `showcase_ice.py` module that resolves the runtime ICE server
list and reports whether it contains at least one `turn:` or `turns:` URL.
`showcase_media.py` remains the media boundary and receives the resolved RTC
configuration as an argument. It must continue to contain no recorder,
processor, frame callback, file, upload, or questionnaire capability.

## Credential And Media Flow

1. `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` are stored as root-level
   Streamlit Secrets. They are never committed or shown in page copy.
2. On the server, `streamlit-webrtc` uses the Twilio SDK to exchange the
   account credentials for short-lived ICE server credentials.
3. Only the short-lived ICE configuration is passed to the WebRTC browser
   component, as required by the WebRTC protocol.
4. The browser requests video only. Audio remains disabled.
5. The encrypted WebRTC stream may traverse Twilio TURN when a direct path is
   unavailable. No frame callback, recorder, file write, upload, or external
   storage integration is introduced.

## Failure Behavior

If both Twilio secrets are absent, only one is present, the SDK is unavailable,
or credential retrieval falls back to STUN-only, the showcase must fail closed:

- do not render a START control that can lead to an unexplained white preview;
- show a neutral message that live preview is temporarily unavailable;
- keep the `continue` action available so the rest of the synthetic flow works;
- do not render the camera-smoothness slider in the feedback step, and show it
  as not experienced instead;
- do not expose exception details, account identifiers, tokens, ICE usernames,
  or credentials in the page.

If TURN is available but the peer connection still does not reach `playing`,
the existing component error/waiting state remains visible and the feedback
step still skips the camera-smoothness item because
`showcase_camera_started` was never set.

## Successful Preview Behavior

When TURN is available, render the existing video-only SENDRECV component with:

- `media_stream_constraints={"video": True, "audio": False}`;
- `sendback_video=True` and `sendback_audio=False` explicitly;
- muted autoplay, inline playback, hidden controls, and `width: 100%`;
- the existing stable component key;
- no recorder or media-processing callback.

Once the peer connection reports `playing`, set the session-only
`showcase_camera_started` flag. The feedback step then displays all four
neutral synthetic sliders. Restart continues to remove the four response keys
and the camera flag.

## Dependency And Deployment

Add the official Twilio Python SDK with a bounded major version in
`requirements.txt`. Update the dependency contract test so deployment cannot
silently lose it.

After local tests and review, release through a private pull request. Before
merging, reconfirm that the source repository is private. After Streamlit
rebuilds, add the two Twilio values through the Streamlit secret-management UI,
not Git or chat. A signed-in browser must then verify permission, live video,
no microphone request, feedback behavior, confirmation privacy, and restart.

## Test Strategy

Tests must be written before production changes and must cover:

- Twilio TURN configuration is accepted and classified as TURN-capable;
- STUN-only, partial credentials, and resolver failures fail closed without
  leaking exception text;
- the media call receives explicit video return, disabled audio, and responsive
  video attributes;
- recorder, frame callback, processor, file, upload, and questionnaire
  capabilities remain absent from the media boundary;
- the camera slider appears only after a connected preview;
- the no-camera path remains completable and confirmation never echoes answers
  or scores;
- restart clears every session-only camera and response key;
- focused tests, dependency contract, the full regression suite, compilation,
  and Git diff checks pass before release.

## Non-Goals

- No microphone support.
- No video recording, persistence, upload, screenshots, or frame analysis.
- No public TURN credentials or hard-coded Twilio credentials.
- No questionnaire, scoring, participant, or study-specific changes.
- No public repository publication until the repaired teacher flow is verified.
