from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from auth_core.views import PrivateUserViewMixin, PublicViewMixin
from .serializers import QuizSerializer, QuizScoreSerializer, QuizCategorySerializer, QuizAccessSerializer
from .models import Quiz, QuizScore, QuizSession, RetryQuizScore, RetrySession, QuizAccess, QuizCategory
from .utils import get_questions_from_sheet, normalize, clear_participant_retry_session
import json
import logging
logger = logging.getLogger(__name__)

class CategoriesWithQuizzesView(PrivateUserViewMixin, APIView):
    def get(self, request):
        user = request.user
        quizzes = Quiz.objects.available_to_user(user)
        category_ids = quizzes.values_list('category__id', flat=True).distinct()
        categories = QuizCategory.objects.filter(id__in=category_ids)
        serializer = QuizCategorySerializer(categories, many=True)
        return Response({"categories": serializer.data})

class QuizzesByCategoryView(PrivateUserViewMixin, APIView):
    def get(self, request, *args, **kwargs):
        user = request.user
        category_id = request.GET.get("category_id")
        if not category_id:
            return Response({"error": "category_id is required"}, status=400)

        quizzes = Quiz.objects.filter(is_active=True, category__id=category_id).distinct()
        accessible = [q.name for q in quizzes if q.is_accessible_by(user)]
        return Response(accessible)

class GetQuizzesView(PrivateUserViewMixin, APIView):
    def get(self, request, *args, **kwargs):
        category_id = request.GET.get("category_id")
        if not category_id:
            return Response({"error": "category_id is required"}, status=400)

        quizzes = Quiz.objects.filter(is_active=True, category_id=category_id)
        data = [{"id": q.id, "name": q.name} for q in quizzes]
        return Response(data)

class ContinueSessionView(PrivateUserViewMixin, APIView):
    def get(self, request):
        user = request.GET.get("user")
        if not user:
            return JsonResponse({"error": "Missing user"}, status=400)

        unfinished_scores = QuizScore.objects.filter(user=user, end_time__isnull=True)
        if not unfinished_scores.exists():
            return JsonResponse({"error": "No unfinished quizzes found."}, status=404)

        options = []
        for score in unfinished_scores:
            session = QuizSession.objects.filter(score_obj=score, user=user, active=True).first()
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

class ProcessMessageView(PrivateUserViewMixin, APIView):
    def post(self, request):
        try:
            user = request.data.get("user")
            text = request.data.get("text")
            explicit_session_id = request.data.get("session_id")  # <- NEW

            if not user or not text:
                return JsonResponse({"error": "Missing user or text"}, status=400)

            # Handle RESUME__<session_id>
            if text.startswith("RESUME__"):
                session_id = text.replace("RESUME__", "").split("|")[0].strip()
                try:
                    session = QuizSession.objects.get(id=session_id, participant=user, active=True)
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
                    "session_id": session.id
                })

            # Handle new quiz start
            quiz = Quiz.objects.filter(name=text, is_active=True).first()
            if quiz:
                # Clean up stale retry sessions
                RetrySession.objects.filter(participant=user).update(active=False, expecting_answer=False)
                if not quiz.is_accessible_by(user):
                    return JsonResponse({"error": "This quiz is private and you do not have access."}, status=403)

                questions = get_questions_from_sheet(quiz.sheet_url)
                score = QuizScore.objects.create(participant=user, quiz=quiz, total_questions=len(questions))
                session = QuizSession.objects.create(
                    participant=user,
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
                    "session_id": session.id
                })

            # Continue existing session
            session = None
            if explicit_session_id:
                session = QuizSession.objects.filter(id=explicit_session_id, participant=user, active=True).first()
            if not session:
                session = QuizSession.objects.filter(participant=user, active=True).first()

            if not session:
                return JsonResponse({"error": "No active session."}, status=404)

            # Completed session
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
                    "session_id": session.id
                })

            # Evaluate current question
            question = session.questions[session.index]
            user_input = normalize(text)
            correct_answer = normalize(question["correct"])
            options = question["options"]
            normalized_options = [normalize(opt) for opt in options]

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
                if not isinstance(session.score_obj.missed_questions, list):
                    session.score_obj.missed_questions = []
                session.score_obj.missed_questions.append({
                    "index": session.index + 1,
                    "selected": text.strip()
                })

            session.index += 1
            session.score_obj.save()
            session.save()

            # Completed after this answer
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
        
class ParticipatedQuizzesView(PrivateUserViewMixin, APIView):
    def get(self, request):
        user = request.user
        scores = QuizScore.objects.filter(participant=user)
        serializer = QuizScoreSerializer(scores, many=True)
        return Response(serializer.data)

class RetryMissedQuestionView(PrivateUserViewMixin, APIView):
    def post(self, request):
        user = request.user
        original_score_id = request.data.get("score_id")
        answer = request.data.get("answer")

        if not user or not original_score_id:
            return JsonResponse({"error": "Missing user or score_id"}, status=400)

        try:
            original_score = QuizScore.objects.get(id=original_score_id, user=user)
        except QuizScore.DoesNotExist:
            return JsonResponse({"error": "User or quiz score not found"}, status=404)

        all_questions = get_questions_from_sheet(original_score.quiz.sheet_url)
        raw_missed = original_score.missed_questions or []

        # Support both old (int) and new (dict) formats
        missed_questions = []
        for item in raw_missed:
            if isinstance(item, int) and item > 0:
                missed_questions.append(item - 1)  # old format (1-based to 0-based)
            elif isinstance(item, dict) and "index" in item and isinstance(item["index"], int):
                missed_questions.append(item["index"] - 1)  # new format

        if any(i >= len(all_questions) or i < 0 for i in missed_questions):
            return JsonResponse({
                "error": "⚠️ The quiz content has changed since your last attempt. Retry session closed."
            }, status=400)

        # Check for an active retry session first
        retry_session = RetrySession.objects.filter(user=user, active=True).first()
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
            clear_participant_retry_session(user)
            RetrySession.objects.create(
                user=user,
                retry=retry,
                active=True,
                expecting_answer=True
            )

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

        # If session complete
        if retry.index >= retry.total_questions:
            retry.end_time = timezone.now()
            retry.save()
            clear_participant_retry_session(user)
            return JsonResponse({
                "type": "complete",
                "feedback": feedback,
                "final_score": retry.score,
                "total_questions": retry.total_questions,
                "message": f"🎉 Congratulations on completing your retry session!\n\n"
                           f"✅ Final Score: {retry.score}/{retry.total_questions}\n"
                           f"📚 Keep practicing to improve even more!"
            })

        # Otherwise next question
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

class RetryableScoresView(PrivateUserViewMixin, APIView):
    def get(self, request):
        user = request.user
        if not user:
            return JsonResponse({"error": "Missing user"}, status=400)

        retryable = []

        scores = QuizScore.objects.filter(user=user).order_by("-attempt_time")
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

class RetrySessionStatusView(PrivateUserViewMixin, APIView):
    def get(self, request):
        user = request.user
        if not user:
            return JsonResponse({"error": "Missing user"}, status=400)

        try:
            session = RetrySession.objects.filter(
                user=user, active=True, expecting_answer=True
            ).latest("updated_at")

            return JsonResponse({
                "score_id": session.retry.original_score.id,
                "retry_id": session.retry.id,
                "expecting_answer": session.expecting_answer,
            })
        except RetrySession.DoesNotExist:
            return JsonResponse({})
    
class ClearRetrySessionView(PrivateUserViewMixin, APIView):
    def get(self, request):
        user = request.user
        if not user:
            return JsonResponse({"error": "Missing user"}, status=400)

        RetrySession.objects.filter(user=user).update(active=False, expecting_answer=False)
        return JsonResponse({"status": "cleared"})

class ListCategoriesView(PrivateUserViewMixin, APIView):
    def get(self, request):
        categories = QuizCategory.objects.all()
        serializer = QuizCategorySerializer(categories, many=True)
        return Response({"categories": serializer.data})

class AddQuizView(PrivateUserViewMixin, APIView):
    def post(self, request):
        data = request.data
        user = request.user

        name = data.get("name")
        sheet_url = data.get("sheet_url")
        status = data.get("status", "public").lower()
        category_ids = data.get("category_ids", [])

        if not all([name, sheet_url]):
            return Response({"error": "Missing required fields"}, status=400)

        if status not in ["public", "private"]:
            return Response({"error": "Invalid status. Must be 'public' or 'private'"}, status=400)

        if Quiz.objects.filter(name=name).exists():
            return Response({"error": "A quiz with this name already exists."}, status=400)

        from .utils import get_questions_from_sheet
        try:
            questions = get_questions_from_sheet(sheet_url)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        quiz = Quiz.objects.create(name=name, sheet_url=sheet_url, status=status, participant=user, is_active=True)
        if category_ids:
            quiz.category.set(category_ids)

        serializer = QuizSerializer(quiz)
        return Response({"message": f"✅ Quiz '{quiz.name}' created successfully.", "quiz": serializer.data})

class MyQuizzesView(PrivateUserViewMixin, APIView):
    def get(self, request):
        user = request.user
        quizzes = Quiz.objects.filter(participant=user).order_by("-id")
        serializer = QuizSerializer(quizzes, many=True)
        return Response(serializer.data)

class UpdateQuizStatusView(PrivateUserViewMixin, APIView):
    def post(self, request):
        user = request.user
        if not user:
            return JsonResponse({"error": "Missing user"}, status=400)

        quiz_id = request.data.get("quiz_id")
        new_status = request.data.get("new_status")

        if not all([quiz_id, new_status]):
            return JsonResponse({"error": "Missing required fields"}, status=400)

        if new_status not in ["public", "private"]:
            return JsonResponse({"error": "Invalid status. Must be 'public' or 'private'"}, status=400)

        try:
            quiz = Quiz.objects.get(id=quiz_id, participant=user)
        except Quiz.DoesNotExist:
            return JsonResponse({"error": "Quiz not found or does not belong to you"}, status=404)

        quiz.status = new_status
        quiz.save()

        return JsonResponse({
            "message": f"✅ Quiz '{quiz.name}' status updated to '{quiz.status}' successfully."
        })

class DeleteQuizView(PrivateUserViewMixin, APIView):
    def post(self, request):
        user = request.user
        if not user:
            return JsonResponse({"error": "Missing user"}, status=400)

        quiz_id = request.data.get("quiz_id")
        if not quiz_id:
            return JsonResponse({"error": "Missing quiz_id"}, status=400)

        try:
            quiz = Quiz.objects.get(pk=quiz_id)
            if quiz.participant != user:
                return JsonResponse({"error": "Unauthorized"}, status=403)

            quiz.delete()
            return JsonResponse({"success": True})

        except Quiz.DoesNotExist:
            return JsonResponse({"error": "Quiz not found"}, status=404)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    
class EditQuizNameView(PrivateUserViewMixin, APIView):
    def post(self, request):
        user = request.user
        if not user:
            return JsonResponse({"error": "Missing user"}, status=400)

        try:
            quiz_id = int(request.data.get('quiz_id'))
            new_name = request.data.get('new_name', '').strip()

            if not new_name:
                return JsonResponse({'error': 'New name is required'}, status=400)

            quiz = Quiz.objects.get(pk=quiz_id)

            if quiz.participant != user:
                return JsonResponse({'error': 'Unauthorized'}, status=403)

            quiz.name = new_name
            quiz.save()

            return JsonResponse({'success': True, 'new_name': new_name})

        except Quiz.DoesNotExist:
            return JsonResponse({'error': 'Quiz not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

class GrantQuizAccessView(PrivateUserViewMixin, APIView):
    def post(self, request):
        user = request.user
        if not user:
            return JsonResponse({"error": "Missing user"}, status=400)

        try:
            data = request.data
            target_username = data.get("target_username", "").lstrip("@").lower()
            quiz_id = data.get("quiz_id")
            access_type = data.get("access_type", "participate_access")

            if not all([quiz_id, access_type]) or not target_username:
                return JsonResponse({"error": "⚠️ Missing required details. Please provide all necessary information."}, status=400)

            quiz = Quiz.objects.filter(id=quiz_id).first()
            if not quiz:
                return JsonResponse({"error": "❗️ This quiz doesn't seem to exist."}, status=404)

            if not (quiz.participant == user or quiz.get_access_type(user) == "full_access"):
                return JsonResponse({"error": "🚫 You don't have permission to manage access for this quiz."}, status=403)

            # Resolve or create target
            target = None
            target = Quiz.objects.filter(participant__username__iexact=target_username).first()
            if not target:
                # create target user placeholder if necessary
                from django.contrib.auth.models import User
                target_user = User.objects.create(username=target_username)
                target = target_user

            if quiz.participant == target:
                return JsonResponse({
                    "error": "👤 You already have access to this quiz and can't grant access to yourself."
                }, status=400)

            # Check for existing access
            existing_access = QuizAccess.objects.filter(quiz=quiz, participant=target).first()
            if existing_access:
                if existing_access.access_type == access_type:
                    return JsonResponse({
                        "error": f"✅ {target.username} already has *{access_type}* access to this quiz."
                    }, status=400)
                else:
                    existing_access.access_type = access_type
                    existing_access.granted_by = user
                    existing_access.save()
                    return JsonResponse({
                        "message": f"🔁 Access level for *{target.username}* has been updated to *{access_type}*.",
                        "updated": True
                    })

            # Grant new access
            QuizAccess.objects.create(
                quiz=quiz,
                participant=target,
                access_type=access_type,
                granted_by=user
            )

            return JsonResponse({
                "message": f"✅ Successfully granted *{access_type}* access to *{target.username}*.",
                "created": True
            })

        except json.JSONDecodeError:
            return JsonResponse({"error": "❌ There was a problem reading the request. Please try again."}, status=400)

class QuizAccessListView(PrivateUserViewMixin, APIView):
    def get(self, request):
        quiz_id = request.GET.get("quiz_id")
        if not quiz_id:
            return Response({"error": "Missing quiz_id"}, status=400)

        try:
            quiz = Quiz.objects.get(id=quiz_id)
        except Quiz.DoesNotExist:
            return Response({"error": "Quiz not found"}, status=404)

        accesses = quiz.accesses.select_related("participant", "granted_by")
        serializer = QuizAccessSerializer(accesses, many=True)
        return Response(serializer.data)