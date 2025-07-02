from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import Quiz, QuizParticipant, QuizScore, QuizSession, RetryQuizScore
from .utils import get_questions_from_sheet, normalize
import logging
logger = logging.getLogger(__name__)

@csrf_exempt
def get_quizzes(request):
    telegram_id = request.GET.get("telegram_id")
    if not telegram_id:
        return JsonResponse({"error": "Missing telegram_id"}, status=400)

    participant, _ = QuizParticipant.objects.get_or_create(telegram_id=telegram_id, is_active=True)

    # Show public or otherwise accessible quizzes
    accessible_quizzes = [
        quiz.name for quiz in Quiz.objects.filter(is_active=True)
        if quiz.is_accessible_by(participant)
    ]

    if not accessible_quizzes:
        return JsonResponse({"message": "No accessible quizzes found."}, status=200)

    return JsonResponse(accessible_quizzes, safe=False)


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
        explicit_session_id = request.POST.get("session_id")  # <- NEW

        if not telegram_id or not text:
            return JsonResponse({"error": "Missing telegram_id or text"}, status=400)

        participant, _ = QuizParticipant.objects.get_or_create(telegram_id=telegram_id)

        # Handle RESUME__<session_id>
        if text.startswith("RESUME__"):
            session_id = text.replace("RESUME__", "").split("|")[0].strip()
            try:
                session = QuizSession.objects.get(id=session_id, participant=participant, active=True)
            except QuizSession.DoesNotExist:
                return JsonResponse({"error": "Session not found or already completed."})

            if session.index >= len(session.questions):
                return JsonResponse({"error": "This session is already complete. Use /start to begin a new quiz."})

            question = session.questions[session.index]
            return JsonResponse({
                "type": "question",
                "message": question["text"],
                "options": question["options"],
                "progress": f"Question {session.index + 1} of {len(session.questions)}",
                "session_id": session.id  # <-- Send back session_id for future answers
            })

        # Handle new quiz start
        quiz = Quiz.objects.filter(name=text, is_active=True).first()
        if quiz:
            if not quiz.is_accessible_by(participant):
                return JsonResponse({"error": "This quiz is private and you do not have access."}, status=403)

            questions = get_questions_from_sheet(quiz.sheet_url)
            score = QuizScore.objects.create(participant=participant, quiz=quiz, total_questions=len(questions))
            session = QuizSession.objects.create(
                participant=participant,
                quiz=quiz,
                score_obj=score,
                questions=questions,
            )

            current_question = session.questions[session.index]
            return JsonResponse({
                "type": "question",
                "message": current_question["text"],
                "options": current_question["options"],
                "progress": f"Question 1 of {len(questions)}",
                "session_id": session.id  # <-- Important
            })

        # Continue existing session using provided session_id if available
        session = None
        if explicit_session_id:
            session = QuizSession.objects.filter(id=explicit_session_id, participant=participant, active=True).first()
        if not session:
            session = QuizSession.objects.filter(participant=participant, active=True).first()

        if not session:
            return JsonResponse({"error": "No active session."}, status=404)

        # Check if session is already completed
        if session.index >= len(session.questions):
            session.active = False
            session.score_obj.end_time = timezone.now()
            session.save()
            session.score_obj.save()
            quiz_name = session.quiz.name if session.quiz else "Quiz"
            return JsonResponse({
                "type": "feedback",
                "final_message": f"🎉 You've completed the *{quiz_name}* quiz!\n\n"
                                 f"📊 Your final score: *{session.score}* out of *{len(session.questions)}*\n\n"
                                 "Use /start to try a new quiz or /continue if you left one unfinished.",
                "final_score": session.score,
                "total_questions": len(session.questions),
                "progress": f"Completed {session.index} of {len(session.questions)}",
                "session_id": session.id  # Optional, for confirmation
            })

        # Evaluate current question
        question = session.questions[session.index]
        user_input = normalize(text)
        correct_answer = normalize(question["correct"])
        options = question["options"]
        normalized_options = [normalize(opt) for opt in options]

        # logger.debug(f"[DEBUG] Normalized user input: {repr(user_input)}")
        # logger.debug(f"[DEBUG] Normalized options: {normalized_options}")
        # print("--------- DEBUG INFO ---------")
        # print("Raw user input:", repr(text))
        # print("Normalized user input:", repr(user_input))
        # print("Raw options:")
        # for opt in options:
        #     print("  -", repr(opt))
        # print("Normalized options:")
        # for norm in normalized_options:
        #     print("  -", repr(norm))
        # print("-------------------------------")

        if user_input not in normalized_options:
            return JsonResponse({
                "error": "❗ The answer you provided is not in the list of options.\n\n"
                         "Use /continue to resume your quiz properly.",
                "session_id": session.id
            })

        formatted_options = "\n".join(options)
        full_feedback = (
            f"*Q{session.index + 1}*: {question['text']}\n{formatted_options}\n"
            f"Your Answer: {text.strip()}\n"
        )
        is_correct = user_input.startswith(correct_answer)
        full_feedback += "✅ Correct!" if is_correct else f"❌ Incorrect. Correct Answer: {correct_answer}"

        if is_correct:
            session.score += 1
            session.score_obj.score += 1
        else:
            # Track the missed question number (starting from 1, not 0)
            if not isinstance(session.score_obj.missed_questions, list):
                session.score_obj.missed_questions = []
            session.score_obj.missed_questions.append(session.index + 1)

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
                "progress": f"Completed {session.index} of {len(session.questions)}",
                "session_id": session.id
            })

        return JsonResponse({
            "type": "feedback",
            "feedback": full_feedback,
            "question": session.questions[session.index],
            "progress": f"Question {session.index + 1} of {len(session.questions)}",
            "session_id": session.id
        })

    except Exception as e:
        logger.exception("❌ CRASH in process_message")
        return JsonResponse({"error": "Internal Server Error"}, status=500)

@csrf_exempt
def get_participated_quizzes(request):
    telegram_id = request.GET.get("telegram_id")
    if not telegram_id:
        return JsonResponse({"error": "Missing telegram_id"}, status=400)

    try:
        participant = QuizParticipant.objects.get(telegram_id=telegram_id, is_active=True)
    except QuizParticipant.DoesNotExist:
        return JsonResponse({"error": "Participant not found or inactive"}, status=404)

    scores = QuizScore.objects.filter(participant=participant)

    data = []
    for score in scores:
        data.append({
            "quiz_name": score.quiz.name,
            "score": score.score,
            "total_questions": score.total_questions,
            "start_time": score.start_time.isoformat(),
            "end_time": score.end_time.isoformat() if score.end_time else None,
        })

    return JsonResponse(data, safe=False)

@csrf_exempt
def retry_missed_question(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    telegram_id = request.POST.get("telegram_id")
    original_score_id = request.POST.get("score_id")
    answer = request.POST.get("answer")

    if not telegram_id or not original_score_id:
        return JsonResponse({"error": "Missing telegram_id or score_id"}, status=400)

    try:
        participant = QuizParticipant.objects.get(telegram_id=telegram_id)
        original_score = QuizScore.objects.get(id=original_score_id, participant=participant)
    except (QuizParticipant.DoesNotExist, QuizScore.DoesNotExist):
        return JsonResponse({"error": "Participant or quiz score not found"}, status=404)

    raw_missed = original_score.missed_questions or []
    missed_questions = [(i - 1) for i in raw_missed if isinstance(i, int) and i > 0]

    if not missed_questions:
        return JsonResponse({"error": "🎉 No missed questions to retry!"}, status=400)

    all_questions = get_questions_from_sheet(original_score.quiz.sheet_url)
    if any(i >= len(all_questions) or i < 0 for i in missed_questions):
        return JsonResponse({
            "error": "⚠️ The quiz content has changed since your last attempt. Retry session closed."
        }, status=400)

    retry = RetryQuizScore.objects.create(
        original_score=original_score,
        missed_questions=missed_questions,
        total_questions=len(missed_questions),
        score=0,
        index=0
    )

    if retry.index >= retry.total_questions:
        retry.end_time = timezone.now()
        retry.save()
        return JsonResponse({
            "type": "complete",
            "message": f"✅ Retry complete! Your score: {retry.score}/{retry.total_questions}"
        })

    current_index = retry.missed_questions[retry.index]
    current_question = all_questions[current_index]

    # No answer yet — return the first retry question
    if not answer:
        return JsonResponse({
            "type": "question",
            "message": current_question["text"],
            "options": current_question["options"],
            "progress": f"Retry Question {retry.index + 1} of {retry.total_questions}",
            "retry_id": retry.id,
            "score_id": original_score.id
        })

    # Validate and evaluate answer
    normalized_answer = normalize(answer)
    correct_answer = normalize(current_question["correct"])
    normalized_options = [normalize(opt) for opt in current_question["options"]]

    if normalized_answer not in normalized_options:
        return JsonResponse({
            "error": "❗ Your answer is not in the list of options.",
            "retry_id": retry.id
        })

    question_number = retry.index + 1  # For display
    formatted_options = "\n".join(current_question["options"])
    feedback = f"*Q{question_number}*: {current_question['text']}\n{formatted_options}\n"
    feedback += f"Your Answer: {answer.strip()}\n"

    if normalized_answer.startswith(correct_answer):
        feedback += "✅ Correct!"
        retry.score += 1
    else:
        feedback += f"❌ Incorrect. Correct answer is: {current_question['correct']}"

    retry.index += 1
    retry.save()

    # Retry finished
    if retry.index >= retry.total_questions:
        retry.end_time = timezone.now()
        retry.save()
        return JsonResponse({
            "type": "complete",
            "feedback": feedback,
            "final_score": retry.score,
            "total_questions": retry.total_questions,
            "message": f"🎉 Congratulations on completing your retry session!\n\n"
                       f"✅ Final Score: {retry.score}/{retry.total_questions}\n"
                       f"📚 Keep practicing to improve even more!"
        })

    # Next question
    next_index = retry.missed_questions[retry.index]
    if next_index >= len(all_questions):
        retry.end_time = timezone.now()
        retry.save()
        return JsonResponse({
            "error": "⚠️ The quiz content has changed since your last attempt. Retry session closed."
        }, status=400)

    next_question = all_questions[next_index]

    return JsonResponse({
        "type": "feedback",
        "feedback": feedback,
        "next_question": {
            "text": next_question["text"],
            "options": next_question["options"],
        },
        "progress": f"Retry Question {retry.index + 1} of {retry.total_questions}",
        "retry_id": retry.id
    })



@csrf_exempt
def get_retryable_scores(request):
    telegram_id = request.GET.get("telegram_id")

    if not telegram_id:
        return JsonResponse({"error": "Missing telegram_id"}, status=400)

    try:
        participant = QuizParticipant.objects.get(telegram_id=telegram_id)
    except QuizParticipant.DoesNotExist:
        return JsonResponse({"error": "Participant not found"}, status=404)

    retryable = []

    scores = QuizScore.objects.filter(participant=participant).order_by("-attempt_time")
    for score in scores:
        missed = score.missed_questions or []

        if not missed:
            continue  # No missed questions

        retryable.append({
            "quiz_name": score.quiz.name,
            "score_id": score.id,
            "missed_count": len(missed),
        })

    return JsonResponse(retryable, safe=False)
