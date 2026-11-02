"""FastAPI application factory and ASGI entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from macbeth_game.api.routes import router
from macbeth_game.core.logging import configure_logging
from macbeth_game.core.settings import Settings, get_settings
from macbeth_game.llm.inference import InferenceGate
from macbeth_game.llm.ollama import OllamaProvider
from macbeth_game.llm.prompts import NarrativePromptBuilder
from macbeth_game.rag.embeddings import OllamaEmbeddingClient
from macbeth_game.rag.retriever import RAGRetriever
from macbeth_game.rag.vector_store import FAISSVectorStore
from macbeth_game.repositories.game_repository import ConcurrentUpdate, PersistenceError
from macbeth_game.repositories.sqlite_repository import SQLiteGameRepository
from macbeth_game.services.game_service import GameService
from macbeth_game.services.gameplay_turn_service import GameplayTurnService
from macbeth_game.services.narrative_orchestrator import NarrativeOrchestrator


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    app_settings = settings or get_settings()
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # Validate content and initialize local storage when the application starts.
        repository = SQLiteGameRepository(app_settings.sqlite_path)
        application.state.game_service = GameService.from_directory(app_settings.content_dir, repository)
        inference_gate = InferenceGate()
        embedding_provider = OllamaEmbeddingClient(
            app_settings.ollama_base_url,
            app_settings.embedding_model,
            app_settings.ollama_timeout_seconds,
            keep_alive=app_settings.ollama_keep_alive,
            inference_gate=inference_gate,
        )
        vector_store = FAISSVectorStore(app_settings.faiss_index_dir, app_settings.rag_metadata_path)
        application.state.rag_retriever = RAGRetriever(
            embedding_provider, vector_store, minimum_relevance=app_settings.rag_min_relevance)
        application.state.rag_default_top_k = app_settings.rag_default_top_k
        llm_provider = OllamaProvider(
            app_settings.ollama_base_url,
            app_settings.generation_model,
            app_settings.ollama_timeout_seconds,
            context_window=app_settings.generation_context_window,
            keep_alive=app_settings.ollama_keep_alive,
            inference_gate=inference_gate,
            think=app_settings.generation_think,
        )
        application.state.llm_provider = llm_provider
        application.state.narrative_orchestrator = NarrativeOrchestrator(
            application.state.game_service,
            application.state.rag_retriever,
            llm_provider,
            app_settings,
            prompt_builder=NarrativePromptBuilder(
                max_prompt_chars=app_settings.narrative_max_prompt_chars
            ),
        )
        application.state.gameplay_turn_service = GameplayTurnService(
            application.state.game_service,
            application.state.narrative_orchestrator,
        )
        yield

    application = FastAPI(title=app_settings.app_name, lifespan=lifespan)

    @application.exception_handler(ConcurrentUpdate)
    async def concurrent_update_handler(_request, _exc):
        return JSONResponse(status_code=409, content={"detail": "Game changed concurrently; reload and retry."})

    @application.exception_handler(PersistenceError)
    async def persistence_error_handler(_request, _exc):
        return JSONResponse(status_code=503, content={"detail": "Game storage is temporarily unavailable."})
    application.include_router(router, prefix=app_settings.api_prefix)
    return application


app = create_app()
