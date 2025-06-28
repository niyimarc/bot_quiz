from django.http import JsonResponse, HttpResponse
from .utils import get_questions_from_sheet
from .models import Quiz
from django.views.decorators.csrf import csrf_exempt
from bot import telegram_app
print("bot.py has been imported")
from telegram import Update
import json
import logging
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)
@csrf_exempt
def telegram_webhook(request):
    print("Telegram update received")
    if request.method == "POST":
        try:
            body_raw = request.body.decode("utf-8")
            data = json.loads(body_raw)
            update = Update.de_json(data, telegram_app.bot)

            # ✅ Schedule update to PTB's own event loop
            telegram_app.create_task(telegram_app.process_update(update))

            return HttpResponse("OK")

        except Exception:
            import traceback
            print("Error handling Telegram webhook:")
            print(traceback.format_exc())
            return HttpResponse("Error", status=500)
    return HttpResponse("OK")

def quiz_questions_api(request):
    quiz_name = request.GET.get("quiz")
    if not quiz_name:
        return JsonResponse({"error": "Missing quiz name"}, status=400)
    
    try:
        quiz = Quiz.objects.get(name=quiz_name, is_active=True)
    except Quiz.DoesNotExist:
        return JsonResponse({
            "error": "Invalid or inactive quiz name.",
            "available_quizzes": list(Quiz.objects.filter(is_active=True).values_list("name", flat=True))
        }, status=400)
    questions = get_questions_from_sheet(quiz.sheet_url)
    return JsonResponse(questions, safe=False)
