# ACTIVE_TASK — energy-ml-service

## Assignment / Layer ID

Developer Mohan | M-C — Claude Code | P029-PREP — Python release verification.
Supporting Mohan release-readiness batch 28 / approximately 29.

## Scope

Exclusive write: energy-ml-service. One repeatable smoke-check command
(in-process default; explicit loopback HTTP mode) verifying health/model info,
analyze, forecast, anomalies, drift and validation; .gitattributes LF rules;
release-handoff documentation. No API behaviour change; no model work; no
listener on 19003; no VPS execution.

## Task status

completed

## Review status

pending

## Previous task outcome (preserved)

P024 completed (`208417e`), review pending; deployment commit `a0a86cc` fixed
the port at 19003.

## Current branch

`main` (base `a0a86cc5d96b16082d8a1d1b911de7a7d1b2474d`).

## Last checkpoint timestamp, including timezone

2026-09-25 02:20 +05:30 (IST) — P029-PREP implementation and verification complete.

## Completed work

1. Startup; baseline and constraints recorded.
2. `app/smoke.py` (`python -m app.smoke`): 11 checks, in-process / explicit
   loopback HTTP, pass/fail/error/skip, exit 0/1/2, `--json` summary report.
3. `tests/test_smoke.py` (14 tests); `.gitattributes` LF rules; `.gitignore`
   for local smoke reports.
4. Results: in-process 11/11 pass; pytest 167/167; pip check clean;
   check_env OK; verifier 75/75. No application defect found.
5. Docs: P029 evidence, README, HANDOFF (19003 runtime; stale 8000 marked
   historical); Windows command paths restored in README/HANDOFF/P013.

## Exact next action

None for M-C: P029-PREP stops here. Reviewer: run `python -m app.smoke` on the
VPS with the service's existing interpreter (in-process, then `--url
http://127.0.0.1:19003`) and record the fields in P029 evidence §8.

## Processes started by M-C

None (no listener started; in-process only).

## Commit reference

Base: `a0a86cc`. P029-PREP: see PROGRESS_LOG (commit hash recorded after push).
