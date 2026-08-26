# GitHub Workflow & Safety Rails

**Purpose:** keep `main` shippable at all times and make any change trivially reversible. Read this alongside docs/DEVELOPMENT_SPEC.md (§9 milestones) and update docs/HANDOFF_CHECKLIST.md status in every PR.

---

## 1. Golden Rules

1. **`main` must always build and pass tests.** No exceptions, no direct pushes.
2. **Small PRs only.** Target ≤ 400 changed lines of real code (excluding tests/docs). A PR touching 3 modules is almost always 3 PRs.
3. **One logical change per PR**, described by its title. If the description needs the word "and", split it.
4. **Revert first, debug later.** If anything on `main` misbehaves, the default action is an immediate revert PR — not a fix-forward on top of unknown breakage. Investigate afterwards, on a branch.
5. Nothing merges without CI green + one approving review (two for IPC schema changes, see spec §5).

## 2. Branching Model

Trunk-based, short-lived branches off `main`:

```
main                         ← always releasable
└── feat/<issue#>-<slug>     feature work        e.g. feat/42-silero-vad
    fix/<issue#>-<slug>      bug fixes           e.g. fix/57-vad-padding
    chore/<slug>             tooling, deps, docs e.g. chore/ruff-config
    spike/<slug>             throwaway experiments — never merged as-is;
                             conclusions become normal PRs
```

- Branches live ≤ ~5 working days. If larger than that, merge behind the milestone boundary or split.
- Milestone deliverables (spec §9 M0–M6) are cut as tags `m0`, `m1`, … once their acceptance line passes. Tags are immutable checkpoints to roll back to.

### Commit conventions

[Conventional Commits](https://www.conventionalcommits.org): `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. Each commit keeps the repo buildable (`pytest backend/tests -q` green) so that bisect/revert operate on meaningful units.

```
feat(vad): integrate silero v5 segmenter

Fixes #42
Refs spec §4; checklist M1 item 2
```

## 3. Pull Request Checklist (in the PR template)

A reviewer confirms:

- [ ] Scope matches title; no drive-by changes (park them in follow-up issues)
- [ ] Tests cover new behavior; `pytest backend/tests -q` and frontend checks pass in CI
- [ ] Pipeline stage functions stay pure/typed where spec §3 requires it
- [ ] Any IPC schema change updates `ipc/schemas.py` AND TS types in the same PR (spec §5)
- [ ] HANDOFF_CHECKLIST.md item statuses updated
- [ ] Spec §7 hallucination guards untouched
- [ ] No secrets, tokens, model binaries, or audio fixtures >60 s committed (see §6)

## 4. Backpeddle Playbook (the part you asked for)

Ordered from least to most invasive — use the smallest tool that works.

| Situation | Action |
|---|---|
| Bad commit found immediately | Revert the single commit: `git revert <sha>` → PR → merge (fast, preserves history) |
| Bad PR identified post-merge | `git revert -m 1 <merge-sha>` via "Revert" button on GitHub |
| A whole feature went sideways | Revert the PRs in reverse chronological order (newest first) until stable; re-introduce via fresh branches referencing original issue numbers |
| Milestone tagged then problems appear everywhere | Cut a hotfix branch from last good tag: `git checkout -b hotfix m1 && ...` — tag `m1.1` after fix; meanwhile investigate on trunk |
| Repo state suspect (force-push accident etc.) | Every milestone tag + CI artifacts are the recovery points; restore from the newest green tag |

**Hard requirements that make this work:**

- Never rewrite pushed history on shared branches. No force-push to `main`; branch protection enforces this.
- Squash-merge is **allowed but discouraged** — prefer plain merge commits so individual commits remain individually revertable and bisectable. Squash only if the PR's internal commits were noise.
- Keep merged-PR number ↔ revert mapping obvious: revert commit titles say `Revert "<original title>" (#<n>)` — the GitHub button already does this. Don't hand-edit them.

**Feature-flag layer:** features that carry integration risk (diarization, live mic, Parakeet toggle) land dark behind settings flags (`parakeet.enabled`, `streaming.enabled`). Flip flags in tiny separate PRs so disabling a feature is a one-line revert, independent of its code landing.

## 5. Issue Tracking

- Every task = a GitHub issue carrying: the HANDOFF_CHECKLIST.md item text verbatim, target milestone label (`M0`…`M6`), estimate context.
- Bugs get `repro steps / expected / actual / fixture reference`. Attach silence-only or short clips (<60 s) directly; reference longer media by manifest entry.
- Decide de-scopes publicly in the "Known risks / decisions log" section of HANDOFF_CHECKLIST.md — link the issue where the decision was made.

## 6. What Must Never Be Committed

Enforced by `.gitignore` + CI secret scan:

- Hugging Face tokens or any credentials
- Model weights/checkpoints (>50 MB requires explicit discussion anyway)
- Long user audio; test fixtures >60 s
- `backend/.venv/`, node_modules, build artifacts

## 7. Releases

- Milestone tag → GitHub Release with auto-generated notes + installer artifacts attached (produced by CI, same commit).
- Installer builds must come from tagged, green-CI commits only. Local builds are for dev, never distribution.
