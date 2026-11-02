# Phase 7.6: Integration, testing, and release readiness

**Assessment date:** 2026-11-01

**Release recommendation:** **Passed with limitations — suitable for a single-person local beta on loopback; not ready for public or shared-network deployment.**
**Production save:** `data/macbeth.sqlite3` was not used or modified by the verification runs.

## Release-readiness matrix

| Area | Status | Evidence and tests | Limitations / outstanding actions |
|---|---|---|---|
| Four independent campaigns and narrative separation | Passed | 4 fresh campaign starts, distinct starts and choices; 60 scenes, 107 choices, 18 reachable ending IDs; all four campaigns save mid-route, resume after API restart, and complete on a representative route; 10 real-model scenarios across all four perspectives | Campaigns are separate saved timelines; actions are not synchronized between separate saves |
| Psychology, relationships, knowledge, memory | Passed | Existing deterministic simulation tests plus route tests and SQLite round-trip/restart coverage; older events without visibility data hydrate as `unknown` | Narrative semantic validation cannot prove every free-text claim |
| Persistence and save compatibility | Passed with limitations | Existing state JSON defaults; legacy campaign default; legacy event visibility test; restart/load, revisions, transaction rollback and event history tests | Backup restore procedure is documented but a manual recovery drill was not run |
| API and local security | Passed with limitations | Loopback test runner, schema validation, generic storage errors, no obvious embedded credentials found in focused source scan | No authentication, TLS, CORS allowlist, rate limits, per-user save isolation, or public request-size controls; local-only use |
| Retrieval and grounding | Passed with limitations | Existing 153-chunk FAISS index used by real tests; configured `nomic-embed-text` availability and embedding probe passed; citations checked against retrieved chunks | Offline index/model availability is local-machine dependent; no index rebuild or corpus audit performed |
| Local LLM integration | Passed | `qwen3:4b` and `nomic-embed-text` present; generation and embedding benchmark passed; real Ollama browser flow passed | Timing depends on cold/warm model state and available memory |
| Python tests | Passed | `159 passed`, 83% line coverage, 1 third-party AnyIO/Pytest deprecation warning; Ruff clean | Coverage is below full coverage, especially CLI and infrastructure error branches |
| Frontend tests and build | Passed | Vitest 5 files / 29 tests; TypeScript app and E2E checks; Vite production build passed | Browser snapshots/reports are local generated artifacts |
| Mocked browser integration | Passed | Playwright: 9 passed, 16.8s | Mocked backend does not substitute for real-model semantic quality |
| Real local Ollama browser integration | Passed | Playwright: 1 passed, 28.3s; generated response HTTP 200, no generation error; save/resume/delete on temporary SQLite | Uses local model and existing FAISS index |
| Real narrative evaluation | Passed with limitations | 10/10 valid responses, no retries; mean 15.88s (12.10–22.83s); results and narration in [evaluation JSON](phase_7_6_evaluation_results.json) | Ten fixed prompts are a smoke evaluation, not a broad human quality study |
| Dependencies | Passed with limitations | `npm audit --offline --json`: 0 reported vulnerabilities across 200 dependency entries; `pip check`: no broken requirements | Python `pip-audit` unavailable; online advisory checks were not run; offline npm advisory cache only |
| Public deployment | Not tested | No public deployment was attempted | Do not expose this API to an untrusted/shared network before adding an authenticated boundary and operational controls |

The complete machine-readable matrix is [phase_7_6_release_readiness.json](phase_7_6_release_readiness.json).

## Architecture and integrated behavior

The deterministic engine remains authoritative for choices, state changes, campaign boundaries, knowledge grants, and endings. The narrator receives a bounded read-only snapshot and may provide validated prose, permitted speakers, engine-authorized choices, and citations. Model availability checks now verify the exact configured generation and embedding models through Ollama's tags endpoint; they fail with actionable errors and never download a model.

Campaign inventories are:

| Campaign ID | Starting scene | Scenes | Choices | Endings |
|---|---|---:|---:|---:|
| `macbeth` | `heath_before_battle` | 35 | 60 | 10 |
| `lady_macbeth` | `lady_letter` | 11 | 18 | 4 |
| `banquo` | `banquo_heath` | 7 | 14 | 2 |
| `macduff` | `macduff_fife` | 7 | 15 | 2 |
| **Total** |  | **60** | **107** | **18** |

Each new game is a separate save and timeline. The stories inhabit the same authored setting, but changes are not globally synchronized between save IDs. Campaign inventory checks prevent a character's decision from entering another campaign's scene graph. In a single save, explicit visibility, witnesses, informed recipients, and rumour recipients scope event history. Legacy events without that contract default to `unknown` and are not treated as public knowledge. Confirmed facts remain distinct from uncertain beliefs. Narrative context is built only from the selected save and protagonist's authorized knowledge and memories.

Psychology and directional relationship changes are deterministic, authored choice effects persisted with the game state. Memories and commitments are associated with their owner, campaign, source event, audience, and visibility. Lady Macbeth's guilt and stability survive SQLite restart and influence the crisis-scene context. Banquo can hold suspicion about Macbeth's role without a confirmed fact; testimony/evidence is the confirmation step. Macbeth's regicide and later Banquo confrontation carry guilt and relationship context into narration.

RAG uses the existing local FAISS index and provenance-bearing Macbeth passages. Retrieval is scoped to the authored Act/scene and may fall back within the Act above a relevance cutoff. Citations must refer to returned chunks. Canonical text is reference evidence; it is not treated as proof that an event occurred on a diverged timeline. No corpus/index rebuild was performed for this milestone.

## Ending inventory and route coverage

- Macbeth: `patient_path`, `ambition_path`, `solitary_path`, `duncan_spared`, `macbeth_confessed`, `scotland_settlement`, `macbeth_surrendered`, `tragic_crown`, `banquo_lineage`, `tyrant_crown`.
- Lady Macbeth: `lady_spared`, `lady_confession`, `lady_reconciliation`, `lady_survival`.
- Banquo: `banquo_survived`, `fleance_escaped`.
- Macduff: `scotland_freed`, `macbeth_tried`.

Graph reachability coverage validates all Macbeth endings. Direct route tests cover all endings in the three additional campaigns, including the two Lady Macbeth routes and Macduff's Scotland-freed route added during this integration pass.

To answer the play/save/resume/complete question directly, an API-level integration test starts each of the four campaigns, plays a route to its midpoint, closes the app, creates a fresh app over the same SQLite file, resumes by game ID, completes the route, and reloads the terminal state and event history. The exercised endings are `patient_path`, `lady_survival`, `banquo_survived`, and `scotland_freed`. Other tests separately cover reachability/completion of the remaining 14 endings; they do not each repeat a mid-route restart.

## Real narrative samples

The unedited generated output is in the evaluation JSON. Representative excerpts:

- Macbeth after regicide: “The deed is done. I hear every sound as an accusation, and the blood on my hands seems impossible to wash away.”
- Banquo suspecting Macbeth: “The crown is on Macbeth’s head, but peace has not followed. I choose whether to confront him or protect my son first.” The prompt retained suspicion rather than asserting the murder plot as known fact.
- Lady Macbeth at crisis: “I wake with my hands raw from washing. The physician waits at the door; Macbeth has not asked what I remember.”
- Canonical patient ending: “I let the prophecy wait. Scotland's next day is uncertain, but for this night my hand is still my own.”

These examples show the tested snapshots, not a guarantee of general model quality. Output varies with model version, sampling, and local runtime.

## Verification results

Commands and outcomes on Python 3.13.1 / Windows:

- `python -m pytest -q --basetemp=.pytest-tmp` — **159 passed**, 83% line coverage, one upstream AnyIO deprecation warning, 9.85s. This includes four API restart journeys across all campaigns.
- `python -m ruff check src tests` — **All checks passed**.
- `npm test` — **5 test files, 29 tests passed**.
- `npm run build` — TypeScript app and E2E configurations passed; Vite built 42 modules, JS 260.22 kB (79.52 kB gzip).
- `npm run test:e2e` — **9 passed**, 16.8s.
- `npm run test:e2e:local` — **1 passed**, 28.3s; real generation 20.4s within the browser test, HTTP 200, no generation error.
- `python scripts/benchmark_local_inference.py --prompt-file scripts/smoke_prompt.txt` — model checks and embedding probe passed; measured connection/tags 2.35s, embedding 8.29s, generation 7.03s, total 20.00s. This includes cold model load and is one sample.
- `python scripts/evaluate_narrative.py` — **10/10** structured responses valid, zero retry/validation failures; mean 15.88s, range 12.10–22.83s. The suite used `qwen3:4b`, `nomic-embed-text`, the existing 153-chunk index, and temporary SQLite.
- `python -m pip check` — no broken requirements.
- `npm audit --offline --json` — zero reported vulnerabilities; offline advisory data only.
- Python `pip-audit` and an online dependency advisory audit — **not run** (`pip-audit` is not installed; network access unavailable).
- GPU: NVIDIA GeForce RTX 3050 6GB Laptop GPU, 6,144 MiB total. An idle snapshot reported 0 MiB used and 0% utilization; no continuous GPU/RAM pressure profile was collected.

The focused evaluation covers Macbeth's pre-regicide, post-regicide, and Banquo confrontation; Lady Macbeth's psychological decline and reconciliation; Banquo's suspicion and survival; Macduff's family protection and justice; a canonical ending; and an alternate-history ending. It is not a load test. The backend `InferenceGate` serializes local generation and embedding calls within a process, so simultaneous throughput is intentionally limited.

## Issues, severity, and limitations

**P0: none identified for local personal use.**

**P1: public/shared-network exposure is unsupported.** The API has no authentication or per-user authorization. If bound beyond loopback, an untrusted caller could enumerate/read/delete saves and trigger expensive local inference. Keep the service bound to `127.0.0.1`. Before any public deployment, add authentication, save ownership, TLS, explicit origin policy, rate and body-size limits, monitoring, and a recovery drill. This is a deployment boundary, not a blocker for the documented local beta.

**P2: security/dependency audit is incomplete.** The frontend's local/offline npm audit reports no known advisories in its cache. A current online advisory scan and Python dependency audit remain outstanding. Run them in a network-enabled release environment before distributing a public build.

**P2: semantic narrative validation is bounded.** Deterministic checks enforce response shape, campaign choices, citation provenance, speaker validity, and selected continuity constraints; they cannot establish the truth of every free-prose sentence. Continue human review of generated text and expand consistency tests for any newly authored branches.

**P3: performance is a local smoke measurement.** Cold model startup materially affects latency; one benchmark and ten sequential scenarios do not characterize sustained or concurrent load. No soak test or continuous GPU/host memory profile was run.

SQLite state and events are JSON-backed; new optional fields default on load, including conservative `unknown` visibility for old events. No schema migration was required. Compatibility was tested with legacy-shaped fixtures, not by modifying the user's production database. Backup instructions now include a separate-file restore check, but that operational drill remains unverified.

## Files created and modified

Created:

- `docs/phase_7_6_release_readiness_report.md` — this report.
- `docs/phase_7_6_release_readiness.json` — machine-readable status matrix.
- `docs/phase_7_6_evaluation_results.json` — full outputs and timings from ten real Ollama scenarios.

Modified:

- `README.md` — four campaign description, dynamic isolated Playwright runtime, test commands, backup verification, and local-only deployment scope.
- `.env.example` — corrected `GENERATION_MAX_TOKENS` from 512 to the actual 768 default.
- `scripts/benchmark_local_inference.py` — checks exact local model availability and probes embedding readiness; reports embedding latency and handles embedding errors.
- `scripts/evaluate_narrative.py` — writes this milestone's evaluation artifact without overwriting the Phase 7.5 results.
- `src/macbeth_game/llm/ollama.py`, `src/macbeth_game/rag/embeddings.py` — configured model availability checks.
- `src/macbeth_game/api/routes.py`, `src/macbeth_game/api/schemas.py`, `src/macbeth_game/domain/models.py`, `src/macbeth_game/repositories/sqlite_repository.py`, `src/macbeth_game/services/gameplay_turn_service.py`, `src/macbeth_game/services/narrative_orchestrator.py` — Ruff import/style normalization only.
- `tests/test_campaigns.py` — ending route coverage and removal of overly broad test exception catches.
- `tests/test_persistence.py` — old event visibility defaults and conservative hydration coverage.
- `tests/test_llm_provider.py`, `tests/test_rag.py` — configured model availability checks.
- `tests/test_foundation.py`, `tests/test_narrative_orchestrator.py`, `tests/test_story_engine.py`, `tests/test_story_expansion.py` — Ruff import/style normalization only.

The build and browser test commands also refreshed generated files in `frontend/dist`, `frontend/playwright-report`, and `frontend/test-results`.
