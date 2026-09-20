"""Tests for the Groq -> Gemini fallback in llm.generate.

All external clients are stubbed; no network calls are made.
"""
import pytest

import llm
from llm import (
    GeminiQuotaError,
    GroqAuthError,
    GroqConnectionError,
    _is_auth_error,
    _is_connection_error,
    _is_quota_error,
)


class Fake403(Exception):
    status_code = 403


def test_cloudflare_1010_block_is_connection_error():
    exc = Fake403("Error code: 403 - b'error code: 1010\\n'")
    assert _is_connection_error(exc) is True
    assert _is_auth_error(exc) is False


def test_401_is_auth_error_not_connection():
    class Fake401(Exception):
        status_code = 401
    exc = Fake401("Invalid API Key")
    assert _is_auth_error(exc) is True
    assert _is_connection_error(exc) is False


def test_quota_detection():
    class Fake429(Exception):
        status_code = 429
    assert _is_quota_error(Fake429("RESOURCE_EXHAUSTED quota exceeded")) is True
    assert _is_quota_error(ValueError("plain failure")) is False


def test_groq_failure_falls_back_to_gemini(monkeypatch):
    def dead_groq(*a, **k):
        raise GroqConnectionError("blocked")
    monkeypatch.setattr(llm, "_generate_groq", dead_groq)
    monkeypatch.setattr(llm, "_generate_gemini", lambda *a, **k: "gemini text")
    assert llm.generate("hello") == "gemini text"


def test_gemini_unconfigured_raises_retryable_error(monkeypatch):
    from llm import GeminiError
    def dead_groq(*a, **k):
        raise GroqAuthError("bad key")
    def no_gemini(*a, **k):
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    monkeypatch.setattr(llm, "_generate_groq", dead_groq)
    monkeypatch.setattr(llm, "_generate_gemini", no_gemini)
    with pytest.raises(GeminiError):
        llm.generate("hello")


def test_gemini_quota_propagates(monkeypatch):
    def dead_groq(*a, **k):
        raise GroqConnectionError("blocked")
    def quota(*a, **k):
        raise GeminiQuotaError("exhausted")
    monkeypatch.setattr(llm, "_generate_groq", dead_groq)
    monkeypatch.setattr(llm, "_generate_gemini", quota)
    with pytest.raises(GeminiQuotaError):
        llm.generate("hello")


def test_groq_success_never_touches_gemini(monkeypatch):
    def bomb(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("gemini should not run when groq works")
    monkeypatch.setattr(llm, "_generate_groq", lambda *a, **k: "groq text")
    monkeypatch.setattr(llm, "_generate_gemini", bomb)
    assert llm.generate("hello") == "groq text"
