# Privacy-Safe Questionnaire README Design

**Date:** 2026-07-28

## Goal

Reframe the public GitHub README from a recording-focused utility page into a
complete, polished demonstration of a protected home-session workflow. The
first viewport must communicate that recording is one stage in a broader
guided session that includes daily context, structured questionnaires, local
export, and completion confirmation.

## Audience

The primary audience is the invited research-group review. The repository may
remain publicly readable, so all content must also be safe for an uninvited
reader.

## First-Viewport Story

Use the neutral product name **Physical Stimulation Intervention Session
Companion** and a concise bilingual description. Present this six-stage flow
before detailed recorder documentation:

1. Controlled access
2. Daily context
3. Browser-local audio and video
4. Stepwise structured questionnaire
5. Local JSON and Excel package
6. Completion confirmation

Existing Alto-inspired colors, GIFs, screenshots, and the controlled-demo link
remain in use. The page should feel like a research workflow, not a camera SDK.

## Questionnaire Section

Add a prominent bilingual section explaining only approved interaction-level
properties:

- one focused step at a time;
- conditional follow-up behavior;
- complete capture of applicable responses;
- an immediate support message when the configured safety condition applies;
- no participant-facing totals, thresholds, interpretations, or risk labels;
- one local ZIP containing equivalent JSON and Excel response records.

The public synthetic sliders are identified as a privacy-safe interaction
surrogate. The README must clearly distinguish the protected operational
questionnaire from the public synthetic demonstration.

## Confidentiality Boundary

Do not publish instrument names, item wording, response option inventories,
scoring algorithms, thresholds, schedules that reveal the protocol, study
hypotheses, participant identifiers, access secrets, real recordings, or real
response values. Do not use the confidential intervention acronym or imply an
affiliation with the visual-reference organization.

## Existing Walkthrough

Retain the visual nine-step walkthrough but update its framing:

- recording is presented as a middle stage rather than the product identity;
- step 7 explains that synthetic feedback represents the protected structured
  questionnaire interaction without reproducing it;
- local export language covers questionnaire responses, not only sliders;
- the privacy diagram and troubleshooting remain accurate.

## Verification

The public-showcase audit must continue to pass. Add or update README contract
tests so the first viewport contains the complete six-stage story and approved
questionnaire concepts while forbidden private terms and real questionnaire
content remain absent. Render the README or inspect its GitHub-compatible
Markdown structure, links, images, and Mermaid block before publication.
