from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import IntegrityError
from .models import Quiz, QuizParticipant, QuizScore, QuizSession, RetryQuizScore, RetrySession, QuizAccess
from .utils import get_questions_from_sheet, normalize, clear_participant_retry_session, get_or_create_participant
import json
import logging
logger = logging.getLogger(__name__)

@csrf_exempt
def get_quizzes(request):
    telegram_id = request.GET.get("telegram_id")
    if not telegram_id:
        return JsonResponse({"error": "Missing telegram_id"}, status=400)

    participant, _ = get_or_create_participant(request.GET)

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
            # Clean up any stale retry sessions (safe fallback)
            RetrySession.objects.filter(participant=participant).update(active=False, expecting_answer=False)
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

    all_questions = get_questions_from_sheet(original_score.quiz.sheet_url)
    raw_missed = original_score.missed_questions or []
    missed_questions = [(i - 1) for i in raw_missed if isinstance(i, int) and i > 0]

    if any(i >= len(all_questions) or i < 0 for i in missed_questions):
        return JsonResponse({
            "error": "⚠️ The quiz content has changed since your last attempt. Retry session closed."
        }, status=400)

    # Check for an active retry session first
    retry_session = RetrySession.objects.filter(participant=participant, active=True).first()
    if retry_session:
        retry = retry_session.retry
    else:
        if not missed_questions:
            return JsonResponse({"error": "🎉 No missed questions to retry!"}, status=400)

        retry = RetryQuizScore.objects.create(
            original_score=original_score,
            missed_questions=missed_questions,
            total_questions=len(missed_questions),
            score=0,
            index=0
        )
        clear_participant_retry_session(participant)
        RetrySession.objects.create(participant=participant, retry=retry)

    # Return the next question if no answer was submitted
    if not answer:
        current_index = retry.missed_questions[retry.index]
        current_question = all_questions[current_index]
        return JsonResponse({
            "type": "question",
            "message": current_question["text"],
            "options": current_question["options"],
            "progress": f"Retry Question {retry.index + 1} of {retry.total_questions}",
            "retry_id": retry.id,
            "score_id": original_score.id
        })

    # Evaluate answer
    current_index = retry.missed_questions[retry.index]
    current_question = all_questions[current_index]

    normalized_answer = normalize(answer)
    correct_answer = normalize(current_question["correct"])
    normalized_options = [normalize(opt) for opt in current_question["options"]]

    if normalized_answer not in normalized_options:
        return JsonResponse({
            "error": "❗ Your answer is not in the list of options.",
            "retry_id": retry.id
        })

    question_number = retry.index + 1
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

    if retry.index >= retry.total_questions:
        retry.end_time = timezone.now()
        retry.save()
        clear_participant_retry_session(participant)
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

@csrf_exempt
def retry_session_status(request):
    telegram_id = request.GET.get("telegram_id")
    if not telegram_id:
        return JsonResponse({"error": "Missing telegram_id"}, status=400)

    try:
        participant = QuizParticipant.objects.get(telegram_id=telegram_id)
        session = RetrySession.objects.filter(participant=participant, active=True, expecting_answer=True).latest("updated_at")

        return JsonResponse({
            "score_id": session.retry.original_score.id,
            "retry_id": session.retry.id,
            "expecting_answer": session.expecting_answer,
        })
    except:
        return JsonResponse({})
    
@csrf_exempt
def clear_retry_session(request):
    telegram_id = request.GET.get("telegram_id")
    if not telegram_id:
        return JsonResponse({"error": "Missing telegram_id"}, status=400)

    try:
        participant = QuizParticipant.objects.get(telegram_id=telegram_id)
    except QuizParticipant.DoesNotExist:
        return JsonResponse({"error": "Participant not found"}, status=404)

    RetrySession.objects.filter(participant=participant).update(active=False, expecting_answer=False)
    return JsonResponse({"status": "cleared"})

@csrf_exempt
def add_quiz(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    try:
        if request.content_type == "application/json":
            data = json.loads(request.body)
        else:
            data = request.POST # handles x-www-form-urlencoded (from PHP)

        telegram_id = data.get("telegram_id")
        name = data.get("name")
        sheet_url = data.get("sheet_url")
        status = data.get("status", "public").lower()

        if not all([telegram_id, name, sheet_url]):
            return JsonResponse({"error": "Missing required fields"}, status=400)

        if status not in ["public", "private"]:
            return JsonResponse({"error": "Invalid status. Must be 'public' or 'private'"}, status=400)

        try:
            participant = QuizParticipant.objects.get(telegram_id=telegram_id)
        except QuizParticipant.DoesNotExist:
            return JsonResponse({"error": "Participant not found"}, status=404)

        if Quiz.objects.filter(name=name).exists():
            return JsonResponse({"error": "A quiz with this name already exists."}, status=400)

        try:
            # Will raise ValueError if the sheet is invalid
            questions = get_questions_from_sheet(sheet_url)
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)

        # ✅ Check for existing sheet_url before hitting DB constraint
        if Quiz.objects.filter(sheet_url=sheet_url.strip()).exists():
            return JsonResponse({"error": "A quiz with this Google Sheet URL already exists."}, status=400)

        quiz = Quiz.objects.create(
            name=name.strip(),
            sheet_url=sheet_url.strip(),
            status=status,
            participant=participant,
            is_active=True
        )

        return JsonResponse({
            "message": f"✅ Quiz '{quiz.name}' created successfully with {len(questions)} questions.",
            "quiz_id": quiz.id
        })

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Internal Server Error: {str(e)}"}, status=500)

@csrf_exempt
def get_my_quizzes(request):
    telegram_id = request.GET.get("telegram_id")
    if not telegram_id:
        return JsonResponse({"error": "Missing telegram_id"}, status=400)

    try:
        participant = QuizParticipant.objects.get(telegram_id=telegram_id)
    except QuizParticipant.DoesNotExist:
        return JsonResponse({"error": "Participant not found"}, status=404)

    quizzes = Quiz.objects.filter(participant=participant).order_by("-id")

    data = []
    for quiz in quizzes:
        try:
            questions = get_questions_from_sheet(quiz.sheet_url)
            total_questions = len(questions)
        except Exception:
            total_questions = 0

        # All scores related to this quiz
        quiz_scores = QuizScore.objects.filter(quiz=quiz)

        # Total unique participants
        total_participants = quiz_scores.values("participant_id").distinct().count()

        # Total attempts
        total_attempts = quiz_scores.count()

        # Latest attempt
        last_attempt = quiz_scores.order_by("-attempt_time").values_list("attempt_time", flat=True).first()

        # Retry count (RetryQuizScore tied to this quiz via original_score)
        retry_count = RetryQuizScore.objects.filter(original_score__quiz=quiz).count()

        data.append({
            "quiz_id": quiz.id,
            "quiz_name": quiz.name,
            "status": quiz.status,
            "total_questions": total_questions,
            "created_at": quiz.created_date.isoformat() if quiz.created_date else None,
            "sheet_url": quiz.sheet_url,
            "is_active": quiz.is_active,
            "last_attempt_time": last_attempt.isoformat() if last_attempt else None,
            "total_participants": total_participants,
            "total_attempts": total_attempts,
            "retry_count": retry_count,
        })

    return JsonResponse(data, safe=False)

@csrf_exempt
def update_quiz_status(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    telegram_id = request.POST.get("telegram_id")
    quiz_id = request.POST.get("quiz_id")
    new_status = request.POST.get("new_status")

    if not all([telegram_id, quiz_id, new_status]):
        return JsonResponse({"error": "Missing required fields"}, status=400)

    if new_status not in ["public", "private"]:
        return JsonResponse({"error": "Invalid status. Must be 'public' or 'private'"}, status=400)

    try:
        participant = QuizParticipant.objects.get(telegram_id=telegram_id)
    except QuizParticipant.DoesNotExist:
        return JsonResponse({"error": "Participant not found"}, status=404)

    try:
        quiz = Quiz.objects.get(id=quiz_id, participant=participant)
    except Quiz.DoesNotExist:
        return JsonResponse({"error": "Quiz not found or does not belong to you"}, status=404)

    quiz.status = new_status
    quiz.save()

    return JsonResponse({
        "message": f"✅ Quiz '{quiz.name}' status updated to '{quiz.status}' successfully."
    })

@csrf_exempt
def delete_quiz(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)

    try:
        quiz_id = int(request.POST.get('quiz_id'))
        telegram_id = request.POST.get('telegram_id')
        if not telegram_id:
            return JsonResponse({'error': 'Missing telegram_id'}, status=400)

        quiz = Quiz.objects.get(pk=quiz_id)

        if str(quiz.participant.telegram_id) != str(telegram_id):
            return JsonResponse({'error': 'Unauthorized'}, status=403)

        quiz.delete()
        return JsonResponse({'success': True})

    except Quiz.DoesNotExist:
        return JsonResponse({'error': 'Quiz not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    
@csrf_exempt
def edit_quiz_name(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)

    try:
        quiz_id = int(request.POST.get('quiz_id'))
        new_name = request.POST.get('new_name', '').strip()
        telegram_id = request.POST.get('telegram_id')

        if not new_name:
            return JsonResponse({'error': 'New name is required'}, status=400)
        if not telegram_id:
            return JsonResponse({'error': 'Missing telegram_id'}, status=400)

        quiz = Quiz.objects.get(pk=quiz_id)

        if str(quiz.participant.telegram_id) != str(telegram_id):
            return JsonResponse({'error': 'Unauthorized'}, status=403)

        quiz.name = new_name
        quiz.save()

        return JsonResponse({'success': True, 'new_name': new_name})

    except Quiz.DoesNotExist:
        return JsonResponse({'error': 'Quiz not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def grant_quiz_access(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST method allowed."}, status=405)

    try:
        data = json.loads(request.body)
        telegram_id = data.get("telegram_id")
        target_telegram_id = data.get("target_telegram_id")
        target_username = data.get("target_username", "").lstrip("@").lower()
        quiz_id = data.get("quiz_id")
        access_type = data.get("access_type", "participate_access")

        if not all([telegram_id, quiz_id, access_type]) or not (target_telegram_id or target_username):
            return JsonResponse({"error": "⚠️ Missing required details. Please provide all necessary information."}, status=400)

        granter = QuizParticipant.objects.filter(telegram_id=telegram_id).first()
        if not granter:
            return JsonResponse({"error": "❗️ We couldn't identify you as a participant."}, status=404)

        quiz = Quiz.objects.filter(id=quiz_id).first()
        if not quiz:
            return JsonResponse({"error": "❗️ This quiz doesn't seem to exist."}, status=404)

        if not (quiz.participant == granter or quiz.get_access_type(granter) == "full_access"):
            return JsonResponse({"error": "🚫 You don't have permission to manage access for this quiz."}, status=403)

        # Resolve or create target
        target = None
        if target_telegram_id:
            target = QuizParticipant.objects.filter(telegram_id=target_telegram_id).first()
            if not target:
                # Create if telegram_id is available
                target = QuizParticipant.objects.create(telegram_id=target_telegram_id)
        elif target_username:
            target = QuizParticipant.objects.filter(username__iexact=target_username).first()
            if not target:
                target = QuizParticipant.objects.create(username=target_username)

        if not target:
            return JsonResponse({"error": "❗️ Couldn't find or create the user you're trying to give access to."}, status=404)

        # Prevent granting access to yourself
        if granter.id == target.id:
            return JsonResponse({
                "error": "👤 You already have access to this quiz and can't grant access to yourself."
            }, status=400)

        # Check for existing access
        existing_access = QuizAccess.objects.filter(quiz=quiz, participant=target).first()
        if existing_access:
            if existing_access.access_type == access_type:
                return JsonResponse({
                    "error": f"✅ {target.username or target.telegram_id} already has *{access_type}* access to this quiz."
                }, status=400)
            else:
                # Update the access type
                existing_access.access_type = access_type
                existing_access.granted_by = granter
                existing_access.save()
                return JsonResponse({
                    "message": f"🔁 Access level for *{target.username or target.telegram_id}* has been updated to *{access_type}*.",
                    "updated": True
                })

        # Grant new access
        QuizAccess.objects.create(
            quiz=quiz,
            participant=target,
            access_type=access_type,
            granted_by=granter
        )

        return JsonResponse({
            "message": f"✅ Successfully granted *{access_type}* access to *{target.username or target.telegram_id}*.",
            "created": True
        })

    except json.JSONDecodeError:
        return JsonResponse({"error": "❌ There was a problem reading the request. Please try again."}, status=400)
    
@csrf_exempt
def get_quiz_access_list(request):
    quiz_id = request.GET.get("quiz_id")
    if not quiz_id:
        return JsonResponse({"error": "Missing quiz_id"}, status=400)

    try:
        quiz = Quiz.objects.get(id=quiz_id)
    except Quiz.DoesNotExist:
        return JsonResponse({"error": "Quiz not found"}, status=404)

    access_list = []

    # Include the creator
    if quiz.participant:
        access_list.append({
            "telegram_id": quiz.participant.telegram_id,
            "username": quiz.participant.username,
            "access_type": "full_access",
            "granted_by": None,
            "granted_at": quiz.created_date.isoformat() if quiz.created_date else None
        })

    # Include all granted access users
    for access in quiz.accesses.select_related("participant", "granted_by"):
        access_list.append({
            "telegram_id": access.participant.telegram_id,
            "username": access.participant.username,
            "access_type": access.access_type,
            "granted_by": access.granted_by.telegram_id if access.granted_by else None,
            "granted_at": access.granted_at.isoformat() if access.granted_at else None
        })

    return JsonResponse(access_list, safe=False)