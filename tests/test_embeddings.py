import json
import logging

import pytest

import embeddings
from doubt_solver import (
    cosine_similarity,
    rank_pages,
    ensure_user_pdfs_indexed,
    EMBEDDING_MODEL,
)


# ---------------------------------------------------------------------------
# Fake google.genai client (no live API calls, no real key needed)
# ---------------------------------------------------------------------------
class FakeValues:
    def __init__(self, values):
        self.values = values


class FakeEmbeddingResult:
    def __init__(self, values):
        self.embeddings = [FakeValues(values)]


class FakeModels:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def embed_content(self, model, contents, **kwargs):
        self.calls.append({"model": model, "contents": contents, **kwargs})
        if isinstance(self._response, Exception):
            raise self._response
        return FakeEmbeddingResult(self._response)


class FakeClient:
    def __init__(self, response):
        self.models = FakeModels(response)


@pytest.fixture
def mock_client(monkeypatch):
    fake = FakeClient([0.1, -0.2, 0.3, 0.5])
    monkeypatch.setattr(embeddings, "_client", fake)
    return fake


# ---------------------------------------------------------------------------
# Test A - embedding generation returns a non-empty numeric vector
# ---------------------------------------------------------------------------
def test_embedding_generation_returns_numeric_vector(mock_client):
    text = (
        "Photosynthesis is the process by which plants "
        "convert light energy into chemical energy."
    )
    vec = embeddings.get_embedding(text)
    assert vec is not None
    assert len(vec) > 0
    assert all(isinstance(v, float) for v in vec)


# ---------------------------------------------------------------------------
# Test B - query embedding
# ---------------------------------------------------------------------------
def test_query_embedding_returns_numeric_vector(mock_client):
    text = "How do plants make food using sunlight?"
    vec = embeddings.get_embedding(text, is_query=True)
    assert vec is not None
    assert len(vec) > 0
    assert all(isinstance(v, float) for v in vec)


# ---------------------------------------------------------------------------
# Test C - semantic similarity (relative ranking, not hardcoded scores)
# ---------------------------------------------------------------------------
def test_semantic_ranking_prefers_related_document(mock_client):
    query = "How do plants make food using sunlight?"
    related = "Plants use sunlight, carbon dioxide and water to produce glucose."
    unrelated = "Newton's laws describe the relationship between force and motion."

    q_emb = embeddings.get_embedding(query, is_query=True)
    related_emb = embeddings.get_embedding(related)
    unrelated_emb = embeddings.get_embedding(unrelated)
    assert q_emb is not None and related_emb is not None and unrelated_emb is not None

    # Deterministic semantic vectors (mocked model) - the related document
    # shares semantic direction with the query.
    related_vec = [1.0, 0.1, 0.05]
    unrelated_vec = [-0.3, 0.8, 0.4]
    q_vec = [1.0, 0.05, 0.02]

    pages = [
        {"embedding": json.dumps(unrelated_vec), "page_text": unrelated},
        {"embedding": json.dumps(related_vec), "page_text": related},
    ]
    ranked = rank_pages(pages, query, q_vec)
    top_text = ranked[0][1]["page_text"]
    assert top_text == related

    rel_score = cosine_similarity(related_vec, q_vec)
    unrel_score = cosine_similarity(unrelated_vec, q_vec)
    assert rel_score > unrel_score


def test_cosine_similarity_edge_cases():
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0
    assert cosine_similarity(None, [1.0]) == 0.0


# ---------------------------------------------------------------------------
# Test D - missing embedding does not crash; keyword fallback is used
# ---------------------------------------------------------------------------
def test_missing_embedding_does_not_crash():
    pages = [
        {"embedding": None, "page_text": "Plants use sunlight to make glucose."},
        # Semantic vector points away from the query (cosine <= 0), so this page
        # falls back to keyword scoring and loses to the keyword match below.
        {"embedding": json.dumps([1.0, 0.0, 0.0]), "page_text": "Newton's laws of motion."},
    ]
    ranked = rank_pages(pages, "plants sunlight food", [0.0, 1.0, 0.0])
    assert len(ranked) == 2
    assert ranked[0][1]["page_text"] == "Plants use sunlight to make glucose."


def test_malformed_embedding_does_not_crash():
    pages = [
        {"embedding": "{not valid json", "page_text": "Plants make food from sunlight."},
    ]
    ranked = rank_pages(pages, "plants food", [1.0, 0.0])
    assert len(ranked) == 1
    assert ranked[0][0] > 0.0  # keyword fallback still produced a score


# ---------------------------------------------------------------------------
# Test E - API failure: no crash, no key leak, clear log, fallback works
# ---------------------------------------------------------------------------
def test_api_failure_logs_clearly_without_key(monkeypatch, caplog):
    fake = FakeClient(RuntimeError("embedding service unavailable"))
    monkeypatch.setattr(embeddings, "_client", fake)

    with caplog.at_level(logging.ERROR, logger="embeddings"):
        vec = embeddings.get_embedding("How do plants make food?")

    assert vec is None
    assert "embedding service unavailable" in caplog.text
    assert "gemini-embedding-2" in caplog.text
    assert "GEMINI_API_KEY" not in caplog.text
    assert "YOUR_NEW_GEMINI_API_KEY" not in caplog.text


def test_api_failure_falls_back_to_keyword_ranking():
    query = "How do plants make food using sunlight?"
    pages = [
        {"embedding": None, "page_text": "Plants use sunlight to make glucose."},
        {"embedding": None, "page_text": "Newton's laws of motion."},
    ]
    # query_embedding None simulates an API failure for the query too
    ranked = rank_pages(pages, query, None)
    assert ranked[0][1]["page_text"] == "Plants use sunlight to make glucose."


def test_embed_content_called_with_new_model_and_config(mock_client):
    embeddings.get_embedding("hello", is_query=True)
    call = mock_client.models.calls[0]
    assert call["model"] == "gemini-embedding-2"
    assert "models/text-embedding-004" not in call["model"]
    assert "task_type" not in call
    cfg = call.get("config")
    assert cfg is not None
    assert cfg.output_dimensionality == embeddings.EMBEDDING_DIMENSIONS


def test_empty_text_returns_none(mock_client):
    assert embeddings.get_embedding("   ") is None
    assert embeddings.get_embedding(None) is None


# ---------------------------------------------------------------------------
# Database migration: stale embeddings invalidated and re-embedded
# ---------------------------------------------------------------------------
def test_stale_embedding_invalidated_and_reindexed(monkeypatch):
    from database import get_db

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO uploaded_pdfs "
        "(user_id, course, pdf_name, file_path, upload_time, pdf_type, total_pages, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (1, "GATE", "notes.pdf", "unused.pdf", "2026-01-01 10:00:00", "Digital", 1, "Processed"),
    )
    pdf_id = cur.lastrowid
    cur.execute(
        "INSERT INTO uploaded_pdf_pages "
        "(pdf_id, user_id, page_number, page_text, embedding, embedding_model) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (pdf_id, 1, 1, "Plants use sunlight to make glucose.", "[0.1, 0.2]", "text-embedding-004"),
    )
    page_id = cur.lastrowid
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "doubt_solver.get_embedding",
        lambda text, is_query=False: [0.3, 0.4, 0.5],
    )

    ensure_user_pdfs_indexed(1)

    conn = get_db()
    row = conn.execute(
        "SELECT embedding, embedding_model FROM uploaded_pdf_pages WHERE id=?",
        (page_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["embedding_model"] == EMBEDDING_MODEL
    assert json.loads(row["embedding"]) == [0.3, 0.4, 0.5]
