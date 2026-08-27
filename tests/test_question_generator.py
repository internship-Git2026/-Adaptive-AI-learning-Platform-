"""Unit tests for the AI quiz generator's parsing and validation helpers.

These tests deliberately avoid calling the Gemini API; they exercise the
pure helpers that turn a raw model response into validated questions.
"""
import pytest

from question_generator import (
    QuizGenerationError,
    _extract_json,
    _normalise_question,
)


def test_extract_json_from_clean_array():
    data = _extract_json('[{"question":"Q","options":["a","b","c","d"],"correct_answer":0,"explanation":"x"}]')
    assert isinstance(data, list)
    assert len(data) == 1


def test_extract_json_from_markdown_fence():
    payload = (
        "```json\n"
        '[{"question":"Q","options":["a","b","c","d"],"correct_answer":1,"explanation":"x"}]\n'
        "```"
    )
    data = _extract_json(payload)
    assert data[0]["correct_answer"] == 1


def test_extract_json_with_prose_around():
    payload = (
        "Here are your questions:\n"
        '[{"question":"Q","options":["a","b","c","d"],"correct_answer":2,"explanation":"x"}]\n'
        "Good luck studying!"
    )
    data = _extract_json(payload)
    assert data[0]["question"] == "Q"


def test_extract_json_rejects_invalid():
    with pytest.raises(QuizGenerationError) as exc_info:
        _extract_json("this is definitely not json")
    assert exc_info.value.stage == "json_parse"


def test_extract_json_rejects_empty():
    with pytest.raises(QuizGenerationError):
        _extract_json("   ")


def test_normalise_question_accepts_valid():
    result = _normalise_question({
        "question": "What is 2+2?",
        "options": ["1", "2", "4", "8"],
        "correct_answer": 2,
        "explanation": "Because.",
    })
    assert result["options"] == ["1", "2", "4", "8"]
    assert result["correct_answer"] == 2


@pytest.mark.parametrize(
    "bad",
    [
        "not a dict",
        {"question": "", "options": ["a", "b", "c", "d"], "correct_answer": 0, "explanation": "e"},
        {"question": "Q", "options": ["a", "b"], "correct_answer": 0, "explanation": "e"},
        {"question": "Q", "options": ["a", "b", "c", ""], "correct_answer": 0, "explanation": "e"},
        {"question": "Q", "options": ["a", "b", "c", "d"], "correct_answer": 5, "explanation": "e"},
        {"question": "Q", "options": ["a", "b", "c", "d"], "correct_answer": -1, "explanation": "e"},
        {"question": "Q", "options": ["a", "b", "c", "d"], "correct_answer": "2", "explanation": "e"},
        {"question": "Q", "options": ["a", "b", "c", "d"], "correct_answer": True, "explanation": "e"},
        {"question": "Q", "options": ["a", "b", "c", "d"], "correct_answer": 0, "explanation": ""},
        {"question": "Q", "options": ["a", "b", "c", "d"]},  # missing answer
    ],
)
def test_normalise_question_rejects_invalid(bad):
    with pytest.raises(QuizGenerationError) as exc_info:
        _normalise_question(bad)
    assert exc_info.value.stage == "validation"