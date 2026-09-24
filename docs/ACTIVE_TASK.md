# ACTIVE_TASK — energy-ml-service

## Layer ID

F1

## Objective

Define shared contract v1.0.0 (canonical in simulation-backend, mirrored to
siblings) with known-answer fixtures and dependency-free verification.
Design only — no training, no code.

## Task status

blocked

## Review status

pending

## Repository and owner

- Repository: `energy-ml-service` (`https://github.com/NEXYRA-Techy-Panda/energy-ml-service.git`)
- Owner (foundation + long-term): Mohan.

## Current branch

`main` (verified; commit + push authorised by F1)

## Last checkpoint timestamp, including timezone

2026-09-24 18:29:39 +05:30 (IST) — F1 contract work complete and verified;
commit/push BLOCKED on missing git identity (asked twice, no values supplied).

## Applicable contract version

1.0.0 (defined; mirror under `contracts/v1/`).

## Completed steps

1. Continuity startup + F0.1 preservation + Python 3.13.15 verification
   (setup target for this repo; dependency compat is F2; F1 needs no Python).
2. Contract mirror received + verified 49/49 (all five repos).
3. Continuity docs: HANDOFF F1 addendum (+dated Python correction), prompt
   push-policy, README links, docs/F1_EVIDENCE.md.
4. Staged-file inspection: task-owned files only.

## Files changed

- Created: `contracts/v1/` (7 files), `scripts/verify-contract.mjs`,
  `.gitignore`, `docs/F1_EVIDENCE.md` (+ F0/F0.1 docs as reviewed foundation).
- Updated in F1: `docs/ACTIVE_TASK.md`, `docs/PROGRESS_LOG.md`,
  `docs/HANDOFF.md`, `docs/AGENT_START_PROMPT.md`, `README.md`.
- Preserved: `docs/PROJECT_CONTEXT.md`, `docs/WORKSPACE_MAP.md`.

## Verification performed and actual results

- Verify script 49 passed / 0 failed in all five repos. Semantic checks only.
  No implementation artifacts.

## Incomplete edits and uncommitted changes

- None incomplete. Committing now with
  "docs: establish foundation and v1 data contracts".

## Blockers or unknowns

- BLOCKED: no git user.name/user.email (commit failed exit 128 in
  simulation-backend). Mohan asked twice; no values supplied, none configured,
  none invented. No commits exist; push auth untested. This repo fully
  untracked. Remediation: configure identity, add, commit, push per repo,
  verify hashes.

## Exact next action

Mohan: configure git identity, then per repo `git add`, commit ("docs:
establish foundation and v1 data contracts"), `git push -u origin main`,
verify remote hashes; then return F1 evidence for architecture review;
do not begin F2 until its prompt is supplied.

## Related-repository dependencies

Canonical contract in `../simulation-backend`. Sole caller:
`../auditor-backend` (4001). Siblings: 3000/4000/3001. This repo's port: 8000.

## Commit reference

To be recorded in the F1 evidence report after push (no hash loop in docs).
