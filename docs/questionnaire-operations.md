# Questionnaire Session Operations

This guide covers the current browser-local operational flow. It contains no
questionnaire wording or participant examples.

## Controlled Access

- Open the application only through the controlled access process approved by
  the operating team.
- A participant session starts from the signed access link issued for that
  session. Confirm the displayed session context before proceeding.
- An authorized operator may use the separate administrative entry when a
  participant link is not appropriate.
- Stop if the session context is unexpected. Do not continue in another
  participant's browser session.

## Pre-Session Check

1. Use a current Chrome release over HTTPS.
2. Confirm that Chrome can request camera and microphone access.
3. Confirm that the selected camera and microphone are the intended devices.
4. Confirm that the browser can save a small test file to a
   participant-selected local destination.
5. Confirm that the configured support contact is available to the operating
   team.

## Browser-Local Recording

- Chrome captures the camera and microphone locally.
- The recording is saved as WebM directly to the participant-selected local
  destination. The Streamlit application does not receive the media bytes.
- Keep the page open until Chrome reports that the local save has completed.
- A saved recording must be explicitly confirmed before the questionnaire can
  continue.
- When recording is skipped or fails, continuation requires the explicit
  on-screen confirmation. Record the operational incident outside the
  participant session without including participant content.

## Questionnaire And Local Export

- Raw questionnaire responses exist only in Streamlit session memory while the
  page remains open.
- Complete the questionnaire in the displayed order and use the on-screen
  support contact whenever the support notice appears.
- At completion, download the local ZIP. It contains JSON and Excel copies of
  the same raw response snapshot.
- Open the ZIP locally and confirm that both files are present before selecting
  the local-save confirmation.
- The local-save confirmation enables the final action. Finish clears the
  application-owned session state from Streamlit session memory.
- The application does not upload recording or questionnaire data.
- The application does not store participant data on the server.

## Data-Loss Boundary

- Refreshing or closing the page before the local ZIP is saved discards the
  in-memory questionnaire state. It cannot be recovered by the application.
- Closing Chrome before the WebM writer finishes may leave an incomplete local
  recording. Verify the saved file before continuing.
- Selecting Finish intentionally clears the active session. A completed local
  export cannot be reopened inside the application.

## Deployment Checks

Before opening the service for use:

1. Verify HTTPS from the same Chrome environment used for sessions.
2. Verify the camera and microphone permission prompt and device selection.
3. Save and play a short local WebM using non-participant test material.
4. Complete a synthetic questionnaire flow and download the local ZIP.
5. Confirm that the ZIP contains matching JSON and Excel response data.
6. Confirm that browser network activity contains no recording or
   questionnaire transfer.
7. Confirm that the support contact text is visible when the support notice is
   triggered with synthetic data.
8. Refresh a synthetic unfinished session and confirm the documented data-loss
   behavior.

## Retry And Troubleshooting

- Camera or microphone unavailable: check Chrome site permissions, reconnect
  the device, and retry before collecting responses.
- Local file selection canceled: start the recording step again and select a
  destination when prompted.
- Recording failure: retry after confirming both devices, or use the explicit
  continue-without-recording confirmation when the operating procedure permits
  it.
- ZIP generation failure: keep the page open and retry. Do not refresh while
  the in-memory responses are still needed.
- Local file cannot be opened: repeat the local export while the session is
  still active, then verify both files before Finish.
- Page refreshed or closed: begin a newly authorized session. The prior
  in-memory responses cannot be recovered.
