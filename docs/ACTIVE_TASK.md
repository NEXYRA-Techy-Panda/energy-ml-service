# ACTIVE_TASK — energy-ml-service

## Assignment / Layer ID

Agent B — Claude Code | P022 | M4 — excess-consumption detection.
Category: Mohan — Python analysis. Owner: Mohan.

## Scope

Additive POST /v1/anomalies: explainable robust (median/MAD) detector of
unusually high device power vs the device's own earlier comparable
observations. Not a malfunction/fault/drift diagnosis. /v1/analyze and
/v1/forecast unchanged; model_available stays false. Frozen parameters in
PROGRESS_LOG (P022 start entry).

## Task status

completed (implementation); review pending

## Review status

pending

## Previous task outcome (preserved)

P021 accepted based on supplied evidence (`ae23a61`); P016 candidate offline;
production forecast = P013 baseline.

## Current branch

`main` at `ae23a61672f074a7673a86e6a793739ef7f1d607` (== origin/main, clean).

## Last checkpoint timestamp, including timezone

2026-09-24 22:54:31 +05:30 (IST) — P022 completed; committing + pushing.

## Completed work

1. Design frozen and logged before implementation/evaluation.
2. app/anomalies/{constants,models,validate,detector,service,synthetic}.py; POST /v1/anomalies in app/main.py (additive).
3. tests/test_anomalies.py (24); full suite 130 passed; pip check clean; check_env OK; verifier 75/75.
4. scripts/evaluate_excess_detector.py (held-out synthetic seeds 7001–7005): TP 116, FP 0, FN 64; strong recall 0.9667; subtle 0.0 (below floor).
5. Live 127.0.0.1:8000: finding 200, insufficient 200, analyze/forecast/health/model-info unchanged; processes stopped.
6. Docs: P022 evidence, README, HANDOFF, PROGRESS_LOG.

## Exact next action

Commit + push, verify remote hash. Then STOP. Next: auditor-backend (Codex) may integrate POST /v1/anomalies per the P022 evidence; drift analysis is separate future work.

## Processes started by Agent B

Python service (launcher 12212 → interpreter 5940) on 127.0.0.1:8000 — stopped; none left running.

## Commit reference

Base: `ae23a61`. P022: the commit containing this file (hash in the P022 return report).
