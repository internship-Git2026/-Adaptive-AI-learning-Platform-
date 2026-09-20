"""Dynamic study resource recommendations.

Uses Groq to generate a smart YouTube search query for each topic,
then hits the YouTube Data API to return real, working video links.

Flow:
    get_resources_for_topic(course, subject_key)
        → _build_search_query(course, subject_key)   # Groq generates query
        → _search_youtube(query)                      # YouTube API returns results
        → list of {title, url, source}
"""

import os
import logging
from functools import lru_cache

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_YT_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
_YT_BASE = "https://www.googleapis.com/youtube/v3/search"

# Cache results for 6 hours so we don't burn API quota on every page load.
# Key: (course, subject_key) → list of resource dicts
_cache = {}
_CACHE_TTL = 6 * 3600  # seconds


def _generate_search_query(prompt):
    """Generate a search query via the shared LLM layer.

    Goes through llm.generate so the Groq -> Gemini fallback applies;
    raises on failure so the caller can use its keyword fallback.
    """
    from llm import generate as llm_generate
    return llm_generate(prompt, temperature=0.3, max_tokens=60)


def _build_search_query(course, subject_key):
    """Ask Groq to produce a good YouTube search query for this topic."""
    from gate_course import GATE_SUBJECTS, NEET_SUBJECTS

    subjects = GATE_SUBJECTS if course == "GATE" else NEET_SUBJECTS
    subject_info = next((s for s in subjects if s["key"] == subject_key), None)
    if not subject_info:
        return f"{course} {subject_key} tutorial"

    prompt = f"""Generate a short YouTube search query (max 10 words) to find
the best free study playlist or tutorial video for:

Course: {course}
Subject: {subject_info['name']}
Topics: {subject_info['description']}

Return ONLY the search query text. No quotes, no explanation.
Example output: GATE data structures algorithms NPTEL playlist"""

    try:
        query = (_generate_search_query(prompt) or "").strip().strip('"').strip("'")
        if query:
            return query
    except Exception as exc:
        logger.warning("STUDY_RESOURCES: LLM query generation failed: %s", exc)

    # Fallback: simple keyword query
    return f"{course} {subject_info['name']} tutorial playlist"


def _search_youtube(query, max_results=3):
    """Search YouTube Data API and return list of {title, url, source}."""
    if not _YT_API_KEY:
        logger.warning("STUDY_RESOURCES: YOUTUBE_API_KEY not set")
        return []

    params = {
        "key": _YT_API_KEY,
        "q": query,
        "part": "snippet",
        "type": "video",
        "maxResults": max_results,
        "relevanceLanguage": "en",
        "videoDuration": "medium",  # 4-20 min videos
        "safeSearch": "strict",
    }

    try:
        resp = requests.get(_YT_BASE, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("STUDY_RESOURCES: YouTube API request failed: %s", exc)
        return []

    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId", "")
        if not video_id:
            continue
        title = snippet.get("title", "Untitled")
        channel = snippet.get("channelTitle", "")
        url = f"https://www.youtube.com/watch?v={video_id}"
        results.append({
            "title": title,
            "url": url,
            "source": channel or "YouTube",
        })

    return results


def get_resources_for_topic(course, subject_key):
    """Return curated study resources for a subject.

    Uses Groq to generate a search query, then YouTube API to find real videos.
    Results are cached for 6 hours.
    """
    import time

    cache_key = (course, subject_key)
    cached = _cache.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["data"]

    query = _build_search_query(course, subject_key)
    logger.info("STUDY_RESOURCES: course=%s key=%s query='%s'", course, subject_key, query)

    results = _search_youtube(query, max_results=3)

    _cache[cache_key] = {"data": results, "ts": time.time()}
    return results
