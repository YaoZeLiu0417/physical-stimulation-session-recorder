# Local Questionnaire Export And Showcase Design

## Status

Approved in conversation on 2026-07-27. This design replaces the server-record
and JSON-upload portions of the earlier browser-local recorder operational
integration plan. The verified browser-local video recorder remains unchanged.

## Goal

Complete the private at-home participant workflow by adding the full approved
questionnaires and a participant-operated local data export. Questionnaire
results are downloaded to the participant's computer as one ZIP containing
JSON and Excel files. The application does not persist questionnaire answers
to server disk and does not upload questionnaire or media files.

Also complete the privacy-safe teacher showcase and the separate Fancy README
using synthetic content only.

## Confirmed Usage Model

- Participants complete the intervention at home.
- Participants operate their own camera and microphone.
- Participants save the audio/video recording to their own computer using the
  already verified Chrome-local recorder.
- Participants complete the private questionnaire flow themselves.
- Participants download their own questionnaire export before ending the
  session.
- A later file-submission process will be defined separately and is outside
  this iteration.
- Researchers do not remotely record the participant's screen or camera.

## Storage And Network Boundary

The existing Streamlit questionnaires necessarily send widget values to the
Streamlit process and hold them in the current server session memory. This
transient processing is allowed. Persistent server storage is not.

The operational application must not:

- write questionnaire answers, derived metrics, recordings, or export files to
  server disk;
- create or update a server-side participant record store;
- upload questionnaire JSON, Excel, ZIP, video, or audio files;
- call Baidu storage, another cloud storage service, or a media relay;
- retain an export after the participant confirms local save and ends the
  session.

The application may build JSON, Excel, and ZIP bytes in memory long enough to
serve the participant's browser download. Existing historical files are left
untouched; this migration must not move, rewrite, or delete them.

## Operational Workflow

The private participant flow is:

1. Verify the signed participant link and lock the pseudonymous participant ID.
2. Confirm daily context and intervention-day information.
3. Record audio/video in Chrome and save it locally.
4. Complete all applicable daily dense questions, conditional details, and
   scheduled formal visits.
5. Validate every required answer and conditional branch.
6. Build one questionnaire export ZIP in memory.
7. Download the ZIP to the participant's computer.
8. Explicitly confirm that the questionnaire ZIP is present locally.
9. Show a privacy-safe completion confirmation and clear questionnaire/export
   session state.

One signed participant link represents one visit. The generated ZIP contains
only that current visit; every configured visit type remains supported, but
separate historical sessions are not aggregated into one archive.

The existing explicit continue-without-recording path remains eligible for the
questionnaire and local export. In that case, the export contains only the
sanitized `skipped` or `failed` recording outcome.

All completion and export timestamps are timezone-aware UTC values serialized
to second precision. Finishing clears sensitive questionnaire, recorder, and
export state while preserving the authenticated link lock and one
non-sensitive completion marker.

Closing or refreshing the page before download loses the current questionnaire
session. The page must state this before questionnaire entry and again before
final download.

## Questionnaire Equivalence

The migration must preserve the complete private CRF behavior:

- every NSSI field currently recorded;
- daily dense items and raw slider/rating responses;
- conditional questions and their visibility rules;
- required and answered-field tracking;
- intervention-day and scheduled-visit rules;
- formal instrument item inventories and response options;
- support-needed and safety-response behavior;
- raw answers needed for later offline scoring;
- revision-independent field IDs and machine-readable structure.

Questionnaire specifications, item wording, option sets, branch predicates,
and scoring inputs must not be renamed, flattened, deleted, or reinterpreted.
Automated inventory tests must compare the migrated application with the
pre-migration base commit.

## Participant Privacy Boundary

The participant-facing page and downloaded files include raw responses because
the participant entered them, but they must not include:

- calculated item scores or total scores;
- score interpretations;
- risk labels or risk thresholds;
- admin-only derived metrics;
- hidden safety classifications;
- server paths, remote paths, device labels, or media filenames;
- a study name or intervention abbreviation in the export filename.

The existing scoring code may remain available for authorized offline or
future research workflows, but the operational participant export does not
execute or serialize those derived results. Raw slider values remain included
as questionnaire answers; they are not presented as interpreted scores.

## Export Package

The participant receives one neutral timestamp ZIP, for example:

```text
session-20260727-103000.zip
```

The filename contains no participant identifier, study name, visit label, or
intervention abbreviation. The ZIP contains exactly:

```text
responses.json
responses.xlsx
```

Both files are generated from one immutable in-memory export snapshot so they
cannot disagree.

### JSON

`responses.json` is the canonical machine-readable export. It contains:

- export schema version;
- pseudonymous participant ID inside the file, not in its filename;
- record date, intervention day, visit inventory, and daily context;
- sanitized browser-local recording completion metadata with no location;
- raw answers grouped by visit/instrument;
- answered-field inventories and conditional-branch outcomes;
- completion timestamps and application schema metadata.

It excludes derived score and upload/storage fields.

### Excel

`responses.xlsx` is the human-readable representation of the same snapshot.
It contains stable sheets for:

- `Session`: pseudonymous session and visit context;
- `Responses`: one row per raw questionnaire response;
- `Visits`: completion state for each applicable visit/instrument;
- `Recording`: sanitized local-save status only.

Rows use stable item IDs, item text, raw values, display values where defined,
answered status, visit, and instrument identifiers. No score, interpretation,
risk, upload, path, or media-location sheet is included.

Excel bytes are generated in memory through one explicit production
dependency. ZIP assembly uses the Python standard library and never creates a
temporary file.

## Download And Cleanup Interaction

- The download command is available only after all required questionnaire
  branches are complete and recording continuation is satisfied.
- A single download command returns the ZIP containing both formats.
- The download command does not display the export mapping or answer summary.
- After the download command, the participant must check a local-save
  confirmation and choose an explicit finish command.
- Finish clears questionnaire widget state, the in-memory record, export bytes,
  recorder status, and local-save acknowledgements.
- The application cannot prove that Chrome completed a disk write, so it must
  describe the checkbox as participant confirmation rather than automatic
  verification.
- Export-generation failure keeps the answers in the current session, reports
  a neutral retry message, and does not claim completion.

The ZIP is not application-encrypted in this iteration. The interface must
state that it contains private questionnaire responses and should be stored in
the participant's approved local location. Encryption and later submission are
separate workflow decisions.

## Runtime Simplification

The operational application no longer needs active server media or record
upload behavior. The migration removes active runtime use of:

- `DailyRecordStore` and server recording directories;
- WebRTC recorder factories, FLV/MP4 conversion, and server playback;
- Baidu OAuth and multipart upload functions;
- JSON/video bundle upload and cleanup controls;
- server-side history, retry, cleanup, and upload operations that depend on
  persisted participant records;
- `streamlit-webrtc`, `aiortc`, `av`, and remote-upload-only dependencies.

Authentication, signed participant links, questionnaire specifications,
support behavior, and the verified browser recorder remain. Legacy storage
modules and historical data may remain as inactive archival code when removing
them would risk unrelated data, but `app.py` must not import or call them.

## Teacher Showcase

The private teacher showcase remains a synthetic demonstration. Its flow is:

1. controlled access;
2. neutral overview;
3. browser-local recording and local save;
4. synthetic slider-based questionnaire feedback;
5. synthetic JSON-plus-Excel ZIP download;
6. privacy-safe confirmation.

The showcase must never display or export real questionnaire wording, NSSI
content, formal instrument names, scoring rules, risk thresholds, study names,
intervention parameters, participant identifiers, or the prior intervention
abbreviation. The synthetic export is structurally representative but contains
only invented fields and values.

## Visual Direction

The operational questionnaire, teacher showcase, and README retain the approved
quiet Alto Neuroscience-inspired direction without claiming affiliation:

- deep navy `#000035` for primary text;
- violet `#2D2674` for secondary structure;
- pink `#DD1D86` for primary and active commands;
- blue `#33B0E4` and peach `#FFBC7D` for restrained status accents;
- white and neutral gray surfaces;
- stable 16:9 recorder layout;
- compact step headings and slider controls;
- no green-dominated palette, gradients, decorative orbs, nested cards, or
  score visualizations.

## Fancy README

The separate public README-only showcase uses the product name `Physical
Stimulation Session Recorder` and contains no private source or study content.
It includes:

- a sanitized end-to-end workflow animation and static fallback;
- illustrated steps for access, recording, questionnaire completion, and local
  ZIP download;
- demonstration and long-recording mode guidance;
- a Mermaid data-flow diagram showing local video and questionnaire export;
- Chrome permissions, recording, download, and troubleshooting instructions;
- the palette and low-cognitive-load design rationale;
- a controlled-demo link without a password;
- clear statements that participant scores are not displayed and the public
  materials contain no real study questions.

All screenshots and animations use a generated camera test scene, synthetic
audio, and invented responses. They must not show a real person, real voice,
password, account, notification, local path, participant ID, score, or private
questionnaire text.

## Error Handling

- Recorder permission, device, write, and local-save errors retain the existing
  sanitized behavior.
- Incomplete questionnaires remain on the current step with field-level
  guidance and no export.
- Export serialization or Excel-generation failures keep the current session
  intact and allow retry.
- Download cancellation is neutral and requires no destructive cleanup.
- Finish is impossible until the participant explicitly confirms local save.
- Refresh, browser close, timeout, or Streamlit session loss may discard
  unsaved answers; the interface warns about this limitation and does not claim
  recovery.
- No raw exception, response payload, questionnaire answer, score, credential,
  path, or filename is logged.

## Test Strategy

### Questionnaire Equivalence

- snapshot field IDs, item text, response options, visit schedules, branch
  predicates, required fields, scoring inputs, and safety triggers against the
  pre-migration base;
- exercise daily negative and conditional-positive branches;
- exercise every scheduled formal visit;
- prove participant pages never expose derived scores or answer summaries.

### Storage And Privacy

- prove the operational app does not instantiate a record store or create a
  recordings directory;
- prove production source has no media upload, questionnaire upload, Baidu,
  WebRTC, transcode, temporary-file, or server-path capability;
- prove no questionnaire or export file is written during end-to-end tests;
- prove session finish removes all sensitive session keys.

### Export

- validate the exact ZIP allowlist and neutral filename;
- parse JSON and Excel independently and compare both with the canonical
  snapshot;
- prove raw responses and branch status are preserved;
- prove derived metrics, scores, risk labels, paths, upload states, and media
  locations are absent;
- prove export failure is retryable and does not destroy answers;
- prove local-save confirmation gates final cleanup.

### Showcase And README

- run synthetic showcase workflow and export tests;
- scan visible text and assets for prohibited research terms and credentials;
- verify desktop/mobile rendering, GIF frames, links, and README allowlist;
- verify no public asset contains real questionnaire or participant content.

## Delivery Order

1. Update the implementation plan around session-only questionnaire state and
   local export.
2. Integrate the verified local recorder into the operational app.
3. Preserve and prove the complete questionnaire workflow.
4. Implement participant-safe in-memory JSON/Excel ZIP export and cleanup.
5. Remove active server persistence, uploads, and media dependencies.
6. Extend the synthetic teacher showcase with local export.
7. Build and verify the sanitized Fancy README.
8. Release through private review and run a real at-home-style Chrome session.

## Non-Goals

- Automatic questionnaire, video, or ZIP submission.
- Server-side draft recovery or participant history.
- Cloud storage, synchronization, or background upload.
- Application-level ZIP encryption or key management.
- Showing participants calculated scores, thresholds, labels, or
  interpretations.
- Changing questionnaire wording, branching, visit schedules, scoring inputs,
  or safety triggers.
- Defining the later research-team file-submission process.
