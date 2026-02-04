"""Semantic deduplication for playbook bullets using Ollama."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, TYPE_CHECKING
from appworld_experiment.base_ace.deduplication import Deduplicator

if TYPE_CHECKING:
    from appworld_experiment.experiment_logger import ExperimentLogger

# Fallback logger for when ExperimentLogger is not provided
_fallback_logger = logging.getLogger(__name__)

try:
    import ollama
except ImportError:
    ollama = None  # type: ignore[assignment]

try:  # Optional fallback to sentence-transformers
    from sklearn.metrics.pairwise import cosine_similarity  # type: ignore
except ImportError:  # pragma: no cover - fallback logic used
    cosine_similarity = None  # type: ignore[assignment]


class OllamaDeduplicator(Deduplicator):
    """Finds semantically similar bullets using Ollama embeddings API."""

    def __init__(
        self,
        model_name: str = "qwen3-embedding",
        similarity_threshold: float = 0.8,
        base_url: str = "http://localhost:11434",
        logger: Optional["ExperimentLogger"] = None,
    ) -> None:
        """
        Initialize Ollama-based deduplicator.

        Args:
            model_name: Ollama embedding model name (e.g., "qwen3-embedding", "nomic-embed-text")
            similarity_threshold: Cosine similarity threshold for duplicates (0-1)
            base_url: Ollama API base URL
            logger: Optional ExperimentLogger instance for structured logging
        """
        if not ollama:
            raise ImportError(
                "ollama is required for OllamaDeduplicator. Install with:\n"
                "  pip install ollama\n"
                "or:\n"
                "  uv sync"
            )

        self._model_name = model_name
        self._threshold = similarity_threshold
        self._client = ollama.Client(host=base_url)
        self._logger = logger

        self._log_info(f"Initialized OllamaDeduplicator with model '{model_name}' (threshold={similarity_threshold})")

    def _log_info(self, message: str) -> None:
        """Log info message using ExperimentLogger or fallback to standard logging."""
        if self._logger:
            self._logger.info(message)
        else:
            _fallback_logger.info(message)

    def _log_debug(self, message: str) -> None:
        """Log debug message using ExperimentLogger or fallback to standard logging."""
        if self._logger:
            self._logger.debug(message)
        else:
            _fallback_logger.debug(message)

    def _get_embeddings(self, texts: List[str]):
        """Get embeddings for a list of texts using Ollama."""
        if not self._client:
            raise RuntimeError("Ollama client is not initialized.")

        response = self._client.embed(
            model=self._model_name,
            input=texts,
        )
        embeddings = response['embeddings']
        return embeddings
    
    def find_duplicates(
        self,
        new_bullets: Dict[str, str],
        existing_bullets: Dict[str, str],
    ) -> List[str]:
        """
        Identifies new bullets that are semantically similar to existing ones.

        Args:
            new_bullets: A dictionary of {bullet_id: content} for new bullets.
            existing_bullets: A dictionary of {bullet_id: content} for existing bullets.

        Returns:
            A list of bullet IDs from `new_bullets` that are duplicates.
        """
        self._log_info(f"Finding duplicates among {len(new_bullets)} new bullets against {len(existing_bullets)} existing bullets")
        if not new_bullets or not existing_bullets:
            return []

        new_contents = list(new_bullets.values())
        existing_contents = list(existing_bullets.values())
        new_ids = list(new_bullets.keys())

        if self._client and cosine_similarity:
            self._log_debug("Using Ollama embeddings with cosine similarity for deduplication")
            new_embeddings = self._get_embeddings(new_contents)
            existing_embeddings = self._get_embeddings(existing_contents)
            similarities = cosine_similarity(new_embeddings, existing_embeddings)

            duplicate_ids = []
            for i, similarity_row in enumerate(similarities):
                if any(similarity > self._threshold for similarity in similarity_row):
                    duplicate_ids.append(new_ids[i])

            self._log_info(f"Found {len(duplicate_ids)} duplicates out of {len(new_bullets)} new bullets")
            return duplicate_ids

        # Fallback: simple exact-match/substring heuristic (keeps tests lightweight)
        self._log_debug("Using fallback substring matching for deduplication")
        duplicates: List[str] = []
        existing_lower = [text.lower() for text in existing_contents]
        for idx, content in zip(new_ids, new_contents):
            normalized = content.lower()
            if any(normalized == other or normalized in other or other in normalized for other in existing_lower):
                duplicates.append(idx)

        self._log_info(f"Found {len(duplicates)} duplicates out of {len(new_bullets)} new bullets (fallback)")
        return duplicates
