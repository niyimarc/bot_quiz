from django.http import JsonResponse
from django.db.models import Count, Q
from django.utils import timezone
from django.contrib.auth.models import User
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
        user = request.user 
        if not user:
            return JsonResponse({"error": "Missing user"}, status=400)

        unfinished_scores = QuizScore.objects.filter(participant=user, end_time__isnull=True)
        if not unfinished_scores.exists():
            return JsonResponse({"error": "No unfinished quizzes found."}, status=404)

        options = []
        for score in unfinished_scores:
            session = QuizSession.objects.filter(score_obj=score, participant=user, active=True).first()
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

class ResumeQuizView(PrivateUserViewMixin, APIView):
    def get(self, request, session_id):
        user = request.user

        try:
            session = QuizSession.objects.get(id=session_id, participant=user, active=True)
        except QuizSession.DoesNotExist:
            return Response({"error": "Active session not found"}, status=404)

        all_questions = session.questions
        index = session.index  # current question index

        # Sanitize all questions (optional: only number, text, options)
        sanitized_questions = [
            {
                "number": q["number"],
                "text": q["text"],
                "options": q["options"],
            } for q in all_questions
        ]

        return Response({
            "session_id": session.id,
            "quiz_name": session.quiz.name,
            "total_questions": len(all_questions),
            "questions": sanitized_questions,  # full list
            "current_question_index": index,    # JS will use this
            "progress": f"Question {index + 1} of {len(all_questions)}"
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

class StartRetryView(PrivateUserViewMixin, APIView):
    def post(self, request):
        user = request.user
        score_id = request.data.get("score_id")

        if not user or not score_id:
            return Response({"error": "Missing user or score_id"}, status=400)

        try:
            original_score = QuizScore.objects.get(id=score_id, participant=user)
        except QuizScore.DoesNotExist:
            return Response({"error": "Quiz score not found"}, status=404)

        missed = original_score.missed_questions or []
        if not missed:
            return Response({"error": "No missed questions to retry"}, status=400)

        # Convert old/new formats to 0-based indexes
        missed_indexes = [
            i-1 if isinstance(i, int) else i["index"]-1
            for i in missed
        ]
        all_questions = get_questions_from_sheet(original_score.quiz.sheet_url)
        retry_questions = [all_questions[i] for i in missed_indexes]

        # Create retry session
        retry = RetryQuizScore.objects.create(
            original_score=original_score,
            missed_questions=missed_indexes,
            total_questions=len(missed_indexes),
            score=0,
            index=0
        )
        # Clear any existing retry session
        RetrySession.objects.filter(participant=user).update(active=False, expecting_answer=False)
        RetrySession.objects.create(
            participant=user,
            retry=retry,
            active=True,
            expecting_answer=True
        )

        # Sanitize questions for frontend
        sanitized_questions = [
            {"number": q["number"], "text": q["text"], "options": q["options"]}
            for q in retry_questions
        ]

        return Response({
            "session_id": retry.id,  # use same key as StartQuiz/ResumeQuiz
            "score_id": original_score.id,
            "quiz_name": original_score.quiz.name,
            "questions": sanitized_questions,
            "total_questions": len(sanitized_questions),
            "current_question_index": 0,
            "progress": f"Question 1 of {len(sanitized_questions)}"
        })

class SubmitRetryAnswerView(PrivateUserViewMixin, APIView):
    def post(self, request):
        user = request.user
        session_id = request.data.get("session_id")
        answer = request.data.get("answer")
        question_index = request.data.get("question_index")

        try:
            session = RetrySession.objects.get(participant=user, active=True)
        except RetrySession.DoesNotExist:
            return Response({"error": "Retry session not found"}, status=404)

        retry = session.retry
        all_questions = get_questions_from_sheet(retry.original_score.quiz.sheet_url)
        retry_questions = [all_questions[i] for i in retry.missed_questions]

        if question_index >= len(retry_questions):
            return Response({"error": "Invalid question index"}, status=400)

        question = retry_questions[question_index]

        # Ensure correct key
        correct_answer = question.get("correct_answer") or question.get("correct") or question.get("answer")
        if correct_answer is None:
            return Response({"error": "Question missing correct answer"}, status=500)

        # Normalize for comparison
        normalized_answer = answer.strip().upper()
        normalized_correct = correct_answer.strip().upper()

        is_correct = normalized_answer.startswith(normalized_correct)

        # Update retry score and index
        retry.index += 1
        if not hasattr(retry, "missed_questions_details"):
            retry.missed_questions_details = []

        if not is_correct:
            retry.missed_questions_details.append({
                "index": question_index,
                "question": question["text"]
            })
        else:
            retry.score += 1

        retry.save()

        # End session if finished
        finished = retry.index >= len(retry_questions)
        if finished:
            session.active = False
            session.expecting_answer = False
            session.save()

        return Response({
            "type": "feedback" if not finished else "complete",
            "correct": is_correct,
            "correct_answer": correct_answer,
            "next_question_index": retry.index,
            "finished": finished,
            "question_text": question["text"],
        })

class RetryableScoresView(PrivateUserViewMixin, APIView):
    def get(self, request):
        user = request.user
        if not user:
            return JsonResponse({"error": "Missing user"}, status=400)

        retryable = []
        scores = QuizScore.objects.filter(participant=user).order_by("-attempt_time")
        for score in scores:
            missed = score.missed_questions or []
            if not missed:
                continue

            retryable.append({
                "score_id": score.id,
                "quiz_name": score.quiz.name,
                "missed_count": len(missed),
            })

        return JsonResponse({
            "message": "📚 Quizzes with missed questions available for retry:",
            "options": retryable
        })

class RetrySessionView(PrivateUserViewMixin, APIView):
    def get(self, request, session_id):
        user = request.user
        if not user:
            return Response({"error": "Missing user"}, status=400)

        try:
            retry = RetryQuizScore.objects.get(id=session_id, retrysession__participant=user, retrysession__active=True)
        except RetryQuizScore.DoesNotExist:
            return Response({"error": "Active retry session not found"}, status=404)

        all_questions = get_questions_from_sheet(retry.original_score.quiz.sheet_url)
        missed_indexes = retry.missed_questions
        retry_questions = [all_questions[i] for i in missed_indexes]

        # Current question
        index = retry.index
        sanitized_questions = [
            {"number": q["number"], "text": q["text"], "options": q["options"]}
            for q in retry_questions
        ]

        return Response({
            "session_id": retry.id,
            "quiz_name": retry.original_score.quiz.name,
            "questions": sanitized_questions,
            "total_questions": len(sanitized_questions),
            "current_question_index": index,
            "progress": f"Question {index + 1} of {len(sanitized_questions)}"
        })
    
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
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return Response({"error": "Invalid JSON"}, status=400)
        else:
            print("Data is already parsed:", data, type(data))

        user = request.user
        name = data.get("name")
        sheet_url = data.get("sheet_url")
        status = data.get("status", "public").lower()

        # Normalize category_ids
        raw_category_ids = data.get("category_ids", [])

        if isinstance(raw_category_ids, (str, int)):
            raw_category_ids = [raw_category_ids]
        try:
            category_ids = [int(cid) for cid in raw_category_ids if cid]
        except ValueError:
            return Response({"error": "Invalid category_ids"}, status=400)

        # Validate required fields
        if not all([name, sheet_url]):
            return Response({"error": "Missing required fields"}, status=400)

        if status not in ["public", "private"]:
            return Response({"error": "Invalid status. Must be 'public' or 'private'"}, status=400)

        # Check duplicate quiz name
        if Quiz.objects.filter(name=name).exists():
            return Response({"error": "A quiz with this name already exists."}, status=400)
        
        if Quiz.objects.filter(sheet_url=sheet_url).exists():
            return Response({"error": "A quiz with this sheet URL already exists."}, status=400)

        # Fetch questions from sheet
        try:
            questions = get_questions_from_sheet(sheet_url)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        # Create quiz
        quiz = Quiz.objects.create(
            name=name,
            sheet_url=sheet_url,
            status=status,
            participant=user,
            is_active=True
        )

        # Assign categories safely
        if category_ids:
            valid_ids = list(quiz.category.model.objects.filter(id__in=category_ids).values_list('id', flat=True))
            if valid_ids:
                quiz.category.set(valid_ids)

        serializer = QuizSerializer(quiz)
        return Response({
            "message": f"✅ Quiz '{quiz.name}' created successfully.",
            "quiz": serializer.data
        })

class MyQuizzesView(PrivateUserViewMixin, ListAPIView):
    serializer_class = QuizSerializer
    pagination_class = QuizPagination

    def get_queryset(self):
        user = self.request.user
        category_id = self.request.GET.get("category_id")
        search = self.request.GET.get("search", "").strip()

        queryset = Quiz.objects.filter(participant=user).order_by("-id")

        if category_id:
            queryset = queryset.filter(category__id=category_id)

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(category__name__icontains=search)
            )

        return queryset.distinct()

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
            # Resolve or create target user
            target = User.objects.filter(username__iexact=target_username).first()
            if not target:
                target = User.objects.create(username=target_username)

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

        # Only quiz owner can view access list
        if not (quiz.participant == request.user or quiz.get_access_type(request.user) == "full_access"):
            return Response({"error": "Not authorized"}, status=403)

        accesses = quiz.accesses.select_related("participant", "granted_by")
        serializer = QuizAccessSerializer(accesses, many=True)
        return Response(serializer.data)
