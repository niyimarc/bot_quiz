import csv
import requests
from io import StringIO
from django.core.cache import cache
import hashlib
import unicodedata

def normalize(s):
    """Strip whitespace, quotes, and normalize unicode for fair comparison."""
    if not isinstance(s, str):
        return ""
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    s = s.strip().strip("'\"")
    return unicodedata.normalize("NFKD", s).upper()

def clean_option_text(value):
    """Apply normalization and cleaning to option strings before storing them."""
    return normalize(value).capitalize()

def get_questions_from_sheet(url):
    cache_key = f"quiz_questions:{hashlib.md5(url.encode()).hexdigest()}"

    cached_questions = cache.get(cache_key)
    if cached_questions:
        print("Loaded questions from cache.")
        return cached_questions

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        print("Successfully fetched sheet.")
    except requests.exceptions.RequestException as e:
        raise ValueError(f"❌ Failed to load questions sheet: {e}")

    response.encoding = 'utf-8'
    text_data = response.text.lstrip('\ufeff')
    f = StringIO(text_data)
    reader = csv.DictReader(f)

    questions = []
    option_letters = ['A', 'B', 'C', 'D', 'E', 'F']

    for i, row in enumerate(reader, start=1):
        question_text = row.get("question", "").strip()
        if not question_text:
            raise ValueError(f"❌ Question text is missing for question {i}")

        row_lower = {k.lower(): v for k, v in row.items()}

        options = []
        valid_letters = set()
        for letter in option_letters:
            raw_value = row_lower.get(f"option_{letter.lower()}", "")
            if raw_value:
                cleaned_value = clean_option_text(raw_value)
                options.append(f"{letter}: {cleaned_value}")
                valid_letters.add(letter)

        correct_raw = row.get("correct_answer", "").strip().upper()
        if not correct_raw:
            raise ValueError(f"❌ Missing correct answer for question {i}")

        correct = correct_raw[0]
        if correct not in valid_letters:
            raise ValueError(f"❌ Correct answer '{correct}' for question {i} does not match any provided options")

        questions.append({
            "number": row.get("question_number", str(i)).strip(),
            "text": question_text,
            "options": options,
            "correct": correct,
        })

    cache.set(cache_key, questions, timeout=600)

    return questions