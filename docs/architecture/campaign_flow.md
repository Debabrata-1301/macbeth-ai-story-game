# Campaign and game-state flow

The authored catalogs contain 60 scene definitions, 107 choice definitions, and 18 distinct ending IDs. Macbeth's campaign uses the 35-scene main catalog; Lady Macbeth, Banquo, and Macduff use their own authored campaign scenes. Each started game belongs to exactly one campaign.

```mermaid
flowchart TD
    Player["Player selects a character"] --> Select{"Campaign"}

    Select --> Macbeth["Macbeth<br/>35 authored scenes"]
    Select --> Lady["Lady Macbeth<br/>11 authored scenes"]
    Select --> Banquo["Banquo<br/>7 authored scenes"]
    Select --> Macduff["Macduff<br/>7 authored scenes"]

    Macbeth --> Start["Start a game with a new game_id"]
    Lady --> Start
    Banquo --> Start
    Macduff --> Start

    Start --> State["Initialize campaign-scoped GameState"]
    State --> Scene["Current authored scene"]
    Scene --> Choices["Offer choices for this scene"]
    Choices --> Check["Evaluate choice conditions against saved state"]
    Check -->|"Unavailable or invalid"| Choices
    Check -->|"Authorized choice"| Transition["Apply deterministic transition"]

    Transition --> Effects["Update destination, flags, character psychology, relationships, knowledge, memories, commitments, and event history"]
    Effects --> Persist["Commit state and ordered events to SQLite"]
    Persist --> Ending{"Campaign complete?"}
    Ending -->|"No"| Scene
    Ending -->|"Yes"| Terminal["Persist terminal status and ending_id"]

    Persist -.->|separate response generation| Narration["Generate character-specific narration"]
    Narration -.->|returned to client; not saved as game state| Player

    classDef persistent fill:#e8f2ff,stroke:#3567a8,color:#14263d;
    class State,Effects,Persist,Terminal persistent;
```

Each campaign creates a separate game ID and SQLite record. Campaigns can share the authored world and character definitions, but their saves, event histories, knowledge, relationships, memories, and outcomes are not synchronized across game IDs. Within a save, authored effects can change multiple characters' state.

The persistent state includes the selected campaign, current scene, flags, status and ending, per-character psychology and known facts, directional relationships, memories, promises/secrets, and ordered events. Choice availability and scene progression are determined by authored content and deterministic rules.

Narration is generated from the saved state after a transition. It may vary between requests, but it cannot select a destination, alter a flag, authorize a choice, or replace the saved event history. Retrying narration does not replay the choice.
