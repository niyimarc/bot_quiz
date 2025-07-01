from django.urls import path
from .views import get_quizzes, continue_session, process_message, get_participated_quizzes

urlpatterns = [
    path('quiz/get_quizzes/', get_quizzes),
    path("quiz/continue_session/", continue_session),
    path("quiz/process_message/", process_message),
    path("quiz/get_participated_quizzes/", get_participated_quizzes),
]
