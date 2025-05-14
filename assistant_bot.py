import os
import json
import logging
from datetime import datetime
import dateparser
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

scheduler = BackgroundScheduler()
scheduler.start()

def load_tasks():
    try:
        with open('tasks.json', 'r') as f:
            return json.load(f)
    except:
        return []

def save_tasks(tasks):
    with open('tasks.json', 'w') as f:
        json.dump(tasks, f)

def schedule_task(task, context):
    run_time = datetime.fromisoformat(task["time"])
    scheduler.add_job(
        lambda: context.bot.send_message(chat_id=task["chat_id"], text=f"🔔 Напоминание: {task['text']}"),
        trigger='date',
        run_date=run_time
    )

async def parse_with_gpt(text):
    prompt = f"""
Ты — ассистент, который извлекает задачу и дату из человеческой фразы.

Верни ТОЛЬКО JSON без комментариев, вот так:

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

        print("📥 GPT вернул:\n", content)  # 💬 Печатаем ответ в логи

        if content.startswith("```"):
            content = content.split("```")[-1].strip()

        return json.loads(content)
    except Exception as e:
        print("❌ GPT ошибка:", e)
        return None


        # Удалим возможные обёртки вроде "```json"
        if content.startswith("```"):
            content = content.split("```")[-1].strip()

        return json.loads(content)
    except Exception as e:
        print("GPT Error:", e)
        return None


    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        content = response.choices[0].message["content"]
        return json.loads(content)
    except Exception as e:
        print("GPT Error:", e)
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
    schedule_task(task, context)

    time_str = datetime.fromisoformat(task["time"]).strftime('%Y-%m-%d %H:%M')
    await update.message.reply_text(f"✅ Запомнил! Напомню: ‘{task['text']}’ в {time_str}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Напиши что-то вроде: «напомни завтра в 10:00 купить хлеб» — и я запомню 😉")


if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    tasks = load_tasks()
    for task in tasks:
        if datetime.fromisoformat(task["time"]) > datetime.now():
            schedule_task(task, app.bot)

    print("Бот запущен.")
    app.run_polling()
