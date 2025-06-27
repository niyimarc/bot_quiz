import os
import requests
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from urllib.parse import urlencode
from asgiref.sync import sync_to_async
from django.utils import timezone
import re

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quiz_project.settings")
import django
django.setup()
from quiz_app.models import Quiz, QuizParticipant, QuizScore

# Load env vars
load_dotenv()
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_URL = os.environ.get("API_URL").rstrip("/")





def escape_markdown(text):
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', text)
# --- Helper: API call ---
def fetch_questions_from_api(quiz_name):
    try:
        url = f"{API_URL}/?{urlencode({'quiz': quiz_name})}"
        print("📡 Calling API URL:", url)
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        print("❌ API error:", response.status_code, response.text)
    except Exception as e:
        print("❌ Request failed:", e)
    return []

# --- Async DB Access ---
@sync_to_async
def get_quiz_names():
    return list(Quiz.objects.filter(is_active=True).values_list("name", flat=True))

@sync_to_async
def get_quiz_by_name(name):
    return Quiz.objects.filter(name=name, is_active=True).first()

@sync_to_async
def get_or_create_participant(user):
    return QuizParticipant.objects.get_or_create(
        telegram_id=user.id,
        defaults={
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name
        }
    )

@sync_to_async
def get_participant_by_telegram_id(tid):
    return QuizParticipant.objects.filter(telegram_id=tid).first()

@sync_to_async
def get_unfinished_score(participant):
    return QuizScore.objects.filter(participant=participant, end_time__isnull=True).first()

@sync_to_async
def create_score(participant, quiz, total):
    return QuizScore.objects.create(
        participant=participant,
        quiz=quiz,
        total_questions=total,
        start_time=timezone.now()
    )

@sync_to_async
def get_quiz_name_from_score(score):
    return score.quiz.name

@sync_to_async
def get_score_by_id(score_id):
    return QuizScore.objects.get(id=score_id)

@sync_to_async
def update_score(score_obj, new_score, ended=False):
    score_obj.score = new_score
    if ended:
        score_obj.end_time = timezone.now()
    score_obj.save()

# --- Session ---
user_sessions = {}

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name or "there"
    intro_text = (
        f"👋 Hello {user}!\n\n"
        "Welcome to the *Quiz Bot*! 🧠\n\n"
        "Here's how it works:\n"
        "1. You'll select a quiz from the available list.\n"
        "2. Questions will be shown one by one.\n"
        "3. After answering each, you'll get immediate feedback.\n"
        "4. Your score will be saved and shown at the end.\n\n"
        "You can also use /continue to resume an unfinished quiz.\n\n"
        "💬 Need help or have feedback? Message the developer at @drey_tech\n\n"
        "👇 Choose a quiz to begin:"
    )

    quizzes = await get_quiz_names()
    if not quizzes:
        await update.message.reply_text("⚠️ No active quizzes available.")
        return
    keyboard = [[KeyboardButton(name)] for name in quizzes]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(escape_markdown(intro_text), reply_markup=markup, parse_mode="MarkdownV2")

async def continue_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    participant = await get_participant_by_telegram_id(user_id)
    if not participant:
        await update.message.reply_text("You haven’t started any quiz yet. Use /start to begin.")
        return

    unfinished = await get_unfinished_score(participant)
    if not unfinished:
        await update.message.reply_text("🎉 You have no quiz in progress. Use /start to begin a new one.")
        return

    quiz_name = await get_quiz_name_from_score(unfinished)
    questions = fetch_questions_from_api(quiz_name)
    if not questions:
        await update.message.reply_text("❌ Could not reload quiz data.")
        return

    user_sessions[user_id] = {
        "quiz_name": quiz_name,
        "questions": questions,
        "index": unfinished.score,
        "score": unfinished.score,
        "score_obj_id": unfinished.id
    }

    await update.message.reply_text(f"🔁 Resuming quiz: {quiz_name}")
    await send_question(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        await handle_answer(update, context)
    else:
        await select_quiz(update, context)

async def select_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    quiz_name = update.message.text.strip()

    quiz = await get_quiz_by_name(quiz_name)
    if not quiz:
        await update.message.reply_text("❌ Invalid or inactive quiz. Use /start to try again.")
        return

    questions = fetch_questions_from_api(quiz_name)
    if not questions:
        await update.message.reply_text("❌ Failed to load quiz questions.")
        return

    participant, _ = await get_or_create_participant(user)
    score_obj = await create_score(participant, quiz, len(questions))

    user_sessions[user.id] = {
        "quiz_name": quiz_name,
        "questions": questions,
        "index": 0,
        "score": 0,
        "score_obj_id": score_obj.id
    }

    await update.message.reply_text(f"🧠 Starting quiz: {quiz_name}")
    await send_question(update, context)

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    if not session:
        await update.message.reply_text("No quiz in progress. Use /start to begin.")
        return

    index = session["index"]
    if index >= len(session["questions"]):
        score_obj = await get_score_by_id(session["score_obj_id"])
        await update_score(score_obj, session["score"], ended=True)
        await update.message.reply_text(f"🎉 Quiz complete! Final score: {session['score']} out of {len(session['questions'])}")
        del user_sessions[user_id]
        return

    question = session["questions"][index]
    context.user_data["correct"] = question["correct"]

    keyboard = [[opt] for opt in question["options"] if opt.strip()]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(f"Q{question['number']}. {question['text']}", reply_markup=markup)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    if not session:
        await update.message.reply_text("❗ Start a quiz first using /start.")
        return

    selected = update.message.text.strip()[0].upper()
    correct = context.user_data.get("correct")

    question = session["questions"][session["index"]]
    question_text = f"Q{question['number']}. {question['text']}\n" + "\n".join(question["options"])
    question_text = escape_markdown(question_text)

    # Feedback with full question context
    if selected == correct:
        session["score"] += 1
        await update.message.reply_text(
            f"✅ Correct!\n\n{question_text}\n\nYour Answer: {selected}"
        )
    else:
        await update.message.reply_text(
            f"❌ Incorrect.\n\n{question_text}\n\nYour Answer: {selected}\nCorrect Answer: {correct}"
        )

    # Save progress
    score_obj = await get_score_by_id(session["score_obj_id"])
    await update_score(score_obj, session["score"])
    session["index"] += 1

    await send_question(update, context)

# --- Run Bot ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("continue", continue_quiz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🤖 Quiz bot is running...")
    app.run_polling()
