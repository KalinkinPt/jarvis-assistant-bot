import os
import json
import logging
from datetime import datetime, timedelta, time
import pytz
import openai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue, CallbackQueryHandler

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
    run_time = tz.localize(datetime.fromisoformat(task["time"]))

    def make_job(delay_seconds, prefix):
        if delay_seconds > 0:
            application.job_queue.run_once(
                lambda context: context.bot.send_message(
                    chat_id=task["chat_id"],
                    text=f"{prefix} {task['text']}"
                ),
                when=delay_seconds
            )

    now = datetime.now(tz)
    delay_main = (run_time - now).total_seconds()
    delay_30 = delay_main - 1800  # 30 минут до
    delay_15 = delay_main - 900   # 15 минут до

    print(f"⏰ Планируем задачу: {task['text']} на {run_time}")
    make_job(delay_30, "⚠️ Через 30 мин:")
    make_job(delay_15, "⏱ Почти время:")
    make_job(delay_main, "🔔 Сейчас:")


def schedule_repeating_task(task, application):
    from datetime import datetime, timedelta, time

    hour, minute = map(int, task["time"].split(":"))
    message = task["text"]
    days = task["repeat"]  # ["Monday", "Tuesday", ...]

    day_indexes = {
        "Monday": 0, "Tuesday": 1, "Wednesday": 2,
        "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6
    }

    target_time = time(hour, minute)

    # Время "за 30 минут"
    time_30_before = (datetime.combine(datetime.today(), target_time) - timedelta(minutes=30)).time()
    # Время "за 15 минут"
    time_15_before = (datetime.combine(datetime.today(), target_time) - timedelta(minutes=15)).time()

    day_list = [day_indexes[d] for d in days]

    # Напоминание за 30 мин
    application.job_queue.run_daily(
        lambda context: context.bot.send_message(
            chat_id=task["chat_id"],
            text=f"⚠️ Через 30 мин: {message}"
        ),
        time=time_30_before,
        days=day_list
    )

    # Напоминание за 15 мин
    application.job_queue.run_daily(
        lambda context: context.bot.send_message(
            chat_id=task["chat_id"],
            text=f"⏱ Почти время: {message}"
        ),
        time=time_15_before,
        days=day_list
    )

    # Напоминание в точное время
    application.job_queue.run_daily(
        lambda context: context.bot.send_message(
            chat_id=task["chat_id"],
            text=f"🔔 Сейчас: {message}"
        ),
        time=target_time,
        days=day_list
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
    if update.message is None or update.message.text is None:
        return

    user_input = update.message.text
    gpt_result = await parse_with_gpt(user_input)

    if not gpt_result:
        await update.message.reply_text("🤖 Не смог распознать дату и время. Попробуй иначе.")
        return

    # ✅ Несколько задач в списке
    if isinstance(gpt_result, list):
        count = 0
        for entry in gpt_result:
            if "text" in entry and "time" in entry:
                task = {
                    "chat_id": update.effective_chat.id,
                    "text": entry["text"],
                    "time": entry["time"]
                }
                schedule_task(task, context.application)
                tasks = load_tasks()
                tasks.append(task)
                save_tasks(tasks)
                count += 1

        await update.message.reply_text(f"✅ Запомнил {count} задач(и)")
        return

    # 🔁 Повторяющаяся задача
    if "repeat" in gpt_result:
        task = {
            "chat_id": update.effective_chat.id,
            "text": gpt_result["text"],
            "time": gpt_result["time"],  # формат: "08:00"
            "repeat": gpt_result["repeat"]
        }
        schedule_repeating_task(task, context.application)

        tasks = load_tasks()
        tasks.append(task)
        save_tasks(tasks)

        await update.message.reply_text(
            f"🔁 Буду напоминать: '{task['text']}' в {task['time']} по дням: {', '.join(task['repeat'])}"
        )
        return

    # 📅 Несколько дат для одной задачи
    if isinstance(gpt_result.get("time"), list):
        for t in gpt_result["time"]:
            task = {
                "chat_id": update.effective_chat.id,
                "text": gpt_result["text"],
                "time": t
            }
            schedule_task(task, context.application)
            tasks = load_tasks()
            tasks.append(task)
            save_tasks(tasks)

        await update.message.reply_text(f"✅ Запланировал несколько напоминаний: {len(gpt_result['time'])}")
        return

    # 🕐 Обычная одноразовая задача
    if not gpt_result.get("time"):
        await update.message.reply_text("🤖 Не смог распознать дату и время. Попробуй иначе.")
        return

    task = {
        "chat_id": update.effective_chat.id,
        "text": gpt_result["text"],
        "time": gpt_result["time"]
    }
    schedule_task(task, context.application)

    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)

    time_str = datetime.fromisoformat(task["time"]).strftime('%Y-%m-%d %H:%M')
    await update.message.reply_text(f"✅ Запомнил! Напомню: ‘{task['text']}’ в {time_str}")


async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("📥 Вызван /tasks")
    tasks = load_tasks()
    chat_id = update.effective_chat.id
    user_tasks = [task for task in tasks if task["chat_id"] == chat_id]

    if not user_tasks:
        await update.message.reply_text("🔕 У тебя нет запланированных задач.")
        return

    tz = pytz.timezone("Europe/Tallinn")
    now = datetime.now(tz)

    def format_timedelta(delta):
        days = delta.days
        seconds = delta.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        parts = []
        if days > 0:
            parts.append(f"{days} дн")
        if hours > 0:
            parts.append(f"{hours} ч")
        if minutes > 0:
            parts.append(f"{minutes} мин")

        return "через " + " ".join(parts) if parts else "скоро"

    text = "🗓 Твои задачи:\n"
    for i, task in enumerate(user_tasks):
        if "repeat" in task:
            text += f"{i + 1}. 🔁 {task['text']} — в {task['time']} по {', '.join(task['repeat'])}\n"
        else:
            t = datetime.fromisoformat(task["time"]).astimezone(tz)
            delta = t - now
            left = format_timedelta(delta) if delta.total_seconds() > 0 else "⏱ Уже прошло"
            t_str = t.strftime('%Y-%m-%d %H:%M')
            text += f"{i + 1}. ⏰ {task['text']} — {t_str} ({left})\n"

    await update.message.reply_text(text)

async def show_tasks_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("📥 Вызван /tasks_today")
    tasks = load_tasks()
    chat_id = update.effective_chat.id
    user_tasks = [task for task in tasks if task["chat_id"] == chat_id]

    tz = pytz.timezone("Europe/Tallinn")
    now = datetime.now(tz)
    today_date = now.date()

    today_tasks = []

    for task in user_tasks:
        if "repeat" in task:
            continue  # не показываем повторяющиеся
        try:
            task_time = datetime.fromisoformat(task["time"]).astimezone(tz)
            if task_time.date() == today_date:
                today_tasks.append((task["text"], task_time))
        except:
            continue

    if not today_tasks:
        await update.message.reply_text("Сегодня у тебя нет задач 💤")
        return

    def format_timedelta(delta):
        days = delta.days
        seconds = delta.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        parts = []
        if days > 0:
            parts.append(f"{days} дн")
        if hours > 0:
            parts.append(f"{hours} ч")
        if minutes > 0:
            parts.append(f"{minutes} мин")

        return "через " + " ".join(parts) if parts else "скоро"

    text = "📅 Задачи на сегодня:\n"
    for i, (task_text, task_time) in enumerate(sorted(today_tasks, key=lambda x: x[1])):
        delta = task_time - now
        left = format_timedelta(delta) if delta.total_seconds() > 0 else "⏱ Уже прошло"
        t_str = task_time.strftime('%H:%M')
        text += f"{i + 1}. ⏰ {task_text} — {t_str} ({left})\n"

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

async def clear_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = load_tasks()
    chat_id = update.effective_chat.id

    tasks = [task for task in tasks if task["chat_id"] != chat_id]
    save_tasks(tasks)

    await update.message.reply_text("🧹 Все твои задачи удалены.")

async def clear_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data="confirm_clear"),
            InlineKeyboardButton("❌ Нет", callback_data="cancel_clear"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("❗ Ты уверен, что хочешь удалить все задачи?", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if query.data == "confirm_clear":
        tasks = load_tasks()
        tasks = [task for task in tasks if task["chat_id"] != chat_id]
        save_tasks(tasks)

        await query.message.delete()
        await query.message.reply_text("🧹 Все задачи удалены.")
    elif query.data == "cancel_clear":
        await query.message.delete()
        await query.message.reply_text("❌ Удаление отменено.")



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Напиши что-то вроде: «напомни завтра в 10:00 купить хлеб» — и я запомню 😉")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    job_queue = app.job_queue

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tasks", show_tasks))
    app.add_handler(CommandHandler("tasks_today", show_tasks_today))
    app.add_handler(CommandHandler("delete", delete_task))
    app.add_handler(CommandHandler("clear", clear_tasks))
    app.add_handler(CallbackQueryHandler(button_handler))  # обработка кнопок

    # этот обработчик должен быть последним!
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # загрузка задач из файла при запуске
    tasks = load_tasks()
    for task in tasks:
        if "repeat" in task:
            schedule_repeating_task(task, app)
        elif datetime.fromisoformat(task["time"]) > datetime.now(pytz.timezone("Europe/Tallinn")):
            schedule_task(task, app)

    print("Бот запущен.")
    app.run_polling()


