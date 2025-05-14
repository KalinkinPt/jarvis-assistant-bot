import os
import json
import logging
from datetime import datetime
import dateparser
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
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
        lambda: context.bot.send_message(chat_id=task["chat_id"], text=f"Напоминание: {task['text']}"),
        trigger='date',
        run_date=run_time
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    dt = dateparser.parse(text, languages=['ru'])
    if not dt:
        await update.message.reply_text("Не смог распознать дату/время. Попробуй иначе.")
        return
    task = {
        "chat_id": update.effective_chat.id,
        "text": text,
        "time": dt.isoformat()
    }
    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)
    schedule_task(task, context)
    await update.message.reply_text(f"Запомнил! Напомню: {text} — {dt.strftime('%Y-%m-%d %H:%M')}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я твой ассистент. Напиши, что тебе напомнить.")

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    tasks = load_tasks()
    for task in tasks:
        if datetime.fromisoformat(task["time"]) > datetime.now():
            schedule_task(task, app.bot)

    print("Бот запущен.")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio

    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()

