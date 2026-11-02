# Local deployment

The documented setup runs the browser, frontend development server, FastAPI application, SQLite file, FAISS files, and Ollama on one user's computer. The development servers bind to loopback. This is a local topology, not a supported public/shared-network deployment.

```mermaid
flowchart LR
    subgraph machine["One local computer"]
        Browser["Browser"]
        Vite["Vite dev server<br/>127.0.0.1:5173"]
        API["FastAPI<br/>127.0.0.1:8000"]
        Services["Game and narrative services"]
        Retriever["RAGRetriever"]
        Embedder["OllamaEmbeddingClient"]
        Provider["OllamaProvider"]
        SQLite[("data/macbeth.sqlite3<br/>game state and events")]
        Index[("data/faiss/<br/>FAISS index and metadata")]
        Ollama["Ollama<br/>http://localhost:11434"]
        Generate["qwen3:4b<br/>narration"]
        Embed["nomic-embed-text<br/>query embeddings"]

        Browser <-->|local page| Vite
        Vite -->|/api proxy| API
        API --> Services
        Services <-->|read and commit saves| SQLite
        Services --> Retriever
        Retriever --> Index
        Retriever --> Embedder
        Embedder --> Ollama
        Services --> Provider
        Provider --> Ollama
        Ollama --> Generate
        Ollama --> Embed
    end
```

The backend's default settings use SQLite at `data/macbeth.sqlite3`, the FAISS index under `data/faiss/`, and Ollama at `http://localhost:11434`. `.env` can override these settings. The default Vite proxy forwards `/api` requests to `127.0.0.1:8000`.

The backend does not download models, extract PDFs, build an index, or contact Ollama during startup. Model installation and RAG index creation are explicit local steps. The source PDF and generated chunks/index/metadata are not distributed. No cloud API is required by this local configuration.

The API has no authentication or per-user save ownership. Keep it bound to loopback; public and shared-network exposure is unsupported. See the [README limitations](../../README.md#limitations-and-security).
