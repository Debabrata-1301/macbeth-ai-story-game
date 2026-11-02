# Phase 7.5: Narrative intelligence

## Architecture

The deterministic game engine remains authoritative for scene transitions, flags, choices, character state, knowledge, and endings. The narrator receives a read-only snapshot and may return prose, authorized dialogue, exact engine choices, and optional source provenance. Invalid output is rejected before it is shown.

Retrieval embeds a query once, searches the authored exact Act and scene first, and applies a configurable cosine relevance floor (`RAG_MIN_RELEVANCE`, default `0.35`). If that scoped search has no qualifying result, it retries within the same Act. If neither returns a qualifying passage, the response has no source references. Results include scope and cutoff metadata; citation IDs must match actual returned chunks.

The prompt separates protagonist-known facts and uncertain beliefs from narrator-only route flags. It labels the canonical source as reference evidence rather than proof that canonical events occurred in the active alternate history. The timeline summary uses persisted flags and visible event records. Prompts cap combined generated prose at `NARRATIVE_MAX_WORDS` (default 180), and operational logs record retrieval scope, counts, estimated prompt tokens, stage timings, output size, citation count, campaign, and scene without logging private prompt text.

## Knowledge and event visibility

New choice definitions can specify `event_visibility`, explicit `witness_character_ids`, `informed_character_ids`, and `rumoured_character_ids`. Persisted events record those fields, recipients of explicit knowledge grants, and an authored summary. Scene attendance alone does not grant knowledge. Private is the default. Old saves hydrate event visibility as `unknown`; old events are visible only to their actor. Prompt history includes only public events, events explicitly witnessed or learned, rumours explicitly directed to the character, and the character's own actions. Nonessential event metadata is stripped before prompting.

This is a per-game save boundary: a choice in Macbeth's game cannot appear in a separate Banquo game. Within one game, an event becomes visible only through its explicit visibility contract. Rumour recipients remain uncertain rather than receiving confirmed facts.

## Character voice and continuity

Macbeth is guided toward controlled authority that may fracture under guilt or fear; Lady Macbeth toward precise persuasion and evolving composure; Banquo toward measured skepticism; and Macduff toward direct, politically restrained grief or resolve. Existing psychology, memories, commitments, relationships, and uncertain knowledge continue to supply the changing emotional context. A deterministic check prevents dialogue from a dead character, except Banquo after the ghost flag is established.

The frontend labels alternate-history scenes and now exposes validated source document, Act, scene, and page provenance in an accessible disclosure. It does not present a source reference as proof of a player's alternate events.

## Compatibility and limitations

New event fields have defaults, so old SQLite JSON payloads remain loadable without a table migration. Existing saves keep their prior route state. The FAISS index is not rebuilt. Visibility defaults are deliberately conservative; old records cannot be retroactively assigned witnesses. Deterministic consistency checks cover known dialogue-speaker life state and a short list of explicit Banquo, Duncan, and Macduff-family route contradictions, not every possible factual claim in free prose. Semantic voice quality still requires human review; local model output can vary.

## Evaluation and test results

The repeatable real-model run is `python scripts/evaluate_narrative.py`; it uses the local qwen3:4b and nomic-embed-text models, the existing 153-chunk index, and a fresh temporary SQLite database. Its full output (including representative narration) is saved in [phase_7_5_evaluation_results.json](phase_7_5_evaluation_results.json).
The evaluation harness retries a rejected narration once to measure recoverability; gameplay keeps its existing explicit retry flow so the accepted choice is never applied twice. The default generation limit is 768 tokens, configurable through `GENERATION_MAX_TOKENS`.

The final evaluation generated and validated all 10 scenarios. They covered Macbeth before Duncan's murder (83 words), after regicide (91), and facing Banquo after betrayal (38); Lady Macbeth at the psychological crisis (53) and alternate-history reconciliation ending (98); Banquo suspicion (123) and survival (45); Macduff protecting family (51) and seeking justice (61); and the patient canonical ending (43). Two first responses triggered deterministic validation failures; their one-attempt retries passed. Mean end-to-end time, including retries, was 17.63 seconds, range 11.44-30.81 seconds. Source references were retained only when validated; the Banquet scene returned none. Word counts include narration, dialogue, and atmosphere.

Example excerpts from an earlier run (the final run's complete output is in the JSON artifact):

- Macbeth after regicide: “My hands are stained with blood that won’t wash away.”
- Banquo suspecting Macbeth: “The crown is on Macbeth’s head, but peace has not followed.” The scene remained framed as suspicion and supplied three engine choices.
- Canonical patient ending: “I let the prophecy wait. Scotland’s next day is uncertain, but for this night my hand is still my own.” It returned no choices.

These examples demonstrate state-conditioned prose in these fixed cases; they do not prove general semantic quality. The model sometimes repeats narration in dialogue, and style varies across runs. The deterministic validator catches invalid structure, speakers, nonterminal choices and provenance, dead dialogue speakers, and a short list of route contradictions. It does not understand every free-prose claim.

Validation on this workspace:

- Python 3.13: `pytest -q --basetemp=.pytest-tmp` - 150 passed, 1 third-party deprecation warning.
- Frontend Vitest: 29 passed across 5 files.
- TypeScript checks and Vite production build: passed.
- Mocked Playwright: 9 passed.
- Local Ollama Playwright: 1 passed; real turn returned HTTP 200 with no generation error in 18.0 seconds; whole browser test took 25.6 seconds and verified persistence/resume/delete against temporary SQLite.
- Ten-case real Ollama evaluation: 10/10 valid structured responses after at most one retry; two first-pass validation failures recovered; 17.63-second mean including retries.

The single browser smoke test includes Vite/backend startup and user interaction and is not directly comparable to the scripted per-narration timings. Timings will vary with local model load and hardware.
