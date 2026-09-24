# PROGRESS_LOG — energy-ml-service

Append-only. Newest entry at the bottom. Correct outdated facts with a dated
correction entry; do not rewrite history.

---

## 2026-09-24 — F0 (reconstructed)

- Layer ID: F0 (repository setup and mapping).
- Developer/agent: F0 implementation agent (prior session). Reconstructed
  2026-09-24 during F0.1 from F0 docs and the supplied F0 report — commands
  below are **reported**, not re-run by the F0.1 agent.
- Objective: clone five repos, verify origins/branches, record tooling/ports,
  create shared context + handoffs + prompts + READMEs. No implementation.
- Changes: cloned `energy-ml-service` from
  `https://github.com/NEXYRA-Techy-Panda/energy-ml-service.git` into
  `../energy-ml-service` (`main`, no commits). Created untracked `README.md`,
  `docs/PROJECT_CONTEXT.md`, `docs/WORKSPACE_MAP.md`, `docs/HANDOFF.md`,
  `docs/AGENT_START_PROMPT.md`. Same pattern in siblings.
- Decisions/reasons: five independent repos; venv+pip+requirements proposed for
  this Python service; proposed port 8000; Python `3.12` recommended but
  explicitly provisional until F2 dependency checks.
- Commands/checks (as reported): clone/verify/fetch/ls-remote (empty),
  version checks (Git 2.55.0.windows.5; Python/pip/py unavailable), netstat
  (ports free). Parent not a Git repo.
- Unresolved at F0 close: **Python not installed** (top blocker for this repo
  from F2); Node pin undecided; docs uncommitted; F1 pending.
- Next action (as closed): return F0 evidence; await review.
- Review status and evidence source: **Accepted by architecture lead based on
  supplied evidence; local files were not directly inspected by the lead.**
- Commit references: none.

---

## 2026-09-24 17:47:57 +05:30 (IST) — F0.1 (actual)

- Layer ID: F0.1 (durable agent continuity, docs only).
- Developer/agent: F0.1 implementation agent (this session).
- Objective: continuity files + onboarding protocol.
- Changes (this repo): created `docs/ACTIVE_TASK.md`; this `docs/PROGRESS_LOG.md`;
  pending: `HANDOFF.md`, `AGENT_START_PROMPT.md`, `README.md` updates + final
  ACTIVE_TASK update.
- Decisions/reasons: verify-then-edit; preserve F0 docs; per-repo identity
  (owner Mohan; F1 needs no Python; Python install/runtime verification is F2).
- Commands/checks and actual results: AGENTS.md absent; `main`; correct origin;
  `status --short` → `?? README.md`, `?? docs/`; `log` → no commits; file
  listing matches F0 report.
- Unresolved items: remaining F0.1 edits; Python still missing (expected, F2
  work); review pending; no commits (by design).
- Next action: update HANDOFF/START_PROMPT/README; mark ACTIVE_TASK completed;
  readiness check; return F0.1 evidence. Do not begin F1.
- Review status and evidence source: pending; this file set + F0.1 report
  (working tree inspected directly).
- Commit references: none.

---

## 2026-09-24 17:51:10 +05:30 (IST) — F0.1 completion checkpoint (actual)

- Layer ID: F0.1. Task status: completed. Review status: pending (never
  self-assigned).
- Changes since the 17:47 entry: HANDOFF.md §0 set to completed; README links
  added; ACTIVE_TASK.md marked completed with full record; verification suite
  run (branch/origin/status/log per repo, 35-path link check, no-artifact scan,
  secret scan — all clean).
- Uncommitted changes: all F0 + F0.1 docs remain untracked by design; no commits.
- Next action: Return F0.1 evidence for architecture review; do not begin F1
  until its prompt is supplied.
- Commit references: none.

---

## 2026-09-24 18:02:31 +05:30 (IST) — F1 started (actual)

- Layer ID: F1 (versioned shared data + interface contract, design only).
- Developer/agent: F1 implementation agent (this session).
- Objective: define contract v1.0.0 (canonical in simulation-backend,
  mirrored to siblings) with fixtures + dependency-free verification; no
  application code.
- F0.1 outcome preserved above (completed; review pending at F0.1 close).
  F0/F0.1 review: accepted by architecture lead based on supplied evidence;
  local files were not directly inspected by the lead.
- Startup state: no AGENTS.md; all repos on `main`, correct origins, no
  commits, only untracked F0/F0.1 docs; fetch OK. Matches report.
- Owner updates applied/planned: Python 3.13.15 verified at supplied
  interpreter path (PATH shim stale, not modified); F0.1 "read-only" wording
  to be corrected; commit+push authorised from F1; hosting plan recorded
  (frontends Vercel, backends+Python on Mohan's VPS; no deployment in F1).
- Blockers/unknowns: no git user.name/user.email configured and no `gh` —
  commit/push will be attempted at completion; if auth fails, hashes and the
  exact remediation will be reported, nothing invented.
- Next action: author canonical contract bundle in
  `simulation-backend/contracts/v1/` + `scripts/verify-contract.mjs`.
- Review status: pending. Commit references: none yet.

---

## 2026-09-24 18:40:00 +05:30 (IST) — F1 contract authored + verified (actual)

- Changes: contract mirror received under `contracts/v1/` (+
  `scripts/verify-contract.mjs`, `.gitignore`); canonical copy lives in
  `simulation-backend/contracts/v1/`.
- Verification: `node scripts/verify-contract.mjs` → 49 passed, 0 failed in
  all five repos. Semantic checks only; formal schema validation is F2.
- Next action: continuity doc updates, then commit + push per repo.
- Review status: pending. Commit references: none yet.

---

## 2026-09-24 18:29:39 +05:30 (IST) — F1 commit/push blocked (actual)

- Contract work complete and verified (49/49 in all five repos); mirror +
  continuity docs + evidence files done.
- Commit blocked: no git user.name/user.email (commit in simulation-backend
  failed with exit 128, "Author identity unknown"). Asked Mohan twice; no
  values supplied, nothing configured, nothing invented. No commits exist;
  no push attempted (push auth untested). This repo remains fully untracked.
- To unblock: configure identity, then per repo `git add`, `git commit -m
  "docs: establish foundation and v1 data contracts"`, `git push -u origin
  main`, verifying each remote hash. No force-push.
- Task status set to blocked (commit/push step only); review pending.

---

## 2026-09-24 18:37:52 +05:30 (IST) — F1-R1 started (actual)

- Layer ID: F1-R1 (targeted pre-acceptance corrections, mirror repo). F1
  implementation completed; architecture review: changes_requested.
- Prior publishing resolved: F1 committed + pushed in all five repos.
- Objective: receive corrected mirrors (self-contained CSV; 12 dp precision +
  tolerances; extended verifier). Version stays 1.0.0. No F2.
- Startup: no AGENTS.md; clean tree at F1 commit; repo-local identity set.
- Next action: corrections authored in `simulation-backend`, then mirrored here.
- Review status: pending.

---

## 2026-09-24 19:07:48 +05:30 (IST) — F1-R2 completed (actual)

- Corrected 1.0.1 mirror received and verified 75/75 (all five repos).
- Continuity updated: ACTIVE_TASK completed, HANDOFF F1-R2 addendum,
  F1_EVIDENCE F1-R2 section. Review pending; no approval claimed.
- Next action: commit, push `main`, verify remote hash; return F1-R2 evidence.
  Do not begin F2.
- Commit references: F1-R1 pushed; F1-R2 recorded after push. Commit references: F1 pushed (see ACTIVE_TASK).

---

## 2026-09-24 18:43:07 +05:30 (IST) — F1-R1 completed (actual)

- Corrected mirror received and verified 54/54 (all five repos).
- Continuity updated: ACTIVE_TASK completed, HANDOFF F1-R1 addendum,
  F1_EVIDENCE F1-R1 section. Review pending; no approval claimed.
- Next action: commit, push `main`, verify remote hash; return F1-R1 evidence.
  Do not begin F2.
- Commit references: F1 pushed; F1-R1 recorded after push.

---

## 2026-09-24 19:01:33 +05:30 (IST) — F1-R2 started (actual)

- Layer ID: F1-R2 (mirror repo). F1-R1 completed; review changes_requested
  after direct inspection (CSV accepted, 54/54 confirmed).
- Objective: receive corrected 1.0.1 mirrors. No F2.
- Startup: no AGENTS.md; clean tree; fetch clean; repo-local identity present.
- Next action: corrections authored in `simulation-backend`, mirrored here.
- Review status: pending.
---

## 2026-09-24 19:20:00 +05:30 (IST) — F2-B started (actual)

- Layer ID: F2-B (backend application foundations), Agent B, developer Mohan.
- Previous outcome preserved: F1-R2 completed + pushed at `a585d1aa792aacfe3711c33f53a44275bb2f0b98`;
  accepted by the architecture lead based on supplied evidence. Contract
  1.0.1 is the implementation baseline and is read-only during F2-B.
- Startup: no AGENTS.md; clean tree; origin in sync; verifier 75/75.
- Ownership: Agent B owns the three backend repos only; Agent A owns the
  frontends concurrently.
- Next action: scaffold, install, verify, document, commit + push.
- Review status: pending.

---

## 2026-09-24 19:35:36 +05:30 (IST) — F2-B checkpoint (actual)

- Node backends scaffolded; verify:contract 75/75, validate:schema 24/24
  (Ajv 8.20.0, Draft 2020-12 strict), typecheck/lint/test/build exit 0.
- energy-ml-service .venv created (Python 3.13.15); pinned requirements;
  pip check clean; pytest 8 passed; fresh-venv repro install freeze identical.
- Environment incident: pandas import initially failed —
  "DLL load failed while importing parsing: An Application Control policy has
  blocked this file" (Windows Smart App Control). Mohan changed the Windows
  setting; re-test: numpy/scipy/scikit-learn/pandas import OK,
  scripts/check_env.py exit 0. No workaround in code.
- Next action: live HTTP checks on 4000/4001/8000, docs, commit + push.

---

## 2026-09-24 19:39:10 +05:30 (IST) — F2-B completed (actual)

- Layer ID: F2-B. Task status: implementation completed; review pending
  (never self-assigned).
- Results: verify-contract 75/75; check_env exit 0 (Python 3.13.15 venv, imports OK); pip check clean; pytest 8 passed; fresh-venv repro identical; live GET http://localhost:8000/health and /v1/model/info → 200 uninitialised envelopes; /v1/analyze 404.
- Live processes started by Agent B were stopped; none left running.
- Contract unchanged; ambiguities reported in docs/F2_B_EVIDENCE.md
  (CONTRACT.md §1 still says schema_version "1.0.0"; INTERNAL_ERROR code;
  Python envelope; model/info uninitialised shape).
- Deliberately not implemented: DB, simulation, uploads, interservice calls,
  training, deployment.
- Next action: commit + push, verify remote; next layer F3 pending its prompt.
- Commit references: F2-B hash recorded in the F2-B return report.

---

## 2026-09-24 20:38:41 +05:30 (IST) — P010 started (actual)

- Assignment P010 (category: foundation handoff + Mohan feature; layer
  F6-S documentation / Python deterministic analysis foundation), Agent B —
  Claude Code, owner Mohan.
- Permitted writes: simulation-backend continuity + handoff documentation
  ONLY; energy-ml-service implementation + docs. No simulator source,
  migrations, contracts, auditor-backend, frontends or parent files.
- Verified state: simulation-backend `6d26309`, energy-ml-service
  `22b0a08`, both == origin/main, clean; no AGENTS.md.
- Review record: P008 occupancy/schedule behaviour accepted based on supplied
  evidence; run-policy timing defect remains open. (F2-B was accepted based
  on supplied evidence, as recorded in later assignments.)
- Next action: implement deterministic POST /v1/analyze (vacant-beyond-grace rule) + tests.

---

## 2026-09-24 20:44:41 +05:30 (IST) — P010 ML foundation completed (actual)

- Deterministic POST /v1/analyze (vacant-beyond-grace-v1; method rule; no
  model). Validation: version, bounds (≤2000/≤2000 → 413), real timestamps,
  window, references, policy effectivity (no retroactive future policy),
  duplicates (identical deduped + warned, conflicting 400), energy
  consistency, forbidden fault fields anywhere.
- Results: pytest 45 passed; pip check clean; check_env OK; verifier 75/75;
  live port 8000: fixture → one vacant_but_on light finding (0.01 kWh
  avoidable, ₹0.10), fridge excluded.
- model_available stays false; forecast not implemented.
- Next action: commit + push; stop after P010. Review pending.

---

## 2026-09-24 20:53:32 +05:30 (IST) — P010 accepted (recorded)

- P010 (`36f5832f298379c3a889a32673c409152aa8eaf0`) accepted based on
  evidence as a deterministic rule foundation.

---

## 2026-09-24 20:53:32 +05:30 (IST) — P013 / M1 started (actual)

- Agent B — Claude Code | P013 | M1 (forecasting baseline). Category: Mohan —
  Python analysis. Exclusive write scope: energy-ml-service.
- Baseline `36f5832` == origin/main, clean; no AGENTS.md.
- Objective: POST /v1/forecast as an explainable statistical hourly baseline
  (next_24h, next_7d, next_calendar_month) per contract Example B; no trained
  model, no fabricated accuracy or intervals; chronological holdout
  evaluation vs repeat-last-day on explicitly synthetic data.
- Next action: freeze interface + eligibility constants, implement, test.

---

## 2026-09-24 21:01:23 +05:30 (IST) — P013 / M1 completed (actual)

- POST /v1/forecast: statistical baseline hourly-profile-median-v1 (no model;
  model_version null; uncertainty unavailable); strict validation (bounds
  413, future observations, grid, duplicates, NaN, timezone, fault fields);
  INSUFFICIENT_DATA 422 below eligibility; next_calendar_month = complete next
  local month.
- Results: pytest 82 passed; pip check clean; check_env OK; verifier 75/75;
  synthetic holdout (seed 20260924) baseline MAE 0.1223/0.1218/0.1239 kWh/h
  vs repeat-last-day 0.7018/1.3702/0.7765 (24h/7d/month) — synthetic only.
- Live port 8000: forecast 200 (24 points, 54.6749 kWh, day-class fallback
  disclosed), 72-hour history 422, analyze regression 200.
- Next action: commit + push; stop after P013. Review pending.

---

## 2026-09-24 21:08:33 +05:30 (IST) — P013 accepted (recorded)

- P013 (`7f71363aa9361e67a0cb2815b98aee79b0708cf9`) accepted as a statistical
  baseline based on reported evidence. Its synthetic metrics are not
  evidence of real-building performance.

---

## 2026-09-24 21:08:33 +05:30 (IST) — P016 / M2 started (actual)

- Agent B — Claude Code | P016 | M2 (trained forecast candidate). Category:
  Mohan — Python ML. Exclusive write scope: energy-ml-service.
- Baseline `7f71363` == origin/main, clean; no AGENTS.md.
- Finding before new work: P013's "aggregate energy error" was computed over
  COMMON SCORED hours only (e.g. 639 of 672 expected hours for next_24h and
  next_7d, 1343 of 1416 for the month, because of 5% missing synthetic hours)
  but was labelled as a per-origin aggregate / total error. The calculation is
  correct; the labels will be corrected (no numbers changed).
- Next action: correct P013 evaluation labels; then offline training
  workflow (input format, features, HGB candidate, temporal evaluation,
  bundles, tests). Production API unchanged.

---

## 2026-09-24 21:19:01 +05:30 (IST) — P016 checkpoint: workflow done, suite running (actual)

- Implemented app/training/{input,synthetic,features,candidate,evaluate,cli}.py;
  tests/test_training.py 21 passed; full suite 103 passed; pip check clean;
  verifier 75/75. Bundle workflow verified (evaluate --save-bundle, predict
  --check-reload → reload_identical true).
- Finding on trend_regime seed 101 (demo evaluate): the candidate beat the
  baseline for the first test weeks, then from ~19 Oct 2026 predicted ~4 kWh
  at working-day NIGHT hours (actual ~0.7). Cause: after the day-330 regime
  change the 90-day night-hour medians (0.55–0.65) lie in a range the trees
  only saw for daytime hours during training; tree ensembles do not
  extrapolate and split on the profile value rather than the hour.
- Decision: NO model redesign after inspecting test results (that would tune
  on the test holdout). The candidate is reported as-is; a more robust design
  (e.g. residual-to-profile target) is proposed for a future evaluation on
  fresh seeds/scenarios.
- Next action: wait for suite (artifacts/reports/p016-suite.json), then write
  evidence and docs, commit + push.

---

## 2026-09-24 21:26:28 +05:30 (IST) — P016 / M2 completed (actual)

- Suite (SYNTHETIC; seeds 101/202/303; 651 s): hours-weighted test MAE
  (baseline vs candidate) — weekly_stable 0.120/0.114 (24h), 0.118/0.113 (7d),
  0.120/0.116 (month); seasonal_ac 0.184/0.157, 0.186/0.159, 0.178/0.208;
  trend_regime 0.270/1.090, 0.278/1.040, 0.375/1.302. Candidate better in
  15/27 cells; catastrophic in 6 regime-change cells. 0 forecast failures;
  common scored hours 95–97 % of expected.
- Decision: candidate NOT integrated; P013 baseline stays production;
  model_available false; API unchanged.
- Verification: pytest 103 passed; pip check clean; check_env OK; verifier 75/75.
- Next action: commit + push; stop after P016. Review pending.
