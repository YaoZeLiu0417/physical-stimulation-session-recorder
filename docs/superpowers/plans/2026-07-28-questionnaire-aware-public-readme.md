# Questionnaire-Aware Public README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the public GitHub page present the complete protected research-session workflow while preserving the existing confidentiality boundary.

**Architecture:** The public repository remains README-and-assets only. The README first viewport and workflow sections describe a generic structured-questionnaire stage and clearly distinguish it from synthetic public feedback; the private audit remains the publication gate.

**Tech Stack:** GitHub-flavored Markdown, Mermaid, existing GIF/WebP assets, Python privacy audit, pytest 8.

---

### Task 1: README contract test

**Files:**
- Modify: `tests/test_showcase_audit.py`
- Read: `D:/proj_taVNS/physical-stimulation-session-recorder-showcase/README.md`

- [ ] **Step 1: Write the failing contract test**

Add a test that reads the real public README from the sibling showcase clone and
requires the neutral product title plus these concepts before the first detailed
walkthrough: controlled access, daily context, browser-local audio and video,
stepwise structured questionnaire, local JSON and Excel package, completion
confirmation, no participant-facing scores, and protected-versus-synthetic
separation. Continue asserting that every `FORBIDDEN_TERMS` value is absent.

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_showcase_audit.py -k "questionnaire_story" -q`

Expected: failure because the README title and first-viewport story are still recording-focused.

### Task 2: Public README rewrite

**Files:**
- Modify: `D:/proj_taVNS/physical-stimulation-session-recorder-showcase/README.md`

- [ ] **Step 1: Rewrite the first viewport**

Use `Physical Stimulation Intervention Session Companion` as the H1. Add a
bilingual six-stage table immediately after the introduction: controlled
access, daily context, local audiovisual recording, structured questionnaire,
local JSON + Excel package, and completion confirmation. Keep the existing
workflow GIF directly visible.

- [ ] **Step 2: Add the questionnaire-experience section**

Describe one-step-at-a-time completion, conditional follow-ups, complete
applicable-response capture, immediate support copy, no participant-facing
scores or risk labels, and local response export. State that public sliders are
a synthetic interaction surrogate and that protected item text is omitted.

- [ ] **Step 3: Reframe the walkthrough and export sections**

Update the overview, step 7, local export, Chrome guide, privacy boundary, and
design-direction copy so recording is a middle stage and response packaging is
described generically. Preserve all existing image paths and the single approved
controlled-demo URL.

- [ ] **Step 4: Run focused tests and audit**

Run:

```powershell
python -m pytest tests/test_showcase_audit.py -q
python -c "from pathlib import Path; from showcase_audit import audit_showcase; findings=audit_showcase(Path(r'D:\proj_taVNS\physical-stimulation-session-recorder-showcase')); print('\n'.join(findings)); raise SystemExit(bool(findings))"
```

Expected: all tests pass and the direct audit prints no findings.

- [ ] **Step 5: Commit and publish the public README**

In the public clone:

```powershell
git add README.md
git commit -m "docs: present complete protected session workflow"
git push origin main
```

Retry transient push failures without force.

### Task 3: Final cross-repository verification

**Files:**
- Verify only.

- [ ] **Step 1: Validate links and repository states**

Confirm every relative README image exists, the approved app URL is the only
external URL, both worktrees are clean, and GitHub APIs report the pushed SHA
for each `main` branch.

