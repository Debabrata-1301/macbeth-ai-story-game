# Architecture documentation

These diagrams describe the implementation in `src/macbeth_game/` and the authored campaign content in `content/macbeth/`. They show the local development topology; they do not describe a public or production deployment.

| Document | Focus |
| --- | --- |
| [System architecture](system_architecture.md) | Application components, ownership of game state, and data flow |
| [Narrative generation](narrative_generation.md) | The implemented choice-to-narration request sequence |
| [Campaign flow](campaign_flow.md) | Four separate campaign timelines, transitions, and endings |
| [Local deployment](local_deployment.md) | Browser, backend, SQLite, Ollama, and FAISS on one machine |

The central boundary is that the deterministic game service authorizes choices and persists transitions. The language model writes validated narration from a bounded view of the resulting state. It cannot advance the game.

The project requires a locally supplied, authorized Macbeth source PDF to build its RAG index. The PDF and generated chunks/index are intentionally excluded from publication pending rights verification. See the [root README](../../README.md) for setup, test results, and limitations.
