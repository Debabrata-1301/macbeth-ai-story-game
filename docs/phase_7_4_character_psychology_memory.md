# Phase 7.4: Character psychology and memory

## Deterministic character simulation

All effects are authored per existing choice in `content/macbeth/character_effects.json`; the file is merged into the current scene choices by ID at load time. It adds no scene or choice. The engine applies these effects to a transition copy only after the choice passes its conditions, then persists the result and event atomically. Numeric dimensions are integers bounded to 0–100 (trust permits −100–100). New psychological dimensions are fear, stress, hope, and confidence; existing ambition, morality, suspicion, guilt, stability, influence, isolation, and resolve are retained. Authored deltas saturate at valid bounds. Event metadata records actual psychological and relationship outcomes and direct character state changes.

Relationships use ordered `character_a` (source) and `character_b` (target) identities. Trust, hostility, loyalty, fear, affection, and respect evolve independently. Choices may require directional trust, hostility, loyalty, fear, or respect thresholds; the existing Macbeth route now gates honoring Banquo on Macbeth's recorded trust in him. Relationship conditions stay hidden from the player-facing choice descriptions.

## Memory, commitments, and knowledge

`CharacterMemory` records the owner, campaign, originating accepted event, category, summary, source choice, certainty, importance, turn, visibility, related cast, and emotional significance. A transition gives the actor a personal decision memory; explicit knowledge transfers create recipient-specific memories; commitment events create memories for named owners, participants, and audiences. Duplicate event memories are suppressed. The in-save per-character cap is 100, and narrative retrieval selects at most five by importance, scene-person relevance, and recency.

Promises and secrets use `NarrativeCommitment`, with owner, participants, visibility, audience, creation event, status, and resolution event. Only an owner can fulfill or breach a promise. Only an owner, participant, or named audience can reveal a secret; public secrets become known to all characters in that save. Breached promises reduce the recipient’s trust and respect toward the owner, increase hostility, and raise the owner’s guilt and stress. Optional resolution directives allow a choice to resolve a commitment only when the relevant branch created it.

Confirmed `known_facts` remain separate from structured rumours, suspicions, and beliefs. Observations retain their category, confidence, source, event, and related characters. Secret content is transferred to authorized recipients only when an engine reveal occurs. Each save contains its own state, event rows, memories, and commitments; no character memory is queried across game IDs or campaigns.

Banquo's `banquo_challenge` records suspicion that Macbeth arranged the ambush without confirming the claim. The later `banquo_testify` choice adds the authorized fact and links both the prior suspicion and its memory to the confirming event. Narrative context distinguishes unresolved suspicions from historical suspicions later confirmed by evidence.

## Narrative and frontend

The read-only narrative orchestrator supplies the selected protagonist’s psychological state, confirmed facts, uncertain observations, up to five relevant owned memories, active authorized commitments, directional relationships involving the protagonist and current scene, recent own accepted events, and bounded RAG passages. Participant psychological state and other participants’ knowledge are omitted. Prompts label uncertain knowledge and narrator-only engine flags separately. The model still returns narration and dialogue only; the deterministic engine owns all state transitions.

The existing parchment status panel shows available psychological measures and an expandable journal for confirmed facts, suspicions/rumours, personal memories, and active commitments visible to the selected protagonist. Relationship rows preserve direction. Older API fixtures can omit new optional display fields; persisted Python saves hydrate new fields through Pydantic defaults. SQLite schema is unchanged because state is stored as JSON.

## Tests and operation

Verification on 2026-10-31:

- Python: `python -m pytest -q` — 145 passed, 1 upstream AnyIO/Pytest deprecation warning, in 20.38 seconds with coverage enabled (Python 3.13.1; isolated basetemp under the workspace).
- Frontend unit tests: `npm run test` — 28 passed.
- TypeScript: `npm run typecheck` — both application and end-to-end TypeScript projects passed.
- Production build: `npm run build` — passed; Vite emitted a 259.81 kB JavaScript asset (79.42 kB gzip).
- Mocked Playwright: `npm run test:e2e` — 9 passed in 23.7 seconds.
- Local Ollama Playwright: `npm run test:e2e -- --local` — 1 passed in 27.1 seconds; real `qwen3:4b` narration returned HTTP 200 with no generation error. The test used a temporary SQLite database and dynamic ports, then verified resume and deletion.
- RAG: no index, model, embedding, or retrieval implementation changes; personal memories use bounded structured filtering, with no extra embedding calls.

The full repository Ruff scan reports existing findings across unrelated files; changed engine and service files pass Ruff. `domain/models.py` has existing UTC-alias lint findings.

Memory retrieval uses in-memory filtering of already-loaded game state, with no new vector store or embedding calls. Context is capped at five memories, 12 uncertain observations, 12 own relationships, and the existing 24,000-character prompt limit. Local inference remains configured through the existing Ollama provider. The real inference smoke journey includes app startup, selection, narration, resume, and deletion; its elapsed time is not a standalone model latency measurement. Gameplay acceptance routes are directly tested: Macbeth's regicide and Banquo murder lead to a ghost-scene prompt containing guilt, betrayal memory, and directed hostility; Lady Macbeth's guilt and fragile stability survive SQLite restart and reach the crisis-scene prompt; Banquo's betrayal suspicion stays uncertain until testimony records confirming evidence. No scene or choice was added.

## Limitations

The effect table enriches key decisions and branches, rather than assigning an arbitrary stat change to every choice. Memory importance ranking is a small deterministic heuristic, not semantic retrieval. The game’s event schema does not record scene witness sets; memory recipients therefore come only from the acting character, explicit information recipients, and commitment participants/audiences rather than inferred witnesses. Narrative output validation verifies schema, speakers, and engine-authorized choices; it does not perform semantic fact-checking of every generated sentence, so prompt-side epistemic controls remain relevant.
