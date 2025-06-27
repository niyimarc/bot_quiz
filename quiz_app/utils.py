import csv
import requests
from io import StringIO

def get_questions_from_sheet(url):
    response = requests.get(url)
    response.encoding = 'utf-8'
    f = StringIO(response.text.lstrip('\ufeff'))
    reader = csv.DictReader(f)

    questions = []
    for row in reader:
        questions.append({
            "number": row["Question Number"],
            "text": row["Question"],
            "options": [
                f"A: {row['Option A']}",
                f"B: {row['Option B']}",
                f"C: {row['Option C']}",
                f"D: {row['Option D']}",
                f"E: {row.get('Option E', '')}",
            ],
            "correct": row["Correct Answer"][0].upper(),
        })
    return questions