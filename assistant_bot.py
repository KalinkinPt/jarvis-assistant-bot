import os
import json
import logging
from datetime import datetime, timedelta
import pytz
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

def load_tasks():
    try:
        with open('tasks.json', 'r') as f:
            return json.load(f)
    except:
        return []

def save_tasks(tasks):
    with open('tasks.json', 'w') as f:
        json.dump(tasks, f)

def schedule_task(task, application):
    tz = pytz.timezone("Europe/Tallinn")
    run_time = tz.localize(datetime.fromisoformat(task["time"]))  # 🛠 исправили тут
    delay = (run_time - datetime.now(tz)).total_seconds()

    if delay > 0:
        print(f"⏰ Планируем задачу через {int(delay)} сек: {task['text']}")
        application.job_queue.run_once(
            lambda context: context.bot.send_message(chat_id=task["chat_id"], text=f"🔔 Напоминание: {task['text']}"),
            when=delay
        )


async def parse_with_gpt(text):
    tz = pytz.timezone("Europe/Tallinn")
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")

    prompt = f"""
Сегодня: {today}
Текущее время: {current_time}

Ты — ассистент, который извлекает задачу и дату из человеческой фразы.

Верни ТОЛЬКО JSON без пояснений, вот так:

{{
  "text": "что сделать",
  "time": "2025-05-15T18:00:00"
}}

Фраза: {text}
Ответ:
"""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        content = response.choices[0].message["content"].strip()
        print("📥 GPT вернул:\\n", content)


        if content.startswith("```"):
            content = content.split("```")[-1].strip()

        return json.loads(content)

    except Exception as e:
        print("❌ GPT ошибка:", e)
        return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    gpt_result = await parse_with_gpt(user_input)

    if not gpt_result or not gpt_result.get("time"):
        await update.message.reply_text("🤖 Не смог распознать дату и время. Попробуй иначе.")
        return

    task = {
        "chat_id": update.effective_chat.id,
        "text": gpt_result["text"],
        "time": gpt_result["time"]
    }

    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)
    schedule_task(task, context.application)

    time_str = datetime.fromisoformat(task["time"]).strftime('%Y-%m-%d %H:%M')
    await update.message.reply_text(f"✅ Запомнил! Напомню: ‘{task['text']}’ в {time_str}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Напиши что-то вроде: «напомни завтра в 10:00 купить хлеб» — и я запомню 😉")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
job_queue = app.job_queue  # <-- добавляем после .build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # Восстанавливаем старые задачи
    tasks = load_tasks()
    for task in tasks:
        if datetime.fromisoformat(task["time"]) > datetime.now(pytz.timezone("Europe/Tallinn")):
            schedule_task(task, app)

    print("Бот запущен.")
    app.run_polling()
