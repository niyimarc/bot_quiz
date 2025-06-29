# views.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from quiz_app.models import Quiz, QuizParticipant, QuizScore, QuizSession
from quiz_app.utils import get_questions_from_sheet
import json

@csrf_exempt
def get_quizzes(request):
    quizzes = Quiz.objects.filter(is_active=True, status="public").values_list("name", flat=True)
    return JsonResponse(list(quizzes), safe=False)

@csrf_exempt
def continue_session(request):
    telegram_id = request.GET.get("telegram_id")
    if not telegram_id:
        return JsonResponse({"error": "Missing telegram_id"}, status=400)

    try:
        participant = QuizParticipant.objects.get(telegram_id=telegram_id, is_active=True)
    except QuizParticipant.DoesNotExist:
        return JsonResponse({"error": "Participant not found or inactive"}, status=404)

    score = QuizScore.objects.filter(participant=participant, end_time__isnull=True).first()
    if not score:
        return JsonResponse({"error": "No unfinished quiz"}, status=404)

    quiz = score.quiz
    questions = get_questions_from_sheet(quiz.sheet_url)

    session, _ = QuizSession.objects.get_or_create(
        participant=participant,
        quiz=quiz,
        score_obj=score,
        active=True,
        defaults={"index": score.score, "score": score.score, "questions": questions},
    )

    response = {
        "quiz_name": quiz.name,
        "question": questions[session.index],
    }
    return JsonResponse(response)

@csrf_exempt
def process_message(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    telegram_id = request.POST.get("telegram_id")
    text = request.POST.get("text")

    if not telegram_id or not text:
        return JsonResponse({"error": "Missing telegram_id or text"}, status=400)

    participant, _ = QuizParticipant.objects.get_or_create(telegram_id=telegram_id)

    quiz = Quiz.objects.filter(name=text, is_active=True).first()
    if quiz:
        if quiz.status == "private" and quiz.participant != participant:
            return JsonResponse({"error": "This quiz is private."}, status=403)

        questions = get_questions_from_sheet(quiz.sheet_url)
        score = QuizScore.objects.create(participant=participant, quiz=quiz, total_questions=len(questions))
        session = QuizSession.objects.create(
            participant=participant,
            quiz=quiz,
            score_obj=score,
            questions=questions,
        )
        return JsonResponse({"type": "question", "question": questions[0]})

    session = QuizSession.objects.filter(participant=participant, active=True).first()
    if not session:
        return JsonResponse({"error": "No active session."}, status=404)

    question = session.questions[session.index]
    correct = question["correct"]
    selected = text.strip().upper()[0]
    feedback = "✅ Correct!" if selected == correct else f"❌ Incorrect. Correct: {correct}"

    if selected == correct:
        session.score += 1
        session.score_obj.score += 1

    session.index += 1
    session.score_obj.save()
    session.save()

    if session.index >= len(session.questions):
        session.active = False
        session.score_obj.end_time = timezone.now()
        session.save()
        session.score_obj.save()
        return JsonResponse({"type": "feedback", "feedback": feedback, "final_score": session.score, "total_questions": len(session.questions)})

    return JsonResponse({"type": "feedback", "feedback": feedback, "question": session.questions[session.index]})
