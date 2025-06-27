from django.urls import path
from .views import quiz_questions_api, telegram_webhook

urlpatterns = [
    path('quiz/questions/', quiz_questions_api),
    path("webhook/bot_webhook/", telegram_webhook, name="telegram-webhook"),
]
