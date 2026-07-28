# README-Aligned Operational App Design

**Date:** 2026-07-29
**Status:** Approved in visual and interaction review

## Goal

Align the protected Streamlit application with the visual system already
presented in the repository README. The application must use the same quiet,
Alto-inspired research-workflow language across controlled access, daily
context, browser-local recording, stepwise questionnaires, local response
export, and completion confirmation.

The redesign is not a generic recoloring exercise. It makes the live
application and README describe the same six-stage product, with one visible
current task, an explicit stage boundary, and consistent local-first status
semantics.

## Non-Goals

- Do not change questionnaire wording, response options, branching, scoring,
  schedules, or support thresholds.
- Do not change browser-local media handling, recorder limits, or the no-upload
  boundary.
- Do not change the JSON and Excel export schema, ZIP format, filename rules,
  or transient-session storage model.
- Do not add analytics, remote assets, remote fonts, client-side state stores,
  or durable server-side session recovery.
- Do not claim affiliation with the visual-reference organization or use its
  name as the application brand.

## Approved Visual Direction

The approved direction is **Option A: faithful README shell**.

### Palette

| Role | Value | Use |
| --- | --- | --- |
| Deep navy | `#000035` | Application shell, desktop stage rail, primary text |
| Violet | `#2D2674` | Inactive stages, secondary hierarchy, structural accents |
| Rose | `#DD1D86` | Current stage and the single primary action |
| Cyan | `#33B0E4` | Completed stages, readiness, local-first status |
| Peach | `#FFBC7D` | Quiet checkpoints and non-error attention states |
| Mist | `#F4F5F7` | Main workspace background |
| White | `#FFFFFF` | Inputs and local working surfaces |

The existing questionnaire-only black and orange shell is replaced by these
README tokens. Typography uses the platform sans-serif stack, zero letter
spacing, compact headings, and stable line heights. The application brand is
`SESSION COMPANION`, with `GUIDED LOCAL-FIRST FLOW` as the small descriptor.

### Desktop Layout

Desktop view uses a persistent deep-navy left rail and a mist main workspace.
The rail presents all six bilingual stages with stable numbered circles:

1. Controlled access / 受控进入
2. Daily context / 当日状态
3. Browser-local recording / 本地音视频
4. Stepwise questionnaire / 分步结构化作答
5. Local response package / 本地资料包
6. Completion confirmation / 完成确认

Completed stages use cyan, the active stage uses a rose outline and marker,
and future stages remain violet. The main workspace shows one stage chip, one
bilingual heading, the current controls, and one visually dominant command.
Sections use spacing and dividers rather than nested cards.

### Mobile Layout

Below the responsive breakpoint, the rail becomes a deep-navy top header. The
header shows the product name, current stage label, `NN / 06`, and a six-part
progress strip. The content becomes a single column without horizontal
scrolling. Controls keep native Streamlit labels, focus, keyboard, and touch
behavior.

## Stage Interaction Model

The application renders one active stage at a time.

### Stage 01: Controlled Access

The existing signed-link and password rules remain authoritative. When access
is required, only the access shell, password input, and login result are
visible. A valid signed link skips the interactive password surface and marks
the stage complete.

### Stage 02: Daily Context

The existing daily-context fields remain unchanged. An explicit primary action,
`确认当日状态，进入本地录制`, records a session-local confirmation and advances
to recording. The confirmation does not persist data outside the current
Streamlit session and does not generate the export early.

The confirmation key is owned by the operational session. It is cleared when
the participant, date, intervention day, visit, authentication context, or
session record changes.

### Stage 03: Browser-Local Recording

Only the recorder and recording guidance are visible. The successful path
still requires local playback, download, and the existing host confirmation.
The skipped or failed path still requires the existing explicit no-save
confirmation. Both outcomes advance to the questionnaire without uploading
media.

### Stage 04: Stepwise Questionnaire

The existing one-question-at-a-time renderer, conditional flow, validation,
draft behavior, and support message remain unchanged. The renderer keeps its
question context and question counter but consumes the shared application
theme instead of injecting a separate global shell.

### Stage 05: Local Response Package

After questionnaire completion, the existing in-memory JSON and Excel ZIP is
generated and validated. The stage shows the download command, local-save
confirmation, and disabled/enabled completion command. It does not claim that
the ZIP contents were opened or inspected.

### Stage 06: Completion Confirmation

The completion surface confirms two conditions: a recording outcome was
confirmed, and the response ZIP was saved locally. It does not imply that a
recording file exists when the no-save recording path was used.

## Architecture

### `operational_ui.py`

A new presentation module owns:

- the palette and static CSS;
- the six bilingual stage definitions;
- global theme injection;
- the desktop rail and mobile progress header;
- the stage heading and contextual status markup;
- safe HTML escaping for every dynamic value passed into markup.

The module receives an already validated active-stage index. It does not read
or mutate questionnaire answers, recorder state, exports, authentication, or
session records.

### `app.py`

`app.py` remains the workflow owner. It:

- adds the daily-context confirmation to the existing owned session keys;
- derives the active stage only from validated authentication, context,
  recording, questionnaire, export, and completion state;
- renders a stage shell before the controls for that stage;
- uses existing `st.stop()` and rerun boundaries so later stages cannot appear
  before their gate is satisfied;
- clears the new confirmation through the existing session-clear paths.

The current top-level flow may be divided into small stage-rendering functions
inside `app.py` when that reduces duplication, but business rules stay in their
existing domain modules.

### `questionnaire_ui.py`

The questionnaire renderer retains native Streamlit controls and all domain
logic. Its global `ALTO_CSS` and branded top shell are removed or reduced to
question-local presentation so they cannot compete with the shared six-stage
application shell.

### Recorder Component

The browser recorder keeps its own fixed 16:9 surface and JavaScript lifecycle.
Only its surrounding Streamlit workspace and approved palette integration may
change. No recorder transport, save, cleanup, or device behavior changes are in
scope.

## State And Data Flow

The active stage follows this validated sequence:

1. Access not granted -> controlled access.
2. Access granted and context not confirmed -> daily context.
3. Context confirmed and recording gate not satisfied -> recording.
4. Recording gate satisfied and questionnaire incomplete -> questionnaire.
5. Questionnaire complete and session not finished -> local response package.
6. Local ZIP confirmed and finish action accepted -> completion.

An invalid cached export remains subject to the existing validation and retry
behavior. A refresh may discard transient state and restart the flow; the
visual shell must not imply recovery that the application cannot guarantee.

## Error And Status Semantics

- Cyan represents completed, ready, or safely local state.
- Peach represents a non-error checkpoint or reminder requiring attention.
- Rose represents the current stage, primary command, and true blocking error
  emphasis where Streamlit requires it.
- Neutral mist or white surfaces carry explanatory and privacy copy.

Existing invalid-link, password, recorder, questionnaire, export, and support
logic remains fail-closed. Styling cannot hide a required control, enable a
disabled gate, or derive progress from untrusted browser markup.

## Accessibility And Responsive Constraints

- Preserve native labels and keyboard interaction for all Streamlit controls.
- Provide visible focus states with sufficient contrast.
- Keep button text wrapping and stable control heights on narrow screens.
- Use no negative letter spacing and no viewport-scaled font sizes.
- Keep the recorder at a stable 16:9 ratio.
- Avoid nested cards and decorative gradients, orbs, and non-functional
  illustration.
- Respect reduced-motion preferences; only restrained state transitions may be
  animated.
- Escape participant identifiers, day values, questionnaire context, and all
  other dynamic markup values.

## Testing And Acceptance

### Automated Tests

- Unit-test six-stage definitions, active-stage resolution, escaping, and the
  daily-context confirmation reset behavior.
- Use Streamlit `AppTest` to prove that each stage exposes only its approved
  controls and cannot bypass access, context, recording, questionnaire, or ZIP
  confirmation gates.
- Add visual-contract tests for the exact README palette, stage labels,
  desktop rail, mobile progress header, primary-action styling, and status
  semantics.
- Reject remote fonts, remote images, scripts, and unescaped dynamic HTML in
  the shared application shell.
- Keep the full Python suite, recorder Node suite, compilation checks, export
  tests, and privacy audits green.

### Visual Verification

Render and inspect the real application at:

- `1440 x 900` desktop;
- `1024 x 768` compact desktop/tablet;
- `390 x 844` mobile.

For every reachable stage, verify no text clipping, control overlap, horizontal
scrolling, unstable recorder sizing, missing focus state, or stale duplicate
header. The acceptance target is not pixel identity with README bitmaps; it is
the same layout logic, palette, hierarchy, and six-stage semantics applied to
the real controls.

## Completion Criteria

The work is complete when the protected application presents the approved
README-aligned shell across all six stages, the new daily-context gate is
enforced, the domain and privacy behavior is unchanged, responsive visual
inspection passes at all target sizes, the full regression suite passes, and
the deployed Streamlit application is verified after publication.
