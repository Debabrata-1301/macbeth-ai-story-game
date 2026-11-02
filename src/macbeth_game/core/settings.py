"""Typed application settings; loading settings does not contact external services."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Macbeth AI Story Game"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    llm_provider: Literal["ollama"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    generation_model: str = "qwen3:4b"
    generation_think: bool = False
    generation_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    generation_max_tokens: int = Field(default=768, ge=1, le=8192)
    generation_context_window: int = Field(default=4096, ge=512, le=131072)
    ollama_keep_alive: str = Field(default="5m", min_length=1, max_length=32)
    narrative_max_prompt_chars: int = Field(default=12000, ge=4000, le=100000)
    narrative_max_words: int = Field(default=180, ge=60, le=500)
    embedding_model: str = "nomic-embed-text"
    content_dir: Path = Path("content/macbeth")
    pdf_source_path: Path = Path("content/macbeth/source/macbeth_original.pdf")
    data_dir: Path = Path("data")
    sqlite_path: Path = Path("data/macbeth.sqlite3")
    faiss_index_dir: Path = Path("data/faiss")
    rag_metadata_path: Path = Path("data/faiss/metadata.json")
    rag_chunks_path: Path = Path("data/macbeth/chunks.json")
    rag_chunk_size: int = Field(default=1200, ge=200, le=10000)
    rag_chunk_overlap: int = Field(default=180, ge=0, le=5000)
    rag_default_top_k: int = Field(default=4, ge=1, le=50)
    narrative_retrieval_top_k: int = Field(default=4, ge=1, le=4)
    rag_min_relevance: float = Field(default=0.35, ge=-1.0, le=1.0)
    ollama_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    rag_scanned_page_char_threshold: int = Field(default=40, ge=0)

    @field_validator("api_prefix")
    @classmethod
    def normalize_api_prefix(cls, value: str) -> str:
        value = "/" + value.strip("/")
        return value if value != "/" else ""

    @field_validator("ollama_keep_alive")
    @classmethod
    def normalize_keep_alive(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("ollama_keep_alive must not be blank")
        return value

    @model_validator(mode="after")
    def validate_rag_chunking(self):
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("rag_chunk_overlap must be smaller than rag_chunk_size")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
