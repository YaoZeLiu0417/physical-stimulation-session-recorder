# Host Recording Confirmation Design

**Date:** 2026-07-28

## Problem

The browser recorder can finish and expose a local WebM download while the
participant remains blocked before the formal questionnaire. The final save
confirmation currently lives inside the custom-component iframe. That makes a
critical workflow transition depend on an embedded control that can be missed,
clipped, or retained from an older browser component session.

Clicking a browser download link cannot prove that the file was written to
disk, so download alone must not unlock the questionnaire.

## Approved Behavior

When the recorder reports a valid `stopped` result, the main Streamlit page
shows a prominent primary action:

> I have downloaded and checked the recording. Continue to the questionnaire.

The surrounding copy states that the participant should first open the local
file and check both video and sound. Activating the action is the participant's
explicit local-save confirmation. The page stores versioned browser-local
recording metadata, reruns, removes the recorder, and renders `③ 正式问卷`.

The existing component confirmation remains compatible. Either explicit
confirmation path produces the same validated `saved` status. Merely stopping
or downloading does not advance the workflow. Failed and skipped recordings
continue to use their separate explicit-continue confirmation.

## Architecture

`local_recording_workflow.py` owns a small pure transition that accepts only a
valid stopped `RecorderStatus` and returns the corresponding saved-and-confirmed
status while preserving mode, duration, and released-device flags.

`app.py` renders the host confirmation only for the stopped state. On click it
uses the pure transition, stores the existing version-2 metadata shape, and
reruns. The next render takes the locked recording branch and enters the
questionnaire without mounting the recorder again.

The recorder remains browser-local. No video bytes, file paths, filenames,
scores, questionnaire answers, or participant identifiers are added to the
transition.

## Error Handling

The transition fails closed for idle, ready, recording, saved, skipped, and
failed states. The host action is not rendered for those states. Existing
recording failure and skip handling is unchanged.

## Verification

Tests must prove that:

1. A stopped status becomes saved and confirmed with approved fields preserved.
2. Any non-stopped status is rejected by the pure transition.
3. A stopped recording renders the host confirmation while the questionnaire
   remains blocked.
4. Clicking the host confirmation persists exact version-2 metadata, removes
   the recorder on rerun, and renders the formal questionnaire.
5. The full Python and recorder JavaScript suites remain green.

