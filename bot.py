# в самом верху bot.py и models.py
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN        = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID     = int(os.getenv("ADMIN_TELEGRAM_ID"))

# bot.py
import logging
from datetime import datetime, date, timedelta, time, timezone
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes,
    filters,
)
from models import SessionLocal, User, Event, Reminder

MSK = timezone(timedelta(hours=3))

from datetime import timedelta

async def test_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просто шлёт тестовое напоминание через минуту самому себе."""
    chat_id = update.effective_user.id
    context.application.job_queue.run_once(
        lambda ctx: context.bot.send_message(chat_id=chat_id, text="✅ Это тестовое уведомление!"),
        when=timedelta(minutes=1),
        name=f"test_{chat_id}"
    )
    await update.message.reply_text("Тестовое напоминание запланировано через 1 минуту.")


async def test_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = update.effective_user.id
    await context.bot.send_message(
        chat_id=me,
        text="✅ Если вы это видите — ваш бот умеет слать сообщения!"
    )


async def test_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = SessionLocal()
    tg_id = update.effective_user.id
    user = session.query(User).filter_by(telegram_id=tg_id).first()
    if not user:
        await update.message.reply_text("❌ Вы не зарегистрированы в БД.")
        session.close()
        return

    bday = date.today() + timedelta(days=7)
    text = f"🎂 Через неделю ({bday.strftime('%d.%m.%Y')}) — день рождения **{user.full_name}**! 🎉"

    # Пошлём тестово и себе
    await context.bot.send_message(chat_id=tg_id, text=text, parse_mode="Markdown")
    session.close()
    await update.message.reply_text("Тестовое поздравление отправлено вам!")




# Состояния разговоров
REGISTER_NAME, REGISTER_POSITION, REGISTER_BIRTHDATE = range(3)
EVENT_TITLE, EVENT_DESC, EVENT_INTERVAL, EVENT_DATE, EVENT_USERS = range(3, 8)

# Должности
POSITIONS = [
    "заведующий кафедрой", "доцент", "старший преподаватель",
    "ассистент", "профессор", "заведующий лабораторией", "сотрудник лаборатории",
]
# Интервалы напоминаний
INTERVAL_OPTIONS = [
    ("Каждые 7 дней", 7),
    ("Каждые 3 дня", 3),
    ("Каждый день",     1),
]

def schedule_birthday_reminder(job_queue, user_id: int, birth_date: date):
    today = date.today()
    this_year_bday = date(today.year, birth_date.month, birth_date.day)
    if this_year_bday < today:
        next_bday = date(today.year + 1, birth_date.month, birth_date.day)
    else:
        next_bday = this_year_bday

    remind_date = next_bday - timedelta(days=7)
    run_dt = datetime.combine(remind_date, time(13, 0), MSK)
    if run_dt <= datetime.now(MSK):
        return

    job_id = f"bday_{user_id}_{next_bday.year}"
    # удаляем старую, если есть
    for job in job_queue.get_jobs_by_name(job_id):
        job.schedule_removal()

    # создаём новую
    job_queue.run_once(
        send_birthday_reminder,
        when=run_dt,
        name=job_id,
        data={'user_id': user_id, 'bday': next_bday}
    )


async def send_birthday_reminder(context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет всем, кроме именинника, напоминание «через неделю день рождения».
    """
    job_data = context.job.data
    user_id = job_data['user_id']
    bday    = job_data['bday']  # ближайший день рождения, datetime.date

    session = SessionLocal()
    user = session.get(User, user_id)
    if not user:
        session.close()
        return

    # выбираем всех кроме именинника
    others = session.query(User).filter(User.id != user_id).all()
    text = (
        f"🎂 Через неделю ({bday.strftime('%d.%m.%Y')}) — день рождения **{user.full_name}**! 🎉"
    )
    for u in others:
        await context.bot.send_message(
            chat_id=u.telegram_id,
            text=text,
            parse_mode="Markdown"
        )
    session.close()



# Построение главного меню с учётом is_admin
def build_main_menu(is_admin: bool):
    rows = [
        ["События", "Управление событиями"],
        ["Создать событие", "Справка"],
        ["Меню"]
    ]
    if is_admin:
        rows.insert(1, ["Панель администратора"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# Меню до регистрации
REG_MENU = ReplyKeyboardMarkup(
    [["Регистрация", "События"], ["Создать событие", "Справка"], ["Меню"]],
    resize_keyboard=True
)

# Логирование
logging.basicConfig(
    format='%(asctime)s — %(name)s — %(levelname)s — %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Функция записи пользователя в БД
def register_user(tg_id, name, pos, bdate):
    session = SessionLocal()
    user = User(
        telegram_id=tg_id,
        full_name=name,
        position=pos,
        birth_date=bdate
    )
    session.add(user)
    session.commit()
    uid, full, position, bd, is_admin = (
        user.id, user.full_name, user.position, user.birth_date, user.is_admin
    )
    session.close()
    return uid, full, position, bd, is_admin

# /start и кнопка «Меню»
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    session = SessionLocal()
    user = session.query(User).filter_by(telegram_id=tg_id).first()
    session.close()

    if user:
        menu = build_main_menu(user.is_admin)
        admin_line = "🛡 Администратор\n" if user.is_admin else ""
        await update.message.reply_text(
            f"С возвращением, {user.full_name}!\n"
            f"🆔 {user.id}\n"
            f"{admin_line}"
            f"🎓 {user.position}\n"
            f"🎂 {user.birth_date.strftime('%d.%m.%Y')}",
            reply_markup=menu
        )
    else:
        await update.message.reply_text("Выберите действие:", reply_markup=REG_MENU)

# --- Регистрация ---
async def registration_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Введите ваше ФИО:", reply_markup=ReplyKeyboardRemove())
    return REGISTER_NAME

async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['full_name'] = update.message.text.strip()
    kb = [[pos] for pos in POSITIONS]
    await update.message.reply_text(
        "Выберите должность:",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )
    return REGISTER_POSITION

async def register_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    pos = update.message.text.strip()
    if pos not in POSITIONS:
        await update.message.reply_text("Пожалуйста, выберите должность с клавиатуры.")
        return REGISTER_POSITION
    context.user_data['position'] = pos
    await update.message.reply_text("Введите дату рождения DD.MM.YYYY:", reply_markup=ReplyKeyboardRemove())
    return REGISTER_BIRTHDATE

async def register_birthdate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    try:
        bdate = datetime.strptime(txt, "%d.%m.%Y").date()
    except ValueError:
        await update.message.reply_text("Неверный формат. Пример: 01.08.2004")
        return REGISTER_BIRTHDATE

    tg_id = update.effective_user.id
    uid, full, pos, bd, is_admin = register_user(
        tg_id,
        context.user_data['full_name'],
        context.user_data['position'],
        bdate
    )

    menu = build_main_menu(is_admin)
    await update.message.reply_text("🎉 Вы успешно зарегистрированы! 🎉")
    await update.message.reply_text(
        f"🆔 {uid}\n"
        f"{full}\n"
        f"🎓 {pos}\n"
        f"🎂 {bd.strftime('%d.%m.%Y')}",
        reply_markup=menu
    )

    schedule_birthday_reminder(
        context.application.job_queue,
        tg_id,  # или user.id, если вы получаете его из register_user
        bdate
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Регистрация отменена.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Создание события ---
async def event_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Введите название события:", reply_markup=ReplyKeyboardRemove())
    return EVENT_TITLE

async def event_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['evt_title'] = update.message.text.strip()
    await update.message.reply_text("Введите описание события:")
    return EVENT_DESC

async def event_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['evt_desc'] = update.message.text.strip()
    kb = [[opt[0]] for opt in INTERVAL_OPTIONS]
    await update.message.reply_text(
        "Выберите периодичность напоминаний:",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)
    )
    return EVENT_INTERVAL

async def event_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text.strip()
    mapping = {opt[0]: opt[1] for opt in INTERVAL_OPTIONS}
    if choice not in mapping:
        await update.message.reply_text("Пожалуйста, выберите вариант с клавиатуры.")
        return EVENT_INTERVAL
    context.user_data['evt_interval'] = mapping[choice]
    await update.message.reply_text("Введите дату события DD.MM.YYYY:")
    return EVENT_DATE

async def event_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    try:
        evt_dt = datetime.strptime(txt, "%d.%m.%Y").date()
    except ValueError:
        await update.message.reply_text("Неверный формат. Пример: 01.08.2025")
        return EVENT_DATE

    # Запретить дату в прошлом
    if evt_dt < date.today():
        await update.message.reply_text("Дата события не может быть раньше сегодняшней. Попробуйте ещё раз:")
        return EVENT_DATE

    context.user_data['evt_date'] = evt_dt

    session = SessionLocal()
    users = session.query(User).all()
    session.close()

    kb = [[u.full_name] for u in users] + [["Готово"]]
    context.user_data['evt_notify_list'] = []
    await update.message.reply_text(
        "Выберите пользователей для уведомлений (можно несколько). Нажмите «Готово» для завершения:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )
    return EVENT_USERS

def schedule_reminders(job_queue, event_id: int, interval: int):
    session = SessionLocal()
    evt = session.query(Event).get(event_id)
    session.close()

    today = date.today()
    run_date = today
    while run_date <= evt.event_date:
        # запланировать на run_date 13:00 МСК
        run_dt = datetime.combine(run_date, time(13, 0), MSK)
        if run_dt >= datetime.now(MSK):
            job_queue.run_once(
                send_reminder,
                when=run_dt,
                data={'event_id': event_id, 'target_date': run_date}
            )
        run_date += timedelta(days=interval)

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    ev_id      = job_data['event_id']
    target_day = job_data['target_date']

    # Получаем из БД данные о событии
    session = SessionLocal()
    evt = session.query(Event).get(ev_id)

    if evt and date.today() == target_day:
        for u in evt.recipients:
            try:
                await context.bot.send_message(
                    chat_id=u.telegram_id,
                    text=(
                        f"⏰ Напоминание: событие «{evt.title}» запланировано на "
                        f"{evt.event_date.strftime('%d.%m.%Y')}.\n\n"
                        f"Описание события: «{evt.description}»"
                    ),
                )
            except Exception as e:
                logger.error(f"Не удалось отправить напоминание {evt.id} пользователю {u.id}: {e}")
                # здесь можно, например, запланировать повтор через минуту:
                context.job_queue.run_once(
                    send_reminder,
                    when=timedelta(minutes=1),
                    data=job_data,
                    name=f"retry_{evt.id}_{u.id}"
                )
    session.close()


async def event_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "Готово":
        session = SessionLocal()
        creator = session.query(User).filter_by(telegram_id=update.effective_user.id).first()

        # 1) Создаём событие и сохраняем, чтобы получить его ID
        evt = Event(
            title=context.user_data['evt_title'],
            description=context.user_data['evt_desc'],
            event_date=context.user_data['evt_date'],
            creator=creator
        )
        session.add(evt)
        session.commit()
        eid = evt.id

        # 2) Создаём запись о напоминании в БД
        rem = Reminder(event=evt, interval_days=context.user_data['evt_interval'])
        session.add(rem)

        # 3) Выбираем получателей и сохраняем их chat_id
        recs = session.query(User).filter(User.full_name.in_(context.user_data['evt_notify_list'])).all()
        chat_ids = [u.telegram_id for u in recs]

        # 4) Привязываем получателей к событию и сохраняем всё
        evt.recipients = recs
        session.commit()

        # 5) Забираем нужные поля до закрытия сессии
        title  = evt.title
        evdate = evt.event_date
        descr  = evt.description
        session.close()

        # 6) Планируем отложенные напоминания через JobQueue
        schedule_reminders(context.application.job_queue, eid, context.user_data['evt_interval'])

        await update.message.reply_text("✅ Событие и получатели сохранены!", reply_markup=ReplyKeyboardRemove())
        await start(update, context)
        return ConversationHandler.END

    # если добавляется очередной получатель
    if text not in context.user_data['evt_notify_list']:
        context.user_data['evt_notify_list'].append(text)
        await update.message.reply_text(f"Добавлен: {text}")
    else:
        await update.message.reply_text(f"{text} уже в списке.")
    return EVENT_USERS



# --- Управление своими событиями ---
async def manage_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = SessionLocal()
    tg_id = update.effective_user.id
    rows = (
        session.query(Event, User.full_name)
        .join(User, Event.creator)
        .filter(User.telegram_id == tg_id)
        .order_by(Event.event_date)
        .all()
    )
    session.close()

    if not rows:
        await update.message.reply_text("У вас ещё нет событий.", reply_markup=build_main_menu(False))
        return

    text_lines = ["Ваши события:"]
    buttons = []
    for evt, _ in rows:
        text_lines.append(f"• {evt.title} ({evt.event_date.strftime('%d.%m.%Y')})")
        buttons.append([InlineKeyboardButton(f"Удалить «{evt.title}»", callback_data=f"delete_evt_{evt.id}")])

    await update.message.reply_text("\n".join(text_lines))
    await update.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(buttons))

async def delete_evt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    evt_id = int(query.data.split("_")[-1])

    session = SessionLocal()
    evt = session.query(Event).get(evt_id)
    if evt and evt.creator.telegram_id == query.from_user.id:
        session.delete(evt)
        session.commit()
    session.close()
    await query.edit_message_text("Событие удалено.")

# --- Вывод всех событий ---
async def events_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = SessionLocal()
    rows = (
        session.query(Event, User.full_name)
        .join(User, Event.creator)
        .order_by(Event.event_date)
        .all()
    )
    session.close()

    if not rows:
        await update.message.reply_text("Событий пока нет.", reply_markup=build_main_menu(False))
        return

    lines = []
    for idx, (evt, creator_name) in enumerate(rows, start=1):
        lines.append(
            f"{idx}. «{evt.title}»\n"
            f"   Дата: {evt.event_date.strftime('%d.%m.%Y')}\n"
            f"   Создатель: {creator_name}"
        )
    text = "📋 Список событий:\n\n" + "\n\n".join(lines)
    await update.message.reply_text(text, reply_markup=build_main_menu(False))

# --- Панель администратора ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("👥 Управление пользователями", callback_data="manage_users")],
        [InlineKeyboardButton("🗓 Управление событиями",   callback_data="manage_events_admin")],
    ]
    await update.message.reply_text(
        "🔧 Панель администратора:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- Управление пользователями ---
async def manage_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    session = SessionLocal()
    users = session.query(User).order_by(User.id).all()
    session.close()

    if not users:
        await query.edit_message_text("Пользователей пока нет.")
        return

    text = "👥 Список пользователей:\n\n"
    buttons = []
    for u in users:
        text += f"• {u.id}: {u.full_name}  ({'АДМИН' if u.is_admin else u.position})\n"
        buttons.append([
            InlineKeyboardButton("🔼 Сделать админом", callback_data=f"promote_{u.id}"),
            InlineKeyboardButton("❌ Удалить",           callback_data=f"delete_user_{u.id}")
        ])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def promote_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[1])
    session = SessionLocal()
    u = session.query(User).get(user_id)
    if u:
        u.is_admin = True
        session.commit()
        await query.edit_message_text(f"✅ {u.full_name} теперь администратор.")
    else:
        await query.edit_message_text("⚠️ Пользователь не найден.")
    session.close()

async def delete_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[2])
    session = SessionLocal()
    u = session.query(User).get(user_id)
    if u:
        session.delete(u)
        session.commit()
        await query.edit_message_text(f"🗑 Пользователь {u.full_name} удалён.")
    else:
        await query.edit_message_text("⚠️ Пользователь не найден.")
    session.close()

# --- Админ: управление событиями ---
async def manage_events_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    session = SessionLocal()
    rows = (
        session.query(Event, User.full_name)
               .join(User, Event.creator)
               .order_by(Event.event_date)
               .all()
    )
    session.close()

    if not rows:
        await query.edit_message_text("Событий пока нет.")
        return

    text_lines = ["🗓 Все события:"]
    buttons = []
    for evt, creator_name in rows:
        text_lines.append(
            f"• {evt.id}. «{evt.title}» — {evt.event_date.strftime('%d.%m.%Y')} (создатель: {creator_name})"
        )
        buttons.append([
            InlineKeyboardButton("❌ Удалить", callback_data=f"admin_delete_evt_{evt.id}")
        ])

    await query.edit_message_text(
        "\n".join(text_lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def admin_delete_evt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    evt_id = int(query.data.split("_")[-1])

    session = SessionLocal()
    evt = session.query(Event).get(evt_id)
    if evt:
        title = evt.title
        session.delete(evt)
        session.commit()
        await query.edit_message_text(f"✅ Событие «{title}» удалено.")
    else:
        await query.edit_message_text("⚠️ Событие не найдено.")
    session.close()

# Обновлённый хэндлер справки
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "❓ *Справка по боту*\n\n"
        "🔹 *Регистрация* — запишите свои ФИО, должность и дату рождения.\n"
        "🔹 *События* — просмотреть список всех запланированных событий.\n"
        "🔹 *Создать событие* — задать своё мероприятие, выбрать участников и частоту напоминаний.\n"
        "🔹 *Управление событиями* — посмотреть и удалить только свои события.\n"
        "🔹 *Дни рождения* — бот автоматически напомнит всем о ваших днях рождения за неделю.\n\n"
        "Напоминания приходят в 13:00 МСК по выбранному графику.\n"
        "Если есть вопросы или предложения — пишите администратору."
    )
    # Отправляем как Markdown, чтобы выделить пункты
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=build_main_menu(False))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Ошибка:", exc_info=context.error)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    # Разговорчики регистрации и событий
    reg_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Регистрация$'), registration_start)],
        states={
            REGISTER_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)],
            REGISTER_POSITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_position)],
            REGISTER_BIRTHDATE:[MessageHandler(filters.TEXT & ~filters.COMMAND, register_birthdate)],
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex('^Меню$'), start)],
        allow_reentry=True,
    )
    evt_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^Создать событие$'), event_start)],
        states={
            EVENT_TITLE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, event_title)],
            EVENT_DESC:      [MessageHandler(filters.TEXT & ~filters.COMMAND, event_desc)],
            EVENT_INTERVAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, event_interval)],
            EVENT_DATE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, event_date)],
            EVENT_USERS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, event_users)],
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex('^Меню$'), start)],
        allow_reentry=True,
    )

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex('^Меню$'), start))
    app.add_handler(reg_conv)
    app.add_handler(evt_conv)
    app.add_handler(MessageHandler(filters.Regex('^События$'), events_list))
    app.add_handler(MessageHandler(filters.Regex('^Управление событиями$'), manage_events))
    app.add_handler(CallbackQueryHandler(delete_evt_callback, pattern=r"^delete_evt_\d+$"))
    app.add_handler(MessageHandler(filters.Regex('^Панель администратора$'), admin_panel))
    app.add_handler(CommandHandler("test_me", test_me))
    app.add_handler(CommandHandler("test_bday", test_birthday))
    app.add_handler(CommandHandler("test", test_notification))

    # Admin: users
    app.add_handler(CallbackQueryHandler(manage_users_callback,   pattern=r"^manage_users$"))
    app.add_handler(CallbackQueryHandler(promote_user_callback,   pattern=r"^promote_\d+$"))
    app.add_handler(CallbackQueryHandler(delete_user_callback,    pattern=r"^delete_user_\d+$"))

    # Admin: events
    app.add_handler(CallbackQueryHandler(manage_events_admin_callback, pattern=r"^manage_events_admin$"))
    app.add_handler(CallbackQueryHandler(admin_delete_evt_callback,     pattern=r"^admin_delete_evt_\d+$"))

    app.add_handler(MessageHandler(filters.Regex('^Справка$'), help_command))
    app.add_error_handler(error_handler)

    session = SessionLocal()
    for u in session.query(User).all():
        schedule_birthday_reminder(
            app.job_queue,
            u.id,
            u.birth_date
        )
    session.close()




    print("Бот запущен. Нажмите Ctrl+C для остановки.")
    app.run_polling()
