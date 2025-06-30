# views.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from quiz_app.models import Quiz, QuizParticipant, QuizScore, QuizSession
from quiz_app.utils import get_questions_from_sheet
import logging
logger = logging.getLogger(__name__)

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

    unfinished_scores = QuizScore.objects.filter(participant=participant, end_time__isnull=True)
    if not unfinished_scores.exists():
        return JsonResponse({"error": "No unfinished quizzes found."}, status=404)

    options = []
    for score in unfinished_scores:
        session = QuizSession.objects.filter(score_obj=score, participant=participant, active=True).first()
        if session:
            total = len(session.questions)
            index = session.index + 1
            label = f"{score.quiz.name} ({index} of {total})"
            options.append({
                "session_id": session.id,
                "label": label
            })

    return JsonResponse({
        "message": "📝 You have unfinished quizzes. Select one to continue:",
        "options": options
    })

@csrf_exempt
def process_message(request):
    try:
        if request.method != "POST":
            return JsonResponse({"error": "POST only"}, status=405)

        telegram_id = request.POST.get("telegram_id")
        text = request.POST.get("text")

        if not telegram_id or not text:
            return JsonResponse({"error": "Missing telegram_id or text"}, status=400)

        participant, _ = QuizParticipant.objects.get_or_create(telegram_id=telegram_id)

        # Check if resuming a session
        if text.startswith("RESUME__"):
            session_id = text.replace("RESUME__", "").split("|")[0].strip()
            try:
                session = QuizSession.objects.get(id=session_id, participant=participant, active=True)
            except QuizSession.DoesNotExist:
                return JsonResponse({"error": "Session not found or already completed."})
            
            question = session.questions[session.index]
            return JsonResponse({
                "type": "question",
                "message": question["text"],
                "options": question["options"],
                "progress": f"Question {session.index + 1} of {len(session.questions)}"
            })

        
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
            return JsonResponse({
                "type": "question",
                "message": questions[0]["text"],
                "options": questions[0]["options"],
                "progress": f"Question 1 of {len(questions)}"
            })

        session = QuizSession.objects.filter(participant=participant, active=True).first()
        if not session:
            return JsonResponse({"error": "No active session."}, status=404)

        question = session.questions[session.index]
        correct = question["correct"]
        selected = text.strip().upper()[0]
        question_text = question["text"]
        options = question["options"]

        formatted_options = "\n".join(options)
        full_feedback = f"*Q{session.index + 1}*: {question_text}\n{formatted_options}\nYour Answer: {text.strip()}\n"
        full_feedback += "✅ Correct!" if selected == correct else f"❌ Incorrect. Correct Answer: {correct}"

        # Check if user input is one of the options
        if text.strip() not in options:
            return JsonResponse({
                "error": "❗ The answer you provided is not in the list of options.\n\n"
                        "Use /continue to resume your quiz properly."
            })

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
            quiz_name = session.quiz.name if session.quiz else "Quiz"
            return JsonResponse({
                "type": "feedback",
                "feedback": full_feedback,
                "final_message": f"🎉 You've completed the *{quiz_name}* quiz!\n\n"
                                f"📊 Your final score: *{session.score}* out of *{len(session.questions)}*\n\n"
                                "Use /start to try a new quiz or /continue if you left one unfinished.",
                "final_score": session.score,
                "total_questions": len(session.questions),
                "progress": f"Completed {session.index} of {len(session.questions)}"
            })

        return JsonResponse({
            "type": "feedback",
            "feedback": full_feedback,
            "question": session.questions[session.index],
            "progress": f"Question {session.index + 1} of {len(session.questions)}"
        })
    except Exception as e:
        logger.exception("❌ CRASH in process_message")
        return JsonResponse({"error": "Internal Server Error"}, status=500)
