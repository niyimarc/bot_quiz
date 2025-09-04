from django.http import JsonResponse
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework import status
from auth_core.views import PrivateUserViewMixin, PublicViewMixin
from .serializers import QuizSerializer, QuizScoreSerializer, QuizCategorySerializer, QuizAccessSerializer
from .models import Quiz, QuizScore, QuizSession, RetryQuizScore, RetrySession, QuizAccess, QuizCategory
from .utils import get_questions_from_sheet, normalize, clear_participant_retry_session
from .pagination import QuizPagination
from django.shortcuts import get_object_or_404
import json
import logging
logger = logging.getLogger(__name__)

class CategoriesWithQuizzesView(PrivateUserViewMixin, APIView):
    def get(self, request):
        user = request.user
        quizzes = Quiz.objects.available_to_user(user)
        categories = (
            QuizCategory.objects
            .filter(id__in=quizzes.values_list("category", flat=True))
            .annotate(quiz_count=Count("quiz", filter=Q(quiz__in=quizzes)))
        )
        serializer = QuizCategorySerializer(categories, many=True)
        return Response({"categories": serializer.data})

class GetAccessibleQuizzesView(PrivateUserViewMixin, ListAPIView):
    serializer_class = QuizSerializer
    pagination_class = QuizPagination

    def get_queryset(self):
        user = self.request.user
        category_id = self.request.GET.get("category_id")
        search = self.request.GET.get("search", "").strip()

        queryset = Quiz.objects.available_to_user(user).filter(is_active=True)

        if category_id:
            queryset = queryset.filter(category__id=category_id)

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(category__name__icontains=search)
            )

        return queryset.distinct()


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


class StartQuizView(PrivateUserViewMixin, APIView):
    def post(self, request):
        user = request.user
        quiz_id = request.data.get("quiz_id")

        if not quiz_id:
            return Response({"error": "quiz_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            quiz = Quiz.objects.get(id=quiz_id, is_active=True)
        except Quiz.DoesNotExist:
            return Response({"error": "Quiz not found or inactive"}, status=status.HTTP_404_NOT_FOUND)

        # Ensure user has access
        if not quiz.is_accessible_by(user):
            return Response(
                {"error": "This quiz is private and you do not have access."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Clean up stale retry sessions
        RetrySession.objects.filter(participant=user).update(active=False, expecting_answer=False)

        # Load questions
        all_questions = get_questions_from_sheet(quiz.sheet_url)

        # Create score and session
        score = QuizScore.objects.create(
            participant=user,
            quiz=quiz,
            total_questions=len(all_questions),
            score=0,
            start_time=timezone.now()
        )
        session = QuizSession.objects.create(
            participant=user,
            quiz=quiz,
            score_obj=score,
            questions=all_questions,  # store full set including correct
            index=0,
            active=True,
        )

        sanitized_questions = [
            {
                "number": q["number"],
                "text": q["text"],
                "options": q["options"],
            }
            for q in all_questions
        ]

        return Response({
            "session_id": session.id,
            "quiz_name": quiz.name,
            "total_questions": len(all_questions),
            "questions": sanitized_questions,  # frontend will cache these
            "progress": f"Question 1 of {len(all_questions)}",
        }, status=status.HTTP_201_CREATED)


class SubmitQuizAnswerView(PrivateUserViewMixin, APIView):
    def post(self, request):
        user = request.user
        session_id = request.data.get("session_id")
        answer = request.data.get("answer")
        # print(f"Submitted Answer: {answer}")
        if not session_id:
            return Response({"error": "session_id is required"}, status=400)

        try:
            session = QuizSession.objects.get(id=session_id, participant=user, active=True)
        except QuizSession.DoesNotExist:
            return Response({"error": "Active session not found"}, status=404)

        all_questions = session.questions  # already stored at start
        if session.index >= len(all_questions):
            return Response({"error": "Quiz already completed"}, status=400)

        current_question = all_questions[session.index]

        if not answer:
            return Response({
                "type": "question",
                "message": current_question["text"],
                "options": current_question["options"],
                "progress": f"Question {session.index + 1} of {len(all_questions)}",
                "session_id": session.id,
            })

        # Normalize for comparison
        normalized_answer = answer.strip().upper()
        correct_answer = current_question["correct"].strip().upper()
        # print(f"Correct Answer: {correct_answer}")
        feedback = f"Q{session.index + 1}: {current_question['text']}\nYour Answer: {answer}\n"

        if normalized_answer.startswith(correct_answer):
            session.score += 1
            session.score_obj.score = session.score
            feedback += "✅ Correct!"
        else:
            # Record missed question
            session.score_obj.missed_questions.append({
                "index": session.index,
                "question": current_question["text"]
            })
            feedback += f"❌ Incorrect. Correct answer: {current_question['correct']}"

        session.index += 1
        session.score_obj.save()
        session.save()

        # If finished
        if session.index >= len(all_questions):
            session.active = False
            session.score_obj.end_time = timezone.now()
            session.score_obj.save()
            session.save()

            return Response({
                "type": "complete",
                "final_score": session.score,
                "total_questions": len(all_questions),
                "message": f"🎉 You completed the quiz!\nScore: {session.score}/{len(all_questions)}",
                "correct_answer": current_question["correct"],  # add this
                "correct": normalized_answer.startswith(correct_answer),
            })

        # Otherwise next question
        next_question = all_questions[session.index]
        return Response({
            "type": "feedback",
            "feedback": feedback,
            "next_question": {
                "text": next_question["text"],
                "options": next_question["options"],
            },
            "correct_answer": current_question["correct"],
            "correct": normalized_answer.startswith(correct_answer),
            "progress": f"Question {session.index + 1} of {len(all_questions)}",
            "session_id": session.id,
        })

    
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