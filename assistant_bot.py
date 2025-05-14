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

def schedule_repeating_task(task, application):
    from datetime import time

    hour, minute = map(int, task["time"].split(":"))
    message = task["text"]
    days = task["repeat"]  # ["Monday", "Tuesday", ...]

    day_indexes = {
        "Monday": 0, "Tuesday": 1, "Wednesday": 2,
        "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6
    }

    application.job_queue.run_daily(
        lambda context: context.bot.send_message(chat_id=task["chat_id"], text=f"🔁 Напоминание: {message}"),
        time=time(hour, minute),
        days=[day_indexes[day] for day in days]
    )

async def parse_with_gpt(text):
    tz = pytz.timezone("Europe/Tallinn")
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")

    prompt = f"""
Сегодня: {today}
Текущее время: {current_time}

Ты — помощник, который извлекает задачу и дату из человеческой фразы. Пользователь пишет тебе напоминание, а ты возвращаешь его в формате JSON.

Если задача одноразовая — верни:
{{
  "text": "что сделать",
  "time": "2025-05-15T18:00:00"
}}

Если задача повторяющаяся — верни:
{{
  "text": "что делать",
  "time": "08:00",  // только часы и минуты!
  "repeat": ["Monday", "Tuesday", "Wednesday"]
}}

❗ ВАЖНО:
— если пользователь пишет "каждый", "по понедельникам", "по будням", "по выходным", "каждое утро", "ежедневно", "в 8 утра по будням" — это повторяющаяся задача  
— используй repeat только при регулярных задачах  
— не пиши пояснений, верни только чистый JSON

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

    # поведение, если repeat есть
    if "repeat" in gpt_result:
        task = {
            "chat_id": update.effective_chat.id,
            "text": gpt_result["text"],
            "time": gpt_result["time"],  # формат: "08:00"
            "repeat": gpt_result["repeat"]
        }
        schedule_repeating_task(task, context.application)
        await update.message.reply_text(f"🔁 Буду напоминать: '{task['text']}' в {task['time']} по дням: {', '.join(task['repeat'])}")
        return

    # если time — список (много дат)
    if isinstance(gpt_result["time"], list):
        for t in gpt_result["time"]:
            task = {
                "chat_id": update.effective_chat.id,
                "text": gpt_result["text"],
                "time": t
            }
            schedule_task(task, context.application)
        await update.message.reply_text(f"✅ Запланировал несколько напоминаний: {len(gpt_result['time'])}")
        return

    # обычная задача
    task = {
        "chat_id": update.effective_chat.id,
        "text": gpt_result["text"],
        "time": gpt_result["time"]
    }
    schedule_task(task, context.application)

    time_str = datetime.fromisoformat(task["time"]).strftime('%Y-%m-%d %H:%M')
    await update.message.reply_text(f"✅ Запомнил! Напомню: ‘{task['text']}’ в {time_str}")

async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = load_tasks()
    chat_id = update.effective_chat.id
    user_tasks = [task for task in tasks if task["chat_id"] == chat_id]

    if not user_tasks:
        await update.message.reply_text("🔕 У тебя нет запланированных задач.")
        return

    text = "🗓 Твои задачи:\n"
    for i, task in enumerate(user_tasks):
        if "repeat" in task:
            text += f"{i + 1}. 🔁 {task['text']} — в {task['time']} по {', '.join(task['repeat'])}\n"
        else:
            t = datetime.fromisoformat(task["time"]).strftime('%Y-%m-%d %H:%M')
            text += f"{i + 1}. ⏰ {task['text']} — {t}\n"

    await update.message.reply_text(text)

async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = load_tasks()
    chat_id = update.effective_chat.id
    user_tasks = [task for task in tasks if task["chat_id"] == chat_id]

    if not context.args:
        await update.message.reply_text("❗ Используй: /delete [номер задачи]")
        return

    try:
        index = int(context.args[0]) - 1
        if index < 0 or index >= len(user_tasks):
            raise ValueError()

        task_to_delete = user_tasks[index]
        tasks.remove(task_to_delete)
        save_tasks(tasks)

        await update.message.reply_text(f"🗑 Задача удалена: {task_to_delete['text']}")

    except ValueError:
        await update.message.reply_text("❗ Неверный номер. Посмотри /tasks")



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Напиши что-то вроде: «напомни завтра в 10:00 купить хлеб» — и я запомню 😉")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    job_queue = app.job_queue  # ✅ эта строка — строго на один уровень отступа

    app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("tasks", show_tasks))
app.add_handler(CommandHandler("delete", delete_task))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    tasks = load_tasks()
    for task in tasks:
        if datetime.fromisoformat(task["time"]) > datetime.now(pytz.timezone("Europe/Tallinn")):
            schedule_task(task, app)

    print("Бот запущен.")
    app.run_polling()

