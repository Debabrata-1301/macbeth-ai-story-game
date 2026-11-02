# Narrative generation sequence

The sequence below follows `GameplayTurnService.take_turn()` and `NarrativeOrchestrator.generate()`. The game transition is committed before retrieval or model generation begins.

```mermaid
sequenceDiagram
    autonumber
    actor Player
    participant UI as React frontend
    participant API as FastAPI routes
    participant Turn as GameplayTurnService
    participant Game as GameService and deterministic rules
    participant SQLite as SQLite repository
    participant Orch as NarrativeOrchestrator
    participant RAG as RAGRetriever
    participant Embed as OllamaEmbeddingClient
    participant FAISS as FAISS index
    participant Ollama as Local Ollama
    participant Provider as OllamaProvider
    participant Validator as NarrativeValidator

    Player->>UI: Select an offered choice
    UI->>API: POST /games/{id}/turns (choice_id, request_id)
    API->>Turn: take_turn(game_id, choice_id, request_id)
    Turn->>Game: Check current choice availability
    Game->>Game: Evaluate authored choice conditions

    alt Choice is invalid or unavailable
        Game-->>Turn: Reject choice; no state transition
        Turn-->>API: Choice error
        API-->>UI: Error response
    else Choice is authorized
        Turn->>Game: execute_choice_once(...)
        Game->>Game: Apply authored state effects and destination
        Game->>SQLite: Commit new state and ordered events
        SQLite-->>Game: Commit result
        Game-->>Turn: Persisted game snapshot and revision

        Note over Turn,SQLite: The choice is saved before any RAG or generation request.

        Turn->>Orch: Generate for the persisted current state
        Orch->>Game: Load state and event history
        Orch->>Game: Read engine-authorized available choices
        Orch->>Orch: Filter events and knowledge for the selected character
        Orch->>RAG: Retrieve for scene, character, and known context
        RAG->>Embed: Embed query
        Embed->>Ollama: Local embedding request with nomic-embed-text
        Ollama-->>Embed: Query embedding
        Embed-->>RAG: Query embedding
        RAG->>FAISS: Search local index and metadata
        FAISS-->>RAG: Ranked source passages with provenance
        RAG-->>Orch: Relevant passages
        Orch->>Orch: Build bounded prompt from scoped context and passages
        Orch->>Provider: Generate bounded prompt
        Provider->>Ollama: Local generation request with qwen3:4b
        Ollama-->>Provider: JSON response
        Provider-->>Orch: Raw model output
        Orch->>Validator: Validate response against context
        Validator->>Validator: Check schema, speakers, choices, citations, route consistency
        Validator-->>Orch: Validated narrative or validation error
        Orch-->>Turn: Narrative result
        Turn-->>API: Persisted state, available choices, narration/status
        API-->>UI: Turn response
    end

    opt Narration fails after the transition was saved
        Note over UI,SQLite: The choice remains committed; POST /games/{id}/narrative retries narration without replaying the choice.
    end
```

The orchestrator only includes event history the protagonist is allowed to know, along with that character's confirmed facts, relevant memories, commitments, relationships, and engine-authorized choices. It checks that the game revision has not changed while context is being assembled. Retrieved text is treated as untrusted reference material.

The validator accepts only authorized speaker IDs and the engine-supplied choice IDs. Source references must match retrieved passages. A narration response does not update SQLite or determine the next scene. A generation failure is returned as an API error alongside the already-persisted game state; `/games/{id}/narrative` retries narration without reapplying a choice.
