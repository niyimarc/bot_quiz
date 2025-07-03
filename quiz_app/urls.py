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
    get_my_quizzes,
    update_quiz_status,
    delete_quiz,
    edit_quiz_name,
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
    path("quiz/get_my_quizzes/", get_my_quizzes),
    path("quiz/update_quiz_status/", update_quiz_status),
    path('quiz/delete_quiz/', delete_quiz),
    path('quiz/edit_quiz_name/', edit_quiz_name),
]
