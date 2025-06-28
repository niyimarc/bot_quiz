import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quiz_project.settings")
import django
django.setup()

import re
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from asgiref.sync import sync_to_async
from django.utils import timezone
from django.conf import settings

from quiz_app.models import Quiz, QuizParticipant, QuizScore, QuizSession  # 👈 Make sure QuizSession is added

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = os.getenv("API_URL").rstrip("/")

# --- Markdown escape
def escape_markdown(text):
    return re.sub(r'([_\*\[\]()~`>#+=|{}.!\\-])', r'\\\1', text)

# --- API Call
def fetch_questions_from_api(quiz_name):
    try:
        url = f"{API_URL}/?{urlencode({'quiz': quiz_name})}"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        print("API Error:", response.status_code, response.text)
    except Exception as e:
        print("Request failed:", e)
    return []

# --- Async DB Functions
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
def get_score_by_id(score_id):
    return QuizScore.objects.get(id=score_id)

@sync_to_async
def update_score(score_obj, new_score, ended=False):
    score_obj.score = new_score
    if ended:
        score_obj.end_time = timezone.now()
    score_obj.save()

@sync_to_async
def get_or_create_session(participant):
    return QuizSession.objects.get_or_create(participant=participant)

@sync_to_async
def update_session(session, **kwargs):
    for key, value in kwargs.items():
        setattr(session, key, value)
    session.save()

# --- Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("/start command received")
    user = update.effective_user
    await get_or_create_participant(user)

    name = user.first_name or "there"
    intro_text = (
         f"""👋 Hello {name}!\n
        <b>Welcome to the Quiz Bot 🧠</b>\n\n
        Here's how it works:\n
        1. Select a quiz from the list.\n
        2. Answer each question one-by-one.\n
        3. Get instant feedback.\n
        4. Score saved at the end.\n\n
        Use <code>/continue</code> to resume unfinished quizzes.\n
        💬 Developer: <a href="https://t.me/drey_tech">@drey_tech</a>\n\n
        👇 Choose a quiz:"""
    )
    quizzes = await get_quiz_names()
    if not quizzes:
        await update.message.reply_text("⚠️ No active quizzes available.")
        return

    keyboard = [[KeyboardButton(name)] for name in quizzes]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(intro_text, reply_markup=markup, parse_mode="HTML")

async def continue_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    participant = await get_participant_by_telegram_id(user_id)
    if not participant:
        await update.message.reply_text("❗ You haven’t started any quiz yet.")
        return

    unfinished = await get_unfinished_score(participant)
    if not unfinished:
        await update.message.reply_text("🎉 You have no unfinished quiz.")
        return

    questions = fetch_questions_from_api(unfinished.quiz.name)
    if not questions:
        await update.message.reply_text("❌ Could not load quiz questions.")
        return

    session, _ = await get_or_create_session(participant)
    await update_session(session,
        quiz_name=unfinished.quiz.name,
        questions=questions,
        index=unfinished.score,
        score=unfinished.score,
        score_obj=unfinished,
    )

    await update.message.reply_text(f"🔁 Resuming quiz: {unfinished.quiz.name}")
    await send_question(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    participant = await get_participant_by_telegram_id(user.id)
    if not participant:
        await update.message.reply_text("❗ Please start a quiz first using /start.")
        return

    session, _ = await get_or_create_session(participant)

    if session.quiz_name:
        await handle_answer(update, context, session, participant)
    else:
        await select_quiz(update, context, participant, session)

async def select_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, participant, session):
    quiz_name = update.message.text.strip()
    quiz = await get_quiz_by_name(quiz_name)
    if not quiz:
        await update.message.reply_text("❌ Invalid quiz name.")
        return

    questions = fetch_questions_from_api(quiz_name)
    if not questions:
        await update.message.reply_text("❌ Could not load questions.")
        return

    score_obj = await create_score(participant, quiz, len(questions))
    await update_session(session,
        quiz_name=quiz_name,
        questions=questions,
        index=0,
        score=0,
        score_obj=score_obj,
    )

    await update.message.reply_text(f"🧠 Starting quiz: {quiz_name}")
    await send_question(update, context)

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    participant = await get_participant_by_telegram_id(user_id)
    session, _ = await get_or_create_session(participant)

    questions = session.questions or []
    index = session.index

    if index >= len(questions):
        score_obj = await get_score_by_id(session.score_obj.id)
        await update_score(score_obj, session.score, ended=True)
        await update.message.reply_text(f"🎉 Finished! You scored {session.score} out of {len(questions)}")
        await update_session(session, quiz_name=None, questions=[], index=0, score=0, score_obj=None)
        return

    question = questions[index]
    context.user_data["correct"] = question["correct"]
    keyboard = [[opt] for opt in question["options"] if opt.strip()]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(f"Q{question['number']}. {question['text']}", reply_markup=markup)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, session, participant):
    selected = update.message.text.strip()[0].upper()
    correct = context.user_data.get("correct")

    question = session.questions[session.index]
    summary = f"*Q{question['number']}*: {escape_markdown(question['text'])}\n" + \
              "\n".join(escape_markdown(opt) for opt in question["options"])

    if selected == correct:
        new_score = session.score + 1
        await update.message.reply_text(f"✅ Correct!\n\n{summary}\nYour Answer: {selected}", parse_mode="HTML")
    else:
        new_score = session.score
        await update.message.reply_text(
            f"❌ Incorrect.\n\n{summary}\nYour Answer: {selected}\nCorrect Answer: {correct}",
            parse_mode="HTML"
        )

    score_obj = await get_score_by_id(session.score_obj.id)
    await update_score(score_obj, new_score)
    await update_session(session, score=new_score, index=session.index + 1)
    await send_question(update, context)

# --- Build Application
application = ApplicationBuilder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("continue", continue_quiz))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

# For Django view
telegram_app = application
