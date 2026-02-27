from typing import Optional

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from common.core.config import settings

_embedding_model: dict[str, Optional[Embeddings]] = {}


class EmbeddingModelCache:

    @staticmethod
    def _new_instance() -> Embeddings:
        kwargs: dict = {
            "model": settings.EMBEDDING_OPENAI_MODEL,
        }
        if settings.EMBEDDING_OPENAI_API_KEY:
            kwargs["api_key"] = settings.EMBEDDING_OPENAI_API_KEY
        if settings.EMBEDDING_OPENAI_BASE_URL:
            kwargs["base_url"] = settings.EMBEDDING_OPENAI_BASE_URL
        return OpenAIEmbeddings(**kwargs)

    @staticmethod
    def get_model(key: str = settings.EMBEDDING_OPENAI_MODEL) -> Embeddings:
        model_instance = _embedding_model.get(key)
        if model_instance is None:
            model_instance = EmbeddingModelCache._new_instance()
            _embedding_model[key] = model_instance
        return model_instance
