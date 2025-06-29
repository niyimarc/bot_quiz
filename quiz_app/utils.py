import csv
import requests
from io import StringIO
from django.core.cache import cache
import hashlib

def get_questions_from_sheet(url):
    print(f"📥 Loading sheet from: {url}")
    # Generate a cache key based on a hash of the URL
    cache_key = f"quiz_questions:{hashlib.md5(url.encode()).hexdigest()}"
    print(f"🔑 Cache key: {cache_key}")

    # Try to get from cache
    cached_questions = cache.get(cache_key)
    if cached_questions:
        print("✅ Loaded questions from cache.")
        return cached_questions

    # If not cached, fetch from Google Sheets
    try:
        print("🌐 Fetching data from Google Sheets...")
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        print("✅ Successfully fetched sheet.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        raise ValueError(f"❌ Failed to load questions sheet: {e}")

    response.encoding = 'utf-8'
    text_data = response.text.lstrip('\ufeff')
    print(f"📄 Raw CSV content (first 500 chars):\n{text_data[:500]}")
    f = StringIO(text_data)
    reader = csv.DictReader(f)

    questions = []
    option_letters = ['A', 'B', 'C', 'D', 'E', 'F']

    for i, row in enumerate(reader, start=1):
        print(f"\n🔎 Processing question {i}")
        print(f"➡️ Row: {row}")
        # Get and validate question text
        question_text = row.get("question", "").strip()
        if not question_text:
            raise ValueError(f"❌ Question text is missing for question {i}")
        print(f"✅ Question text: {question_text}")
        # Normalize keys
        row_lower = {k.lower(): v for k, v in row.items()}
        print(f"🔡 Normalized row keys: {row_lower.keys()}")
        # Construct options
        options = []
        valid_letters = set()
        for letter in option_letters:
            value = row_lower.get(f"option_{letter.lower()}", "").strip()
            if value:
                options.append(f"{letter}: {value}")
                valid_letters.add(letter)
        print(f"📝 Options: {options}")
        print(f"✔️ Valid letters: {valid_letters}")
        # Validate correct answer
        correct_raw = row.get("correct_answer", "").strip().upper()
        if not correct_raw:
            raise ValueError(f"❌ Missing correct answer for question {i}")

        correct = correct_raw[0]
        print(f"✅ Correct answer from sheet: {correct}")
        if correct not in valid_letters:
            raise ValueError(f"❌ Correct answer '{correct}' for question {i} does not match any provided options")

        questions.append({
            "number": row.get("Question Number", str(i)).strip(),
            "text": question_text,
            "options": options,
            "correct": correct,
        })

    # Store in cache for 10 minutes (600 seconds)
    cache.set(cache_key, questions, timeout=600)

    return questions
