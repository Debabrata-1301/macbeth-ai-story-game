# Phase 7.3 — Four Independent Character Campaigns

## Architecture and persistence

`content/macbeth/campaigns.json` is the campaign catalog. Each entry defines a stable campaign ID, protagonist, player objective, introduction, opening scene, and scene inventory. The Macbeth catalog entry owns the existing 35-scene Act I–V route. Lady Macbeth, Banquo, and Macduff use authored scenes in `campaign_scenes.json`; these are loaded and validated with the original scene graph.

`GameState.campaign_id` is persisted inside the existing SQLite `state_json`. New games choose the campaign mapped to the selected protagonist. Every transition is checked against the saved campaign inventory, including the destination scene. A legacy state without `campaign_id` defaults to `macbeth`, preserving the old Macbeth-led route regardless of selected narrator; the current scene is never used to guess campaign identity. SQLite schema, game IDs, revisions, and event history are unchanged.

## Campaign catalog

| Campaign ID | Protagonist | Starting scene | Objective | Scenes / choices / endings |
|---|---|---|---|---:|
| `macbeth` | Macbeth | `heath_before_battle` | Win the crown without losing himself, or survive ambition’s ruin. | 35 / 60 / 10 |
| `lady_macbeth` | Lady Macbeth | `lady_letter` | Shape power, reckon with its cost, and choose what remains. | 11 / 18 / 4 |
| `banquo` | Banquo | `banquo_heath` | Investigate prophecy, protect Fleance, and choose the future that survives. | 7 / 14 / 2 |
| `macduff` | Macduff | `macduff_fife` | Protect his family, build resistance, and determine Scotland’s next rule. | 7 / 15 / 2 |

The three new campaigns contain 25 scenes and 47 choices, bringing the combined catalog to 60 scenes and 107 choices. Their scenes and endings are distinct; they do not route into Macbeth’s choices.

### Lady Macbeth scene inventory

`lady_letter` → `lady_duncan` → `lady_night` → `lady_queen` → `lady_banquet` → `lady_crisis`, with `lady_ghost` inserted if Lady Macbeth enabled Banquo’s murder. Endings are `lady_spared`, `lady_confession`, `lady_reconciliation`, and `lady_survival`. Her choices shape counsel, Duncan’s fate, Banquo’s survival, evidence concealment, her relationship with Macbeth, and her own fate. The ghost appears only on the murder branch. `guilt`, `emotional_stability`, `influence`, and `isolation` are explicit character-state dimensions. They are displayed in her status panel and persisted with the save. Sleepwalking is an authored crisis scene, not an inevitable ending.

### Banquo scene inventory

`banquo_heath` → `banquo_forres` → `banquo_court` → `banquo_ambush`. Banquo can investigate, warn Duncan, build support, challenge Macbeth, leave, survive the attack, or die protecting Fleance. A survivor proceeds to `banquo_feast` as a living witness; the ghost cannot appear on that timeline. A dead Banquo reaches the terminal `banquo_lineage` ending while Fleance escapes. Fleance’s survival and escape are recorded independently.

### Macduff scene inventory

`macduff_fife` → `macduff_court` → `macduff_family` → `macduff_england` → `macduff_birnam`, ending at `macduff_victory` or `macduff_trial`. The player begins with Lady Macduff and the child alive in Fife. Warnings, evacuation, concealment, or departure affect both NPC life state and knowledge. Macduff then determines alliance aims and how Macbeth is removed.

## Shared world, knowledge, and RAG

Campaign saves are separate timelines in one setting. Canonical adaptations name their source classification and available Act/Scene metadata; choices that diverge from Shakespeare are marked with explicit state flags and alternate-history endings. For example, Lady Macbeth can prevent Duncan’s murder, and Macduff can save his household. Later narration receives the saved campaign ID, current scene, current engine continuity flags, selected-character knowledge, and current participant state. Other characters’ private `known_facts` are omitted from the prompt. Engine flags are labeled as continuity data, not as facts the protagonist automatically knows. Event history remains conservatively scoped to events attributed to the selected protagonist.

The existing local FAISS index is unchanged. Campaign scenes provide authored Act and Scene labels to the existing filtered retrieval call where a Shakespearean correspondence is defined. Alternate-history endings have no false canonical reference. The narrative validator continues to authorize only engine-generated choices and permitted scene speakers.

## Relationships and character state

Campaign choices record trust or hostility between the protagonist and relevant characters. Existing relationship validation and deterministic transition rules apply unchanged. Macbeth retains his established ambition, suspicion, regicide, Banquo, rebellion, and final-confrontation mechanics. Lady Macbeth’s psychological state is tracked directly; Banquo’s resolve and knowledge reflect his investigation and survival; Macduff’s resolve, family state, alliance, and knowledge track the resistance.

## Ending inventory and prerequisites

Macbeth retains its ten Phase 7.2 endings: `patient_path`, `ambition_path`, `solitary_path`, `duncan_spared`, `macbeth_confessed`, `scotland_settlement`, `macbeth_surrendered`, `tragic_crown`, `banquo_lineage`, and `tyrant_crown`.

Lady Macbeth’s four endings are reached by preventing regicide, confessing, seeking reconciliation, or escaping Dunsinane. Banquo’s survival ending requires escaping or fighting through the ambush; his lineage ending requires sacrificing himself so Fleance escapes. Macduff’s victory ending follows a direct challenge or protecting the city; the trial ending requires offering Macbeth a final surrender. All terminal scenes carry an ending ID, are completed by the deterministic engine, and return no available choices.

## Frontend

Character selection is presented as four campaign cards with a title, introduction, central conflict, and objective. The selected campaign’s authored opening is shown. Gameplay displays the campaign title, scene and source label, character status, relationships, knowledge, history, legal decisions, and ending status. The local game library shows each saved campaign and resumes the same game ID. Lady Macbeth’s status panel includes her psychological dimensions. The existing parchment visual language and responsive component layout remain in use.

## Save compatibility

No destructive migration is needed. Pydantic’s default for missing `campaign_id` and new state dimensions safely hydrates older JSON saves. SQLite tables, user_version, IDs, existing revision numbers, and separately persisted event rows do not change. New game state JSON stores its campaign ID from creation; resume reads that ID rather than inferring it from a scene.

## Test results

Campaign tests also start all four fresh games together and assert four different campaign IDs, opening scenes, opening narrations, and first-decision sets. A two-save narration test verifies Macbeth’s private prophecy decision does not enter Banquo’s state, history, or prompt. Other coverage includes protagonist-to-campaign authorization, persistence, legacy defaults, route boundaries, endings, Lady Macbeth’s alternate outcomes, Banquo’s survival/death and Fleance outcome, Macduff’s family outcomes, and Macbeth’s suspicion-gated Banquo plot. The graph tests validate each inventory and route reachability.

- Python: `pytest -q --basetemp .pytest-tmp\\acceptance-full --tb=short` — **135 passed**, 82% coverage, one upstream pytest deprecation warning.
- Frontend unit tests: `npm test` — **27 passed** across 5 files.
- TypeScript: `npm run typecheck` — passed for app and Playwright fixtures.
- Production build: `npm run build` — passed; JavaScript bundle 257.72 kB (78.95 kB gzip).
- Mocked Playwright: `npm run test:e2e` — **9 passed**, including responsive desktop/tablet/mobile layouts, selection, saves, and resume.
- Local Ollama Playwright smoke: not run because `http://127.0.0.1:11434/api/tags` was unreachable. `ollama list` also timed out while the local CLI could not access its application log. No model was downloaded and no production database was used.

## Known limitations

Each save is an independent timeline; decisions in one saved campaign do not mutate another save. The new supporting arcs are intentionally compact compared with Macbeth’s 35-scene route. Lady Macbeth’s alternate reconciliation ending is a negotiated narrative outcome rather than a new diplomatic subgraph. Local Ollama remains optional for deterministic choice execution and save/resume.
