"""Tests that Ask AI and study-query generation go through llm.generate
(Groq -> Gemini fallback) instead of raw Groq clients.
"""
import practice
import study_resources
import llm


def test_ask_ai_reply_uses_shared_llm(monkeypatch):
    seen = {}

    def stub(prompt, temperature=0.7, max_tokens=None):
        seen["prompt"] = prompt
        seen["temperature"] = temperature
        return "Use the dashboard."

    monkeypatch.setattr(practice, "generate", stub)
    reply = practice.generate_ask_ai_reply(
        "How do I track progress?",
        [{"q": "Hi", "a": "Hello!"}],
    )
    assert reply == "Use the dashboard."
    assert "How do I track progress?" in seen["prompt"]
    assert "Hi" in seen["prompt"] and "Hello!" in seen["prompt"]
    assert "Adaptive Learning" in seen["prompt"]
    assert seen["temperature"] == 0.6


def test_ask_ai_reply_empty_history(monkeypatch):
    monkeypatch.setattr(
        practice, "generate", lambda *a, **k: "  Trim me  "
    )
    assert practice.generate_ask_ai_reply("Hello?", []) == "Trim me"


def test_study_query_uses_shared_llm(monkeypatch):
    import study_resources as sr

    seen = {}

    def stub(prompt):
        seen["prompt"] = prompt
        return "GATE compiler NPTEL playlist"

    monkeypatch.setattr(sr, "_generate_search_query", stub)
    q = sr._build_search_query("GATE", "compiler")
    assert q == "GATE compiler NPTEL playlist"
    assert "Compiler" in seen["prompt"]


def test_ask_ai_empty_reply_flashes_warning(monkeypatch):
    from tests.conftest import make_user, login, set_csrf

    uid = make_user("ask_empty@example.com")
    c = __import__("Main_page").app.test_client()
    login(c, "ask_empty@example.com", uid, "tok")
    set_csrf(c, "tok")
    monkeypatch.setattr(practice, "generate_ask_ai_reply", lambda *a, **k: "   ")
    html = c.post(
        "/practice/ask-ai", data={"question": "Hi?", "csrf_token": "tok"}
    ).get_data(as_text=True)
    assert "empty answer" in html


def test_study_query_falls_back_on_llm_failure(monkeypatch):
    def bomb(*a, **k):
        raise RuntimeError("both providers down")

    monkeypatch.setattr(llm, "generate", bomb)
    q = study_resources._build_search_query("GATE", "compiler")
    assert q == "GATE Compiler Design tutorial playlist"
