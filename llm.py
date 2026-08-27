import os
import logging

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Model is configurable via GROQ_MODEL. The default (llama-3.3-70b-versatile)
# is a strong, fast, widely-available Groq model on the free tier. The key is
# never logged anywhere in this module.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()

_client = None


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

    Thread-safety: each of the app's two call sites constructs its own prompt
    and awaits the response synchronously, so a single shared client is fine.
    """
    kwargs = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    response = _get_client().chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    return (content or "").strip()