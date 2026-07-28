# Operational README and Visual Assets Design

**Date:** 2026-07-28

## Goal

Turn the operational repository homepage into a polished, teacher-facing product
brief for the complete intervention-session workflow. The README must lead with
the questionnaire journey and use a newly created Alto-inspired visual system,
not the public synthetic showcase assets.

## Non-Reuse Boundary

No file from `physical-stimulation-session-recorder-showcase/assets` may be
copied, embedded, hotlinked, modified, or used as a source frame. The operational
repository will own a new `assets/readme/` inventory generated specifically for
the current `app.py` workflow.

The README must contain no `raw.githubusercontent.com` image dependency and no
image link to the showcase repository. The showcase repository may remain as a
text link in the final reference section only.

## Visual Direction

The assets use the approved restrained neuroscience palette:

- deep navy `#000035` for primary text and dark surfaces;
- violet `#2D2674` for structural navigation;
- rose `#DD1D86` for current state and primary action;
- cyan `#33B0E4` for ready and information accents;
- peach `#FFBC7D` for completion accents;
- white and pale neutral gray for the working canvas.

The composition is quiet, precise, and low in cognitive load. It uses compact
headings, generous white space, stable 16:9 frames, simple progress rails, and
thin color accents. It does not claim affiliation with any external company.

## New Asset Inventory

Create these original files under `assets/readme/`:

1. `operational-workflow.gif` - a six-scene animated overview at 1440 x 810.
2. `operational-workflow-static.webp` - a static fallback matching the first
   frame of the GIF.
3. `questionnaire-experience.webp` - the stepwise response experience with a
   progress rail, one neutral example control, applicable-follow-up indicator,
   and an explicit no-score boundary.
4. `local-recording-save.webp` - camera/microphone readiness, local recording,
   playback, download, and the host-level continue action.
5. `local-response-export.webp` - JSON + Excel ZIP download, local confirmation,
   and completed-session state.
6. `operational-palette.webp` - the five approved color swatches.

All screenshots are original privacy-safe product compositions derived from the
operational flow and visible product copy. They are not captures or edits of the
showcase app. They contain no participant identifiers, actual questionnaire
items, real answers, recordings, scores, thresholds, credentials, or study
hypotheses.

## Animation Storyboard

The GIF uses six stable scenes with short cross-frame continuity:

1. Controlled access / 受控进入
2. Daily context / 当日状态
3. Browser-local recording / 本地音视频
4. Stepwise questionnaire / 分步结构化作答
5. Local response package / 本地资料包
6. Completion confirmation / 完成确认

Each scene keeps the same left progress rail and working canvas. Only the active
stage, concise stage content, and restrained accent color change. The animation
loops slowly enough to read and stays below 5 MiB.

## README Structure

The first viewport contains, in order:

1. `Physical Stimulation Intervention Session Companion` as the product signal;
2. a concise bilingual value statement;
3. one controlled-application link;
4. the new local `operational-workflow.gif`;
5. a compact six-stage session rail.

The body then presents:

- why the tool exists and what teachers can evaluate;
- the stepwise questionnaire experience before recorder details;
- local recording and explicit host confirmation;
- local JSON + Excel response delivery;
- a precise data-boundary diagram;
- Chrome usage and troubleshooting;
- local development, Streamlit deployment, and verification inside collapsed
  `<details>` sections so technical material does not dominate the page.

The README must use only GitHub-compatible Markdown and HTML. Color and visual
identity come from the bitmap assets because GitHub strips custom CSS.

## Copy and Confidentiality

The README may describe stepwise responses, applicable follow-ups, required
completion checks, support messaging, and the fact that participant-facing
scores are absent. It must not reproduce instrument names, questionnaire item
wording, response-scale inventories, scoring algorithms, thresholds, study
schedules, study hypotheses, access credentials, or real participant data.

The operational repository is public, so the README must not claim that source
code is private. It must state accurately that media remains browser-local,
response values use transient Streamlit session memory, and the user-saved ZIP
contains the local JSON and Excel response record.

## Verification

Automated checks must prove that:

1. all six new assets exist locally and every README image target resolves;
2. the GIF is animated, has at least six frames, is 1440 x 810, and is under
   5 MiB;
3. every WebP has the approved dimensions and decodes successfully;
4. no operational README asset is byte-identical to any showcase asset;
5. the README contains the approved first-viewport story and no remote showcase
   image link;
6. credential signatures, participant artifacts, and prohibited confidential
   terms are absent from the README and asset metadata;
7. Markdown structure, links, animation, and static fallback render correctly
   before publication.
