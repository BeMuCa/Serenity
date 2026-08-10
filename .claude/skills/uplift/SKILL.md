---
name: uplift
description: Use when implementing or modifying code as a subagent — especially on a smaller/faster model (Haiku, Sonnet) — load BEFORE writing any code, and again before reporting results. Also use when a test command fails to run, test counts look unexpected, or you are about to call a failure "pre-existing" or "unrelated".
---

# Uplift — implementation discipline for delegated coding

## Overview

You are executing work that a more deliberate pass planned. The failure mode is not writing bad code — it is **verifying loosely and reporting smoothly**. Slow down at three checkpoints: before coding (ground), before claiming (verify), when blocked (surface).

**A smooth report of numbers you didn't actually obtain is worse than a blunt report of a blocker.** The orchestrator can fix a blocker; it cannot fix a false green.

## 1. Ground before code

- Read the actual target file and every symbol you'll touch or call. Never assert something exists or is missing without having read/grepped it *in your working directory this session*.
- Grep for an existing helper before writing a new one; mirror the sibling code's conventions (header block, docstring voice, comment density, test style of the file you're extending).
- Restate the task as concrete checks you can run. If the task references a spec section, read it before designing.

## 2. Prove it works — the loop

Failing test → watch it fail for the right reason → minimal implementation → targeted test passes → **full prescribed gate** → commit. If a task tells you the gate command, that exact command IS the definition of done.

## 3. Verification integrity (the hard rules)

- **Run the EXACT prescribed command.** If it cannot run (missing interpreter/venv/tool/path), STOP and report the blocker in your final message. Substituting another interpreter or a test subset **silently** is forbidden — if you substitute, your report must lead with what you substituted and why the result may differ (missing extras change skip/fail profiles).
- **Establish the baseline BEFORE claiming.** Run the gate on the untouched tree first (or state the documented expected count if the task gives one). After your change, compare totals. An unexpected total — more tests, fewer tests, any failure — is a finding to investigate, not a detail to narrate past.
- **"Pre-existing" requires proof.** You may only call a failure pre-existing/unrelated after re-running it on a clean tree (stash your diff or checkout HEAD) and showing it fails there too. No clean-tree run → no such claim.
- **Numbers must be copy-pasted.** Every count in your report comes from output you produced this session. Never round, recall, or estimate a test count.

## 4. Report shape (REQUIRED fields)

Your final report contains, in order:

1. **What changed** — files + one-line why each.
2. **Commands run** — verbatim, with the exact result line pasted (e.g. `1157 passed, 5 skipped in 41.2s`).
3. **Baseline vs after** — expected/before totals vs your after totals; call out any delta.
4. **Deviations & blockers** — anything you substituted, skipped, or couldn't run. "None" means the command you ran is **byte-identical** to the prescribed one — a different interpreter path, an added env var, an absolute-path rewrite, or a test subset is a deviation, even when harmless. Declaring it costs one line; hiding it costs trust in the whole report.
5. **Not verified** — what you did NOT check (platforms, integrations, paths without tests).

## Red flags — STOP, you are about to file a false green

| Thought | Reality |
|---|---|
| "4 pre-existing failures in unrelated modules" | Proven on a clean tree? If not, they're YOUR failures until shown otherwise. |
| "Full suite passes: N tests" | Is N the expected total? A short count means collection errors or a partial run. |
| "The venv is missing, I'll just use python3" | Fine to try — but the report must lead with the substitution, or it's fabricated verification. |
| "I ran the module's tests; the rest can't be affected" | Imports, fixtures, and registrations cross module lines. Run the full gate or report that you didn't. |
| "The logic is straightforward, it works" | Execution evidence or it didn't happen. |
