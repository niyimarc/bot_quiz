from django.http import JsonResponse, HttpResponse
from .utils import get_questions_from_sheet
from .models import Quiz
from django.views.decorators.csrf import csrf_exempt
from bot import telegram_app
from telegram import Update

@csrf_exempt
def telegram_webhook(request):
    print("📩 Telegram update received")
    if request.method == "POST":
        update = Update.de_json(request.body.decode("utf-8"), telegram_app.bot)
        telegram_app.update_queue.put(update)
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
