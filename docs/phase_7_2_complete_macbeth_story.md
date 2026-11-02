# Phase 7.2 — Complete Macbeth Story Expansion

## Scope and story graph

The existing Act 1 opening and its identifiers remain in place. The authored graph now contains 35 scenes and 60 engine-authorized choices, including the original ten scene IDs and the original endings `patient_path`, `ambition_path`, and `solitary_path`. All 35 scenes are reachable from the existing opening, every non-ending has at least one outgoing choice, and all 10 ending scenes are terminal.

The Act 2–5 route follows Macbeth's moral crisis before Duncan's murder; the murder and discovery; succession and coronation; Banquo's prophecy, the ambush and feast; the unstable court and Macduff's opposition; the apparitions and the choice concerning Macduff's household; Malcolm's alliance and rebellion; Lady Macbeth's sleepwalking; Birnam Wood, the siege, and the final confrontation. Choice routes can refuse the murder, confess, protect or frame others, spare or target Banquo, determine Fleance's fate, spare or attack Macduff's household, accept or resist Malcolm's alliance, and settle, surrender, flee, fight, or cling to the crown.

The ten terminal IDs are:

| Scene | Ending ID | Outcome |
|---|---|---|
| `patient_ending` | `patient_path` | Original patient path |
| `ambition_ending` | `ambition_path` | Original ambition path |
| `solitary_ending` | `solitary_path` | Original solitary path |
| `duncan_spared_ending` | `duncan_spared` | Regicide refused |
| `macbeth_confession_ending` | `macbeth_confessed` | Macbeth confesses after the murder |
| `scotland_settlement_ending` | `scotland_settlement` | Negotiated restoration or succession |
| `macbeth_surrender_ending` | `macbeth_surrendered` | Surrender to Malcolm |
| `tragic_tragedy_ending` | `tragic_crown` | Final combat ends in Macbeth's death |
| `banquo_lineage_ending` | `banquo_lineage` | Macbeth escapes; Fleance's line remains possible |
| `tyrant_crown_ending` | `tyrant_crown` | Macbeth holds power by force |

These are deterministic outcomes; the LLM can narrate them but cannot choose or alter them.

## Canon, adaptation, and alternate history

Each scene has a `source_classification`. `canonical_adaptation` means the scene adapts the corresponding Shakespearean dramatic situation in original game prose. `alternate_history` marks game-created divergence or an ending that is not Shakespeare's sequence. Existing scene IDs are preserved. Act/scene metadata is only populated when the source correspondence is supported by the local source index; several scenes have act-only metadata because the PDF index does not expose a reliable exact scene heading. Act-only metadata filters retrieval to that act without asserting a scene match. Scenes with no source mapping receive no RAG claim.

The story uses original summaries, narration, descriptions, and dialogue. The corpus remains read-only. Retrieval filters the already loaded metadata/vector set by the authored act and, where available, scene; no index rebuild or model download is part of normal play. Retrieved passages remain reference material and do not authorize choices. Canonical events and alternate events are separately identified in prompts and in the gameplay scene label.

## Characters and state

The four playable profiles remain Macbeth, Lady Macbeth, Banquo, and Macduff. Five additional people—Duncan, Malcolm, Fleance, Lady Macduff, and Macduff's child—are represented as non-playable character definitions and speakers so that authored choices can track their survival and knowledge without exposing them in character selection.

Choices continue to change deterministic character attributes, life status, knowledge, relationship trust/hostility, and flags. Relationship changes identify their source where needed and the engine rejects self-relationships. Conditions gate later choices on facts such as whether Banquo survived, whether Fleance escaped, whether Macduff was detained, whether the household was spared, and whether Malcolm's alliance was accepted. The LLM receives participant state for continuity but is told that state does not imply the selected character knows private events.

Phase 7.2 adds authored participation and causal choices for all four playable character selections while retaining the existing shared Macbeth-centered plot. It does not create four separate campaigns or independent scene graphs; those remain future work. The current selection is retained in save data and remains the first-person narrator identity.

## Save compatibility

No SQLite schema or migration was added. New NPC state entries live in the existing serialized `GameState.character_states` JSON. When an older save lacks those entries, `GameService` hydrates missing character states in memory with defaults. Existing values, flags, events, game IDs, and revisions are preserved; the next accepted transition persists the hydrated state through the existing repository transaction.

## Validation

`tests/test_story_expansion.py` validates graph reachability, unique choice IDs, terminal metadata, original IDs, ten endings, playable/NPC boundaries, consequence state, authored paths to each ending, and old-save hydration. Existing engine, RAG, prompt, orchestration, persistence, frontend, and Playwright checks cover the interfaces that consume the new content.
