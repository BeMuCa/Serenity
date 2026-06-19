# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

`Serenity` (a.k.a. ProjectSerenity) is greenfield — currently in the design/brainstorm phase, no source code yet. `img/` holds the mascot artwork (illustrated + pixelated poses). Architecture, build, and test commands will be documented here as the codebase takes shape.

## Communication

- When reporting information, be extremely concise — sacrifice grammar for concision.
- After each new script/function or code change, ask if I want an explanation. For small changes, just tell me about it. When I want one, explain the code and how it fits into the whole software. I want to understand and learn from everything written.

## Editing discipline

- Don't change or overwrite comments I add — only do so when a code change makes the comment obsolete or false.
- Touch only what the request requires. Don't "improve" adjacent code, refactor things that aren't broken, or reformat. Match existing style even if you'd do it differently.
- Remove imports/variables/functions that *your* changes orphaned. Don't delete pre-existing dead code — mention it instead.
- Minimum code that solves the problem. No speculative features, abstractions for single-use code, or error handling for impossible scenarios.

## Required: header comment on every Python script

Every Python script starts with this block:

```
============================================================
Author:  Berk
Created: <YYYY-MM-DD>
Purpose: One-line description of what the script does.
Role:    1-3 lines describing where this script fits in the larger codebase.

Functions:           ← (or Models / Fields / Test classes — pick the right label)
- func_name(args) — one-liner explanation
============================================================
```

## Required: maintain `notes/`

- `notes/0_Learnings.md` — record learnings I have while coding. Identify them from my questions, advanced code concepts, library mentions, etc. Include a table of contents.
- `notes/1_Planning.md` — track planning across sessions: mental notes, next steps, follow-up tasks, important considerations. This is the source of truth when I ask "what's next?". Update after each milestone.
- `notes/2_System_Arch.md` — system architecture overview, local use vs. deployment. Include a diagram showing what goes to which service, and a per-service breakdown of its function and why it's indispensable.

## Working approach

- Don't assume; don't hide confusion. If something is unclear, stop and name it. If multiple interpretations exist, present them rather than picking silently. If a simpler approach exists, say so.
- Transform tasks into verifiable goals and loop until verified (e.g. "fix the bug" → write a test that reproduces it, then make it pass). State a brief step→verify plan for multi-step work.

1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

State your assumptions explicitly. If uncertain, ask.
If multiple interpretations exist, present them - don't pick silently.
If a simpler approach exists, say so. Push back when warranted.
If something is unclear, stop. Name what's confusing. Ask.
2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

No features beyond what was asked.
No abstractions for single-use code.
No "flexibility" or "configurability" that wasn't requested.
No error handling for impossible scenarios.
If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:

Don't "improve" adjacent code, comments, or formatting.
Don't refactor things that aren't broken.
Match existing style, even if you'd do it differently.
If you notice unrelated dead code, mention it - don't delete it.
When your changes create orphans:

Remove imports/variables/functions that YOUR changes made unused.
Don't remove pre-existing dead code unless asked.
The test: Every changed line should trace directly to the user's request.

4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

"Add validation" → "Write tests for invalid inputs, then make them pass"
"Fix the bug" → "Write a test that reproduces it, then make it pass"
"Refactor X" → "Ensure tests pass before and after"
For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.