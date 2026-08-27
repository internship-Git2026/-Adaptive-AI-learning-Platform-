import os
import logging

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Current supported Google embedding model.
# NOTE: gemini-embedding-2 does NOT accept a task_type / taskType parameter
# (unlike the retired models/text-embedding-004 or gemini-embedding-001), so
# the old embed call with task_type=RETRIEVAL_DOCUMENT/QUERY must not be used.
EMBEDDING_MODEL = "gemini-embedding-2"

# gemini-embedding-2 outputs 3072 dimensions by default but, thanks to
# Matryoshka Representation Learning (MRL), supports 128-3072. 768 is a
# Google-recommended size: smaller to store, and the model auto-normalizes
# truncated vectors so cosine similarity still works as-is.
EMBEDDING_DIMENSIONS = 768

try:
    _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception as exc:  # pragma: no cover - defensive; key is validated at app start
    logger.error("Embedding client could not be created: %s", exc)
    _client = None


def get_embedding(text, is_query=False):
    """Return the text embedding as a list of floats, or None if unavailable.

    `is_query` is kept for compatibility with the old Doubt Solver call sites.
    gemini-embedding-2 needs no task type, so it is intentionally unused.

    Never raises and never logs the API key: failures return None so callers
    can fall back to keyword search.
    """
    if not text or not text.strip():
        logger.warning("Embedding skipped: empty text provided.")
        return None

    if _client is None:
        logger.error(
            "Embedding unavailable: Gemini client could not be created "
            "(check that GEMINI_API_KEY is configured in .env)."
        )
        return None

    try:
        result = _client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                output_dimensionality=EMBEDDING_DIMENSIONS
            ),
        )
        if not result.embeddings:
            logger.error("Embedding generation failed (%s): API returned no embeddings.", EMBEDDING_MODEL)
            return None

        values = list(result.embeddings[0].values)
        if not values:
            logger.error("Embedding generation failed (%s): API returned an empty vector.", EMBEDDING_MODEL)
            return None
        if not any(v != 0.0 for v in values):
            logger.error("Embedding generation failed (%s): API returned an all-zero vector.", EMBEDDING_MODEL)
            return None
        return values
    except Exception as exc:
        # The API key is never included in this message.
        logger.error("Embedding generation failed (%s): %s", EMBEDDING_MODEL, exc)
        return None
