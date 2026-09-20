import os
import logging

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Model is configurable via GROQ_MODEL. The key is never logged anywhere
# in this module.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()

# Fallback chat model (Google Gemini, free tier). Used automatically when
# Groq is unreachable or rejects the key. Override via GEMINI_MODEL, e.g.
# gemini-3.5-flash-lite for the cheapest quota footprint.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

_client = None
_gemini_client = None


class GroqAuthError(Exception):
    """Raised when Groq rejects the request for authentication reasons.

    This is a distinct, non-transient failure (bad/revoked/expired API key).
    It subclasses Exception so existing generic handlers keep working, but
    callers can catch it explicitly to show a clear "key invalid" message
    instead of a misleading "try again" one. Retrying is pointless.
    """


class GroqConnectionError(Exception):
    """Raised when the Groq API host cannot be reached at all.

    Typical on sandboxed hosts (e.g. PythonAnywhere free accounts, where
    non-whitelisted outbound hosts are blocked by the proxy) or when the
    server has no internet/DNS. Retrying within the same request only adds
    timeout delays, so callers should fail fast with a clear message.
    """


class GeminiQuotaError(Exception):
    """Raised when Gemini answers with a rate-limit/quota error (HTTP 429).

    The free tier resets daily (midnight Pacific). Callers should surface a
    "try again later" message instead of retrying in a loop.
    """


class GeminiError(Exception):
    """Raised when the Gemini fallback fails for a non-quota reason.

    Unlike quota exhaustion, these failures may be transient (e.g. HTTP 503
    overload), so callers should keep their normal retry behaviour.
    """


def _get_client():
    """Return a lazily-initialised Groq client (OpenAI-compatible)."""
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
        )
    return _client


def generate(prompt, temperature=0.7, max_tokens=None):
    """Send a single-turn chat prompt to Groq and return the assistant text.

    If Groq is unreachable or rejects the key, automatically falls back to
    Gemini (free tier) so hosted environments without Groq access keep
    working. If both providers fail, the Groq error propagates unless the
    failure is a Gemini quota exhaustion (GeminiQuotaError).
    """
    try:
        return _generate_groq(prompt, temperature, max_tokens)
    except (GroqAuthError, GroqConnectionError) as groq_exc:
        logger.warning(
            "LLM: Groq unavailable (%s); trying Gemini fallback.",
            type(groq_exc).__name__,
        )
        try:
            return _generate_gemini(prompt, temperature, max_tokens)
        except GeminiQuotaError:
            raise
        except Exception as gemini_exc:
            # Non-quota Gemini failures may be transient (e.g. 503 overload),
            # so raise a retryable error carrying the (redacted) reason
            # instead of the misleading Groq-connection message.
            reason = str(gemini_exc)[:200]
            logger.error("LLM: Gemini fallback also failed: %s", reason)
            raise GeminiError(
                "AI backup service failed (%s). Please try again." % reason
            ) from groq_exc


def _generate_groq(prompt, temperature=0.7, max_tokens=None):
    """Single Groq attempt; classifies auth vs connection failures."""
    kwargs = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    try:
        response = _get_client().chat.completions.create(**kwargs)
    except Exception as exc:
        if _is_auth_error(exc):
            raise GroqAuthError(
                "Groq rejected the API key (invalid, expired, or revoked). "
                "Set a valid GROQ_API_KEY in .env and restart the app."
            ) from exc
        if _is_connection_error(exc):
            raise GroqConnectionError(
                "Could not reach the Groq API from this server "
                "(network/DNS/proxy block)."
            ) from exc
        raise
    content = response.choices[0].message.content
    return (content or "").strip()


def _get_gemini_client():
    """Return a lazily-initialised Gemini client.

    Raises RuntimeError when no usable key is configured so the caller can
    fall through to the original Groq error.
    """
    global _gemini_client
    if _gemini_client is None:
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key or api_key.startswith("YOUR_"):
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def _generate_gemini(prompt, temperature=0.7, max_tokens=None):
    """Single Gemini attempt with the same (prompt, temperature) contract."""
    from google.genai import types

    config = types.GenerateContentConfig(temperature=temperature)
    if max_tokens is not None:
        config.max_output_tokens = max_tokens
    try:
        response = _get_gemini_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config,
        )
    except Exception as exc:
        if _is_quota_error(exc):
            raise GeminiQuotaError(
                "Gemini free-tier quota is exhausted (resets midnight "
                "Pacific). Try again later."
            ) from exc
        raise
    return (getattr(response, "text", "") or "").strip()


def _is_auth_error(exc):
    """True if the exception looks like an auth failure (HTTP 401)."""
    status = getattr(exc, "status_code", None)
    if status == 401:
        return True
    text = str(exc).lower()
    return "invalid_api_key" in text or (
        "401" in text and ("unauthorized" in text or "authentication" in text)
    )


def _is_connection_error(exc):
    """True if the exception looks like the host is unreachable.

    Covers DNS failures, refused/reset connections, proxy blocks (such as
    PythonAnywhere's free-tier outbound whitelist), SSL handshake failures,
    and timeouts — all of which surface through httpx/httpcore wording.
    """
    text = (
        str(exc) + " " + str(getattr(exc, "body", "") or "")
    ).lower()
    # NOTE: plain timeouts are deliberately NOT listed here. A timeout on an
    # otherwise reachable host is transient and deserves the normal retry
    # path; the markers below mean the host itself cannot be reached.
    markers = (
        "failed to establish a new connection",
        "name or service not known",
        "temporary failure in name resolution",
        "connection refused",
        "connection reset",
        "connection aborted",
        "network is unreachable",
        "proxyerror",
        "proxy error",
        "tunnel connection failed",
        "proxy authentication required",
        "ssLError",
        "ssl:",
        "certificate verify failed",
        # Cloudflare edge blocks (e.g. error 1010 IP ban as seen from
        # shared-proxy hosts): the request reaches the edge but is refused
        # before the API ever sees it. Retrying is pointless.
        "error code: 1010",
        "cloudflare",
    )
    return any(marker in text for marker in markers)


def _is_quota_error(exc):
    """True if the exception is a rate-limit/quota exhaustion (HTTP 429)."""
    if getattr(exc, "status_code", None) == 429:
        return True
    text = str(exc).lower()
    return "429" in text and (
        "resource_exhausted" in text or "quota" in text or "rate" in text
    )