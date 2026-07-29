# Stages 4-6 Visual Refinement Design

**Date:** 2026-07-29
**Status:** Approved in visual review

## Goal

Refine the participant-facing questionnaire, local response package, and
completion confirmation so stages 04-06 feel as considered as the completed
browser-local recorder. The three stages must align with the existing
README/Alto-inspired shell while preserving every questionnaire, export,
privacy, and session-state contract.

## Non-Goals

- Do not change questionnaire prompts, response options, field identifiers,
  required rules, branching, validation, scoring, support thresholds, draft
  behavior, or submission order.
- Do not change ZIP bytes, filenames, member order, JSON or Excel schemas,
  archive validation, download behavior, or the local-save confirmation gate.
- Do not change session clearing, authentication, recorder behavior, media
  handling, or the local-only privacy boundary.
- Do not add a second stage navigator, nested cards, remote assets, fonts,
  analytics, animation-heavy decoration, or a marketing-style completion page.

## Approved Direction

The approved direction is an **open participant canvas**. The persistent
desktop rail and mobile progress header already establish stage position, so
the main content does not repeat that structure inside a large enclosing
panel. Stages 04-06 instead share:

- a centered content width aligned with the existing stage heading;
- open mist workspace with white native controls;
- cyan structural rules, rose current/primary emphasis, violet secondary
  hierarchy, peach checkpoint notices, and navy text;
- compact metadata rows, thin dividers, and generous vertical spacing;
- one visually dominant command at a time;
- stable mobile stacking without horizontal scrolling.

The approved visual mockups are stored in the ignored brainstorming session
under `.superpowers/brainstorm/1591-1785287954/content/`.

## Stage 04: Stepwise Questionnaire

The current question is the main visual element. The stage keeps one active
question at a time and presents it in this order:

1. A metadata row shows `CURRENT PROMPT`, the escaped protocol context, and a
   tabular `current / total` counter.
2. A thin progress track represents the validated current step and total
   number of active questions. The track exposes native progress semantics.
3. The prompt uses a cyan left rule, a compact context label, and a larger navy
   question label with comfortable line height.
4. The native Streamlit answer control follows with consistent spacing,
   visible focus, a white surface, violet neutral borders, and rose selected
   state where the control permits it.
5. A thin divider separates the answer from navigation. Back remains a compact
   icon command with its existing tooltip and disabled behavior; Continue or
   Check and Submit remains the single rose primary command.

Boolean answers remain native radios, sliders retain their configured range
and endpoint labels, integer fields remain number inputs, multiselect fields
retain their options, and narrative fields remain text areas. Styling must not
simulate a selected answer or replace the native control with untrusted HTML.

Validation and save errors remain adjacent to the current question and cannot
be hidden by the visual treatment. Conditional questions continue to change
the validated total and progress indicator through the existing flow builder.

## Stage 05: Local Response Package

The local package surface follows the same open width and divider rhythm:

1. A peach checkpoint notice preserves the existing warning not to refresh or
   close the page before download is complete.
2. A cyan top rule introduces a `LOCAL EXPORT` summary with a ready status.
3. The escaped ZIP filename appears on its own line.
4. A three-part fact row states the format (`ZIP`), contents (`JSON + Excel`),
   and storage boundary (`local device only`). These facts describe the actual
   validated bundle and do not imply that the user opened its contents.
5. The download command is the sole rose primary action for this stage.
6. The existing local-save checkbox remains required. The finish command stays
   disabled until the checkbox is checked and remains visually secondary.

Export generation and retry errors use the same content width and an aligned
blocking/error surface. A retry never bypasses bundle validation or the
local-save confirmation.

## Stage 06: Completion Confirmation

The default full-width green Streamlit success alert is replaced with an
Alto-palette completion summary. It includes:

- a cyan circular completion mark;
- the exact visible outcome `本次会话已完成。`;
- a short statement that the participant confirmed local package storage and
  that the current session data has been cleared;
- three divided confirmation rows: the package was confirmed saved locally,
  questionnaire data was cleared from the current session, and no recording
  media was uploaded to the application server;
- a final statement that the page can now be closed.

The completion surface must not display participant identifiers, answers,
recording outcomes, filenames, or any state already cleared by
`_finish_current_session`. It also must not claim that a recording file exists
when the deliberate no-recording path was used.

## Architecture

### `operational_ui.py`

Own the shared CSS for the three open workflow surfaces and pure escaped markup
for package facts and completion confirmation. Markup helpers validate any
finite enumerated state before rendering and escape every dynamic string.

### `questionnaire_ui.py`

Own questionnaire-specific progress markup and the native-control layout. The
renderer may use a keyed, borderless Streamlit container to provide a stable
CSS scope, but it must not add a large visual panel or change widget keys,
callbacks, rerun boundaries, saved answers, or validation flow.

### `app.py`

Continue to own stage routing, export generation, local-save acknowledgement,
finish gating, and session clearing. It wires the stage 05 and 06 presentation
helpers around the existing controls without changing their arguments, bundle
bytes, or state keys.

## Responsive And Accessibility Contract

- At desktop widths, stage content stays centered and aligned below the shared
  heading while the left rail remains unchanged.
- Below the existing `840px` breakpoint, the rail is replaced by the current
  mobile header and every metadata/fact row stacks into one column.
- Answer controls and commands remain at least the existing touch height and
  wrap long Chinese or English labels without overlap.
- Native labels, keyboard behavior, disabled states, and validation messages
  remain available to assistive technologies.
- The questionnaire progress track exposes `role="progressbar"` with validated
  minimum, maximum, and current values.
- Focus remains cyan and visible against mist, white, violet, and rose.
- Font sizes do not scale with viewport width; letter spacing stays zero.
- No gradients, nested cards, decorative orbs, remote assets, or motion are
  introduced.

## Testing And Acceptance

### Pure Presentation Tests

- Prove question progress markup escapes hostile context and emits validated
  counter and progress semantics for first, middle, final, and empty flows.
- Prove package and completion markup escape dynamic filenames and expose only
  the approved local facts and completion statements.
- Lock the shared CSS selectors, palette tokens, open-canvas width, responsive
  stacking, focus treatment, and absence of a large enclosing panel.

### Streamlit Integration Tests

- Prove stage 04 still shows one active question, existing widget keys,
  validation, branching, draft persistence, back/next behavior, and support
  messages.
- Prove stage 05 still receives the exact ZIP bytes, filename, MIME type, local
  checkbox key, and disabled finish gate.
- Prove retry/error paths remain stage 05-only and do not expose questionnaire
  controls or completion content.
- Prove stage 06 contains the approved completion summary, exposes no download
  or questionnaire controls, and retains cleared sensitive state.

### Regression Verification

- Run the complete Python suite and Node recorder suite.
- Run `compileall` and `git diff --check`.
- Inspect stages 04-06 at desktop and mobile widths when browser automation is
  available, checking wrapping, focus, scroll, button visibility, and absence
  of content overlap.

## Acceptance Criteria

The work is complete when stages 04-06 visibly share the same open-canvas
system, the questionnaire question and answer control are the dominant stage
04 content, stage 05 presents a legible local file summary and unchanged
download gate, stage 06 uses the approved completion summary instead of the
default success alert, and all existing behavioral and privacy tests continue
to pass.
