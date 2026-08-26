<!--
PR title = Conventional Commit, e.g. feat(vad): integrate silero v5 segmenter
Reference the GitHub issue created from the HANDOFF_CHECKLIST.md item.
-->

Closes #

## What (one logical change)
<!-- If you need more than one sentence or the word "and", split the PR. -->

## How tested
- [ ] pytest backend/tests -q (or the subset covering this change)
- [ ] Manual verification: <!-- what you clicked/ran -->

## Reviewer checklist (from docs/GITHUB_WORKFLOW.md §3)
- [ ] Scope matches title; no drive-by changes
- [ ] Tests cover new behavior
- [ ] Pipeline-stage purity/type hints respected (spec §3)
- [ ] IPC schema change → schemas.py AND TS types updated together (spec §5), needs 2 approvals
- [ ] HANDOFF_CHECKLIST.md statuses updated
- [ ] Hallucination guards (spec §7) untouched
- [ ] No secrets / model weights / audio >60 s committed (workflow §6)

## Rollback note
<!-- One line: how does this behave under `git revert`?
     Straightforward code revert expected / flag-gated (flag name: ____) /
     contains data migration or format change — describe -->
