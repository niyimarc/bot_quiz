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
import asyncio

logger = logging.getLogger(__name__)
@csrf_exempt
def telegram_webhook(request):
    print("Telegram update received")
    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8"))
            update = Update.de_json(data, telegram_app.bot)

            async def process():
                if not telegram_app._initialized:
                    await telegram_app.initialize()
                await telegram_app.process_update(update)

            # ✅ Create a new event loop in this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(process())

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
