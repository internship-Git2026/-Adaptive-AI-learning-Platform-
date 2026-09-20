import os
import json
import logging
import re

from dotenv import load_dotenv
from llm import GROQ_MODEL, GroqAuthError, generate
from gate_course import GATE_SUBJECTS, NEET_SUBJECTS

# Load .env
load_dotenv()

logger = logging.getLogger(__name__)

# Length of study material actually sent to the model.
MAX_QUIZ_SOURCE_CHARS = 12000
MAX_VALIDATION_CHARS = 4000

# Valid difficulty levels
VALID_DIFFICULTIES = ("Easy", "Medium", "Hard")

# Map course name -> list of subject dicts (from gate_course / neet_course)
SUBJECTS_BY_COURSE = {
    "GATE": GATE_SUBJECTS,
    "NEET": NEET_SUBJECTS,
}


def _get_valid_topics(course):
    """Return the list of valid topic names for a given course."""
    subjects = SUBJECTS_BY_COURSE.get(course, [])
    return [s["name"] for s in subjects]


def _subject_keyword_list(course):
    """Return a newline-formatted keyword list for the prompt."""
    subjects = SUBJECTS_BY_COURSE.get(course, [])
    lines = []
    for s in subjects:
        lines.append(f"- {s['name']} (keywords: {', '.join(s['keywords'])})")
    return "\n".join(lines) if lines else "General"


class QuizGenerationError(Exception):
    """Raised when quiz generation fails.

    Carries a `stage` (for logs) and a user-safe `message` that must never
    contain internal details, keys, or full prompts.
    """

    def __init__(self, stage, message):
        super().__init__(message)
        self.stage = stage
        self.message = message


def _redact(text):
    """Remove anything that looks like a secret from an error string."""
    redacted = re.sub(
        r"(?i)(api[_-]?key|authorization|bearer)\s*[=:\s]\s*[A-Za-z0-9_\-\.]{8,}",
        r"\1=***",
        str(text),
    )
    return redacted[:500]


def _extract_json(text):
    """Return the first valid JSON array/object found in `text`.

    Tolerates markdown code fences, leading prose, trailing text,
    and common JSON issues like trailing commas.
    """
    if not text or not text.strip():
        raise QuizGenerationError("json_parse", "AI returned an empty response.")

    cleaned = text.strip()
    
    # Remove markdown code fences (```json ... ```)
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?\s*```\s*$", "", cleaned)
    
    # Remove common prefixes/suffixes the model might add
    cleaned = re.sub(r'^(?:Here\s+(?:is|are)\s+the\s+questions[^:]*:\s*\n?)', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^(?:Below\s+(?:is|are)\s+the\s+questions[^:]*:\s*\n?)', '', cleaned, flags=re.IGNORECASE)
    
    candidates = [cleaned]
    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        match = re.search(pattern, cleaned)
        if match:
            candidates.append(match.group(0))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    
    # Last resort: try to fix common JSON issues and retry
    for candidate in candidates:
        try:
            # Remove trailing commas before ] or }
            fixed = re.sub(r',\s*([\]\}])', r'\1', candidate)
            # Remove single-line comments
            fixed = re.sub(r'//[^\n]*', '', fixed)
            # Remove multi-line comments
            fixed = re.sub(r'/\*[\s\S]*?\*/', '', fixed)
            return json.loads(fixed)
        except (json.JSONDecodeError, TypeError):
            continue

    raise QuizGenerationError(
        "json_parse", "AI response was not valid JSON."
    )


def _shuffle_options(item):
    """Shuffle options using a deterministic permutation so correct_answer
    is distributed across positions. This is applied AFTER normalisation
    to guarantee the AI's bias toward Option A doesn't affect the user.

    Uses a simple rotation based on the question index hash so each
    question gets a different position for the correct answer.
    """
    import random
    
    options = list(item["options"])
    correct_idx = item["correct_answer"]
    
    # Save the correct answer
    correct_text = options[correct_idx]
    
    # Create a fixed but varied permutation for this question
    # Use question text hash for determinism (same question always same shuffle)
    seed = hash(item["question"]) % 10000
    rng = random.Random(seed)
    
    # Shuffle all options
    indices = [0, 1, 2, 3]
    rng.shuffle(indices)
    
    # Apply the shuffle
    new_options = [options[i] for i in indices]
    
    # Find where the correct answer ended up
    new_correct_idx = indices.index(correct_idx)
    
    return {
        "question": item["question"],
        "options": new_options,
        "correct_answer": new_correct_idx,
        "explanation": item["explanation"],
        "topic": item["topic"],
        "difficulty": item["difficulty"],
    }


def _normalise_question(item):
    """Validate and normalise one generated question.

    Returns a validated dict or raises QuizGenerationError with the reason.
    """
    if not isinstance(item, dict):
        raise QuizGenerationError("validation", "AI returned a non-object question.")

    question = str(item.get("question", "")).strip()
    if not question:
        raise QuizGenerationError("validation", "AI returned a question with empty text.")

    options = item.get("options")
    if not isinstance(options, (list, tuple)) or len(options) != 4:
        raise QuizGenerationError(
            "validation", "AI returned a question without exactly four options."
        )

    options = [str(opt).strip() for opt in options]
    if any(not opt for opt in options):
        raise QuizGenerationError("validation", "AI returned a question with an empty option.")

    correct_answer = item.get("correct_answer")
    if isinstance(correct_answer, bool) or not isinstance(correct_answer, int):
        raise QuizGenerationError("validation", "AI returned a non-integer correct_answer.")
    if correct_answer not in (0, 1, 2, 3):
        raise QuizGenerationError("validation", "AI returned an out-of-range correct_answer index.")

    explanation = str(item.get("explanation", "")).strip()
    if not explanation:
        raise QuizGenerationError("validation", "AI returned a question without an explanation.")

    # topic: accept any non-empty string, default to 'General' if missing/empty
    topic = str(item.get("topic", "")).strip() or "General"

    # difficulty: must be Easy/Medium/Hard, default to 'Medium' if invalid
    difficulty = str(item.get("difficulty", "")).strip()
    if difficulty not in VALID_DIFFICULTIES:
        difficulty = "Medium"

    return {
        "question": question,
        "options": options,
        "correct_answer": correct_answer,
        "explanation": explanation,
        "topic": topic,
        "difficulty": difficulty,
    }


def generate_questions(text, question_count=10, difficulty="Medium", course=None):
    """
    Generate AI quiz questions from extracted PDF text.

    When *course* is provided (e.g. "GATE" or "NEET"), the prompt includes
    the valid subject/topic vocabulary for that course so the model picks
    from a fixed list instead of inventing topic names.

    Returns a list of validated question dicts.
    Raises QuizGenerationError on any failure so callers can log the stage.
    """
    source = (text or "").strip()
    if not source:
        raise QuizGenerationError(
            "empty_source",
            "No study text available. Upload a PDF with readable content first.",
        )

    logger.info(
        "QUIZ_PIPELINE: source chars=%d, prompt chars=%d, "
        "question_count=%d, difficulty=%s, course=%s, model=%s",
        len(source), min(len(source), MAX_QUIZ_SOURCE_CHARS),
        question_count, difficulty, course, GROQ_MODEL,
    )

    # Build the topic vocabulary instruction for the prompt
    topic_instruction = ""
    if course and course in SUBJECTS_BY_COURSE:
        topic_list = _subject_keyword_list(course)
        topic_instruction = (
            f"\nValid topics for {course} (you MUST pick one of these as the \"topic\" field):\n"
            f"{topic_list}\n"
        )

    prompt = f"""
You are an expert teacher.

Read the study material carefully.

Generate exactly {question_count} multiple-choice questions.

Difficulty Level: {difficulty}
{topic_instruction}
Return ONLY valid JSON.

The JSON format MUST be:

[
  {{
    "question":"Question here",
    "options":["Option A","Option B","Option C","Option D"],
    "correct_answer":2,
    "explanation":"Why this answer is correct.",
    "topic":"Topic name from the list above",
    "difficulty":"Easy"
  }}
]

Rules:

1. Exactly 4 options.
2. correct_answer must be:
   0 = Option A
   1 = Option B
   2 = Option C
   3 = Option D
3. CRITICAL: You MUST distribute correct answers across all four options (0, 1, 2, 3) roughly evenly. Do NOT always put the correct answer as Option A (index 0). Vary the correct answer position across questions. For example, if generating 10 questions, roughly 2-3 should have correct_answer=0, 2-3 should have correct_answer=1, 2-3 should have correct_answer=2, and 2-3 should have correct_answer=3.
4. The incorrect options (distractors) must be plausible and related to the topic. Do NOT make obviously wrong answers.
5. topic must be one of the valid topics listed above (or "General" if not applicable).
6. difficulty must be exactly one of: "Easy", "Medium", "Hard".
   - Easy: simple factual recall. Ask for definitions, dates, formulas, or basic identification.
   - Medium: application questions. Require understanding concepts and applying them to a new scenario.
   - Hard: complex reasoning. Require comparing concepts, analyzing trade-offs, or multi-step problem solving. Include plausible distractors that could trick someone who only partially understands.
7. Return ONLY valid JSON array. No markdown, no code fences, no extra text before or after.
8. Each question object must have all 6 fields: question, options, correct_answer, explanation, topic, difficulty.

Study Material:

{source[:MAX_QUIZ_SOURCE_CHARS]}
"""

    # Build a simpler fallback prompt for retries
    simple_prompt = f"""
Generate {question_count} MCQs from the study material below.
Difficulty: {difficulty}
{topic_instruction}
Return ONLY a JSON array. No markdown, no text, no explanation outside the JSON.
Each object: {{"question":"...","options":["A","B","C","D"],"correct_answer":0,"explanation":"...","topic":"...","difficulty":"{difficulty}"}}

correct_answer: 0=A, 1=B, 2=C, 3=D. Distribute correct answers across 0,1,2,3.
Study Material:
{source[:MAX_QUIZ_SOURCE_CHARS]}
"""

    max_retries = 2
    output = None
    last_error = None
    
    for attempt in range(max_retries):
        current_prompt = prompt if attempt == 0 else simple_prompt
        temp = 0.7 if attempt == 0 else 0.3
        
        logger.info("QUIZ_PIPELINE: Groq request = started (attempt %d/%d)", attempt + 1, max_retries)
        try:
            output = generate(current_prompt, temperature=temp)
        except GroqAuthError as exc:
            # Non-transient: the API key is dead. Don't waste retries.
            logger.error("QUIZ_PIPELINE: Groq request = rejected (bad API key)")
            raise QuizGenerationError("groq_auth", str(exc)) from exc
        except Exception as exc:
            logger.error("QUIZ_PIPELINE: Groq request = failed (attempt %d): %s", attempt + 1, _redact(exc))
            last_error = exc
            continue
        logger.info("QUIZ_PIPELINE: Groq request = completed (attempt %d)", attempt + 1)

        if not output:
            logger.warning("QUIZ_PIPELINE: Groq response = empty (attempt %d)", attempt + 1)
            continue

        logger.info("QUIZ_PIPELINE: Groq response = received (chars=%d)", len(output))
        logger.info("QUIZ_PIPELINE: response parsing = started")

        try:
            data = _extract_json(output)
            if not isinstance(data, list) or len(data) == 0:
                logger.warning("QUIZ_PIPELINE: json_structure = invalid (attempt %d)", attempt + 1)
                continue
            logger.info("QUIZ_PIPELINE: response parsing = ok (%d raw items)", len(data))
            break
        except QuizGenerationError as exc:
            logger.warning("QUIZ_PIPELINE: json_parse = failed (attempt %d): %s", attempt + 1, exc.message)
            last_error = exc
            continue
    else:
        # All retries exhausted
        raise QuizGenerationError(
            "groq_request", "AI service failed to generate valid questions after multiple attempts."
        ) from last_error

    validated = []
    for index, item in enumerate(data, start=1):
        try:
            validated.append(_normalise_question(item))
        except QuizGenerationError as exc:
            logger.warning(
                "QUIZ_PIPELINE: question %d rejected (%s): %s",
                index, exc.stage, exc.message,
            )
            continue

    if not validated:
        raise QuizGenerationError(
            "validation", "AI returned questions that failed validation."
        )

    # Post-process: shuffle options to fix answer distribution
    # This guarantees the correct answer is spread across all positions
    validated = [_shuffle_options(q) for q in validated]
    
    # Log the distribution for debugging
    answer_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    for q in validated:
        answer_counts[q["correct_answer"]] += 1
    logger.info(
        "QUIZ_PIPELINE: answer distribution after shuffle = %s",
        answer_counts,
    )
    
    logger.info(
        "QUIZ_PIPELINE: validation = ok (%d/%d questions kept)",
        len(validated), len(data),
    )
    return validated


def validate_pdf_content(text, course):
    """
    Validate if the text extracted from PDF is suitable study material for the given course (GATE or NEET).
    Rejects: wrong course material, assignments, resumes, business documents, unrelated PDFs.
    Returns: (is_valid, error_message)
    """
    prompt = f"""
You are an expert academic validator.
Analyze the following extracted text from a PDF study material.
Determine if it is academic study material (notes, syllabus, textbooks, problem sheets, question banks, or reference materials) suitable for preparing for the {course} exam.

Note:
- GATE (Graduate Aptitude Test in Engineering) covers a very wide range of subjects: Computer Science, Mathematics, Physics, Chemistry, Mechanical, Electrical, Civil, Biotechnology, Biomedical, etc. So engineering problem sheets, project lists, and research papers are valid.
- NEET (National Eligibility cum Entrance Test) covers Physics, Chemistry, and Biology (Botany/Zoology).

You must reject:
1. Resumes, CVs, portfolios, or personal career profiles.
2. Corporate business documents, financial reports, marketing materials, or company pitch decks.
3. Completely unrelated content (news articles, fictional stories, personal letters, etc.).
4. Obvious wrong course material (e.g., advanced computer architecture for NEET, or human anatomy for GATE Computer Science).

Return ONLY a JSON object with:
{{
  "is_valid": true/false,
  "reason": "Explain why it is valid or why it is rejected (briefly)."
}}

Do NOT write markdown. Do NOT write ```json.

Extracted Text (first 4000 characters):
{text[:MAX_VALIDATION_CHARS]}
"""
    try:
        logger.info("VALIDATION_PIPELINE: Groq request = started")
        response_text = generate(prompt)
        logger.info("VALIDATION_PIPELINE: Groq request = completed")
        result = _extract_json(response_text)
        return result.get("is_valid", False), result.get("reason", "Invalid content.")
    except QuizGenerationError as exc:
        logger.error("VALIDATION_PIPELINE: parsing = failed (%s): %s", exc.stage, exc.message)
    except Exception as e:
        logger.error("VALIDATION_PIPELINE: request = failed: %s", _redact(e))
    # Fallback to allow if the validation service is unavailable.
    return True, "Validation bypassed due to service status."