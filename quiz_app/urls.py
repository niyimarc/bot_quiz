from django.urls import path
from .views import (
    get_quizzes, 
    continue_session, 
    process_message, 
    get_participated_quizzes, 
    retry_missed_question, 
    get_retryable_scores, 
    retry_session_status,
    clear_retry_session,
    add_quiz,
    )

urlpatterns = [
    path('quiz/get_quizzes/', get_quizzes),
    path("quiz/continue_session/", continue_session),
    path("quiz/process_message/", process_message),
    path("quiz/get_participated_quizzes/", get_participated_quizzes),
    path("quiz/retry_missed_question/", retry_missed_question),
    path("quiz/get_retryable_scores/", get_retryable_scores),
    path("quiz/retry_session_status/", retry_session_status),
    path("quiz/clear_retry_session/", clear_retry_session),
    path("quiz/add_quiz/", add_quiz),
]
