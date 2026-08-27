"""Minimal tests for the adaptive quiz next-question logic.

These verify:
  - correct answer → next question is same topic, one tier HARDER
  - wrong answer   → next question is same topic, one tier EASIER
  - fallback to next unanswered when no matching topic/difficulty exists
  - no重复 of already-answered questions
"""
import pytest
from practice import next_adaptive_question, _DIFFICULTY_TIERS


def _make_pool():
    """Return a question pool with 3 topics × 3 difficulties = 9 questions."""
    pool = []
    topics = ["Data Structures", "Operating Systems"]
    for t in topics:
        for d in _DIFFICULTY_TIERS:
            for i in range(2):
                pool.append({
                    "question": f"Q-{t[:2]}-{d}-{i}",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": 0,
                    "explanation": "why",
                    "topic": t,
                    "difficulty": d,
                })
    return pool


def _make_entry(pool, answers=None, order=None):
    return {
        "kind": "adaptive",
        "questions": pool,
        "answers": answers or {},
        "score": 0,
        "order": order or [],
    }


# -------------------------------------------------------------------
# Test A — correct answer → harder difficulty, same topic
# -------------------------------------------------------------------
def test_correct_answer_selects_harder():
    pool = _make_pool()
    # Place "Data Structures / Easy" at order position 1 (pool index 0)
    entry = _make_entry(pool, answers={}, order=[0])

    idx = next_adaptive_question(entry, last_index=1, was_correct=True)
    chosen = pool[idx]
    assert chosen["topic"] == "Data Structures"
    assert chosen["difficulty"] == "Medium"  # Easy -> Medium


def test_correct_at_medium_goes_to_hard():
    pool = _make_pool()
    # pool index 2 = "Data Structures / Medium" (first of its pair)
    entry = _make_entry(pool, answers={}, order=[2])

    idx = next_adaptive_question(entry, last_index=1, was_correct=True)
    chosen = pool[idx]
    assert chosen["topic"] == "Data Structures"
    assert chosen["difficulty"] == "Hard"


def test_correct_at_hard_stays_hard():
    pool = _make_pool()
    # pool index 4 = "Data Structures / Hard" (first of its pair)
    entry = _make_entry(pool, answers={}, order=[4])

    idx = next_adaptive_question(entry, last_index=1, was_correct=True)
    chosen = pool[idx]
    assert chosen["topic"] == "Data Structures"
    assert chosen["difficulty"] == "Hard"


# -------------------------------------------------------------------
# Test B — wrong answer → easier difficulty, same topic
# -------------------------------------------------------------------
def test_wrong_answer_selects_easier():
    pool = _make_pool()
    # pool index 2 = "Data Structures / Medium"
    entry = _make_entry(pool, answers={}, order=[2])

    idx = next_adaptive_question(entry, last_index=1, was_correct=False)
    chosen = pool[idx]
    assert chosen["topic"] == "Data Structures"
    assert chosen["difficulty"] == "Easy"


def test_wrong_at_easy_stays_easy():
    pool = _make_pool()
    # pool index 0 = "Data Structures / Easy"
    entry = _make_entry(pool, answers={}, order=[0])

    idx = next_adaptive_question(entry, last_index=1, was_correct=False)
    chosen = pool[idx]
    assert chosen["topic"] == "Data Structures"
    assert chosen["difficulty"] == "Easy"


# -------------------------------------------------------------------
# Test C — fallback when no matching topic/difficulty remains
# -------------------------------------------------------------------
def test_fallback_to_next_unanswered():
    pool = _make_pool()
    # Mark ALL "Data Structures / Medium" as answered
    # Pool indices 2,3 are Data Structures / Medium
    entry = _make_entry(
        pool,
        answers={1: 0, 2: 0, 3: 0},  # answered positions 1,2,3
        order=[0, 2, 3],
    )
    # Currently at position 3 (pool index 3, DS/Medium), correct → wants DS/Hard
    # DS/Hard pool indices 4,5 — both unanswered → should pick index 4
    idx = next_adaptive_question(entry, last_index=3, was_correct=True)
    chosen = pool[idx]
    assert chosen["topic"] == "Data Structures"
    assert chosen["difficulty"] == "Hard"


def test_fallback_when_all_matching_answered():
    pool = _make_pool()
    # Answer all Data Structures questions (indices 0-5)
    entry = _make_entry(
        pool,
        answers={1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0},
        order=[0, 1, 2, 3, 4, 5],
    )
    # At position 6 (pool index 5, DS/Hard), correct → wants DS/Hard
    # All DS/Hard answered → fallback to next unanswered ( Operating Systems)
    idx = next_adaptive_question(entry, last_index=6, was_correct=True)
    chosen = pool[idx]
    assert chosen["topic"] == "Operating Systems"


# -------------------------------------------------------------------
# Test D — no重复 of already-answered questions
# -------------------------------------------------------------------
def test_no_repeat_of_answered():
    pool = _make_pool()
    # Answer positions 1 and 2
    entry = _make_entry(
        pool,
        answers={1: 0, 2: 0},
        order=[0, 2],
    )
    idx = next_adaptive_question(entry, last_index=2, was_correct=True)
    # Must not be pool index 0 or 2 (already answered)
    assert idx not in (0, 2)


# -------------------------------------------------------------------
# Test E — returns None when all questions answered
# -------------------------------------------------------------------
def test_returns_none_when_all_answered():
    pool = _make_pool()  # 12 questions
    all_indices = list(range(len(pool)))
    answers = {i + 1: 0 for i in range(len(pool))}
    entry = _make_entry(pool, answers=answers, order=all_indices)

    idx = next_adaptive_question(entry, last_index=len(pool), was_correct=True)
    assert idx is None
