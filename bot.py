import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import settings
from tools import etl, get_my_issues, check_personal_track_changes, format_my_issue_message, check_sla_warning

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logging.debug(f"Telegram bot token: {settings.telegram.telegram_bot_token}")

user_chat_ids = set()

# Personal track monitoring state: chat_id -> None (not yet init) | {issue_key -> {status, sla_warned}}
my_watch_state: Dict[int, Optional[Dict]] = {}

async def alarm(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the alarm message."""
    job = context.job
    text = etl(mode='broadcast')
    await context.bot.send_message(chat_id=job.chat_id, text=text)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    await update.message.reply_text(text="Привет! Я бот для напоминаний о новых треках.\n"
                                         "Если вы хотите получать уведомления о новых треках используйте команду:\n"
                                         "/set seconds\n", parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command"""
    msg = """
/set <seconds> - подписаться на обновления о новых треках
/unset <seconds> - отписаться от уведомлений каждые <seconds>
/stop - отписаться от всех уведомлений сразу
/check - посмотреть какие треки в Open and Unassigned
/get <ltbetx-2977> - посмотреть конкретный трек
/zen - обязанности дежурного

Мои треки:
/mywatch [seconds] - следить за своими треками (изменения статуса, SLA)
/myunwatch - остановить слежку за своими треками
/mycheck - разовая проверка своих активных треков
"""
    await update.message.reply_text(text=msg, parse_mode=ParseMode.MARKDOWN)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop command"""
    current_jobs = context.job_queue.jobs()
    for job in current_jobs:
        remove_job_if_exists(job.name, context)

    await update.message.reply_text("Вы больше не будете получать уведомления о новых треках.")


async def send_reminder(chat_id: int, title: str, description: str = None) -> None:
    """Send reminder to specific user"""
    try:
        logger.info(f"Sending reminder to chat_id {chat_id}: {title}")
        message = f"🔔 {title}"
        if description:
            message += f"\n\n{description}"
            await application.bot.send_message(chat_id=chat_id, text=message)
        logger.info(f"Reminder sent successfully to {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send reminder to {chat_id}: {e}")


async def broadcast_reminder(broadcast_message: str) -> None:
    """Send reminder to all subscribed users"""
    title = 'Напоминание о новых треках'
    logger.info(f"Broadcasting reminder to {len(user_chat_ids)} users: {title}")
    for chat_id in user_chat_ids:
        await send_reminder(chat_id, title, broadcast_message)


async def check_tracks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check current Open or Unassigner Tracks and send the message with info to requester"""

    try:
        mode = context.args[0] if context.args else 'check'
        logger.info(f"Check Opened or Unnassigned issues for user {update.effective_chat.id} with mode {mode}")
        message = etl(mode=mode)
        print(message)
        await update.message.reply_text(text=message) #, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Failed to check issues for {update.effective_chat.id}: {e}")


async def get_issues(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get info about the specified issue's by their numbers """
    try:
        logger.info(f"user: {update.effective_chat.username}, requests: {update.message.text}")
        user_request = ", ".join(update.message.text.lower().split()[1:])
        search_string = f"key in ({user_request})"
        message = etl(mode='check', search_string=search_string)
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f'Failed to get issues for {update.effective_chat.id} by request: {update.message.text}')
        await update.message.reply_text(f'there is an error. check logs!', parse_mode=ParseMode.MARKDOWN)


def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_message.chat_id
    logging.debug(f'FUNCTION ADD_JOB CONTEX: {context.args}')
    try:
        interval = int(context.args[0])
        if interval < 0:
            await update.effective_message.reply_text("Sorry we can not go back to future!")
            return
        elif interval < 600:
            interval = 600
        job_name = f'{chat_id}_send_updates_{interval}'
        job_removed = remove_job_if_exists(str(chat_id), context)

        context.job_queue.run_repeating(
            callback=alarm,
            interval=timedelta(seconds=interval),
            chat_id=chat_id,
            name=job_name,
        )

        text = f"Timer for {interval} seconds is successfully set!"
        if job_removed:
            text += "\nOld one was removed."
        await update.effective_message.reply_text(text)

    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /set <seconds>")


async def unset_timer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove the job if the user changed their mind."""
    try:
        chat_id = update.message.chat_id
        interval = int(context.args[0])
        job_name = f'{chat_id}_send_updates_{interval}'
        job_removed = remove_job_if_exists(job_name, context)
        text = "Timer successfully cancelled!" if job_removed else "You have no active timer."
        logger.info(f'User {chat_id} remove job {job_name}')
        await update.message.reply_text(text)

    except Exception as e:
        await update.effective_message.reply_text("Usage: /unset <seconds>")


async def send_updates(context: ContextTypes.DEFAULT_TYPE):
    """Handle to reminders job"""
    message = etl(mode='broadcast')
    logging.info(message)
    await broadcast_reminder(broadcast_message=message)


async def get_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        current_jobs = context.job_queue.jobs()
        logging.debug(f'CURRENT JOBS: {current_jobs}')
        message = f'Your active timers:\n'
        for job in current_jobs:
            message += f"{job.name}\n"
    except Exception as e:
        message = f'Something goes wrong! Check logs! {e}'

    logging.debug(f'GET JOBS MESSAGE: {message}')
    await update.message.reply_text(text=message, parse_mode=ParseMode.HTML)

async def duty_zen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = '''
    Дневные дежурства в рабочее время
    Цель: дневной дежурный отвечает за соблюдение SLA Time to first response для всех треков в статусе Open.

Реализация: дневной дежурный назначается сроком на 1 неделю.
Обязанности:

1. Проверять папку unassigned не реже одного раза в 30 минут.
2. При появлении нового трека - взять в работу, если позволяет загрузка и специализация.
3. Если загрузка и специализация не позволяют, связаться с профильным тим лидом, который примет решение на кого назначить трек. 
               Определение профильного тим лида:
               AKBREXT, System/Service AML/Anti-Fraud - Сергей-Роман
               BOTEXT, RSBEXT - Иван
               LTBEXT - Семён
               GPBEXT - Тимофей
               INGSEXT - Антон-Сергей
               VBREXT, LOKOBEXT, EUBEXT (databorn Jira) - Ярослав
               LMREXT, OTP - Тимофей-Антон
               MKBEXT, SZGEXT, AVOEXT (databorn Jira), MTSBEXT - Марат-Айнур-Роман-Тимофей
               
4. Проследить, чтобы трек был взят в работу (назначен Assignee, статус - In progress). Если Time to first response < 1 часа, следует самостоятельно перевести трек в статус  In progress.
5. Продолжать следить за треком до перевода трека в статус In progress.
6. В случае невозможности исполнять обязанности (пропал доступ к Jira, заболел и т.д.) сообщить руководителю отдела.
7. Просроченные TTFR учитываются дежурившему при расчёте бонусной части ЗП
    '''
    await update.message.reply_text(text=message, parse_mode=ParseMode.MARKDOWN)

async def mywatch_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic job: check personal tracks for status changes and SLA warnings."""
    chat_id = context.job.chat_id
    try:
        current_issues = get_my_issues()
        prev_states = my_watch_state.get(chat_id)  # None = first run

        notifications, new_states = check_personal_track_changes(
            current_issues,
            prev_states,
            sla_warn_ms=settings.telegram.sla_warning_threshold_ms,
        )
        my_watch_state[chat_id] = new_states

        for msg in notifications:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"mywatch_job failed for {chat_id}: {e}")


async def mywatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /mywatch [seconds] — start monitoring personal tracks."""
    chat_id = update.effective_message.chat_id
    try:
        interval = int(context.args[0]) if context.args else settings.telegram.my_watch_default_interval
        if interval < 60:
            interval = 60

        job_name = f'{chat_id}_mywatch'
        remove_job_if_exists(job_name, context)
        my_watch_state[chat_id] = None  # force re-init on restart

        context.job_queue.run_repeating(
            callback=mywatch_job,
            interval=timedelta(seconds=interval),
            chat_id=chat_id,
            name=job_name,
            first=0,
        )
        await update.effective_message.reply_text(
            f"Слежу за вашими треками каждые {interval} сек.\n"
            f"Уведомлю при изменении статуса или когда SLA менее {settings.telegram.sla_warning_threshold_ms // 60000} мин."
        )
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Использование: /mywatch [seconds]")


async def myunwatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /myunwatch — stop monitoring personal tracks."""
    chat_id = update.message.chat_id
    job_name = f'{chat_id}_mywatch'
    removed = remove_job_if_exists(job_name, context)
    my_watch_state.pop(chat_id, None)
    if removed:
        await update.message.reply_text("Перестал следить за вашими треками.")
    else:
        await update.message.reply_text("Слежка не была запущена.")


async def mycheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /mycheck — one-shot view of personal active tracks."""
    try:
        issues = get_my_issues()
        if not issues:
            await update.message.reply_text("Нет активных треков, назначенных на вас.")
            return

        parts = []
        for issue in issues:
            has_warning = check_sla_warning(issue, settings.telegram.sla_warning_threshold_ms)
            event = 'sla_warning' if has_warning else 'current'
            parts.append(format_my_issue_message(issue, event))

        # Telegram limit is 4096 chars — split into chunks
        chunk, chunk_len = [], 0
        for part in parts:
            part_len = len(part) + 2  # +2 for '\n\n'
            if chunk and chunk_len + part_len > 4000:
                await update.message.reply_text('\n\n'.join(chunk), parse_mode=ParseMode.HTML)
                chunk, chunk_len = [], 0
            chunk.append(part)
            chunk_len += part_len
        if chunk:
            await update.message.reply_text('\n\n'.join(chunk), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"mycheck failed for {update.effective_chat.id}: {e}")
        await update.message.reply_text("Ошибка при получении треков. Проверьте логи.")


# Create application
logger.info("Initializing Telegram bot...")
application = Application.builder().token(settings.telegram.telegram_bot_token).build()

# Add handlers
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("stop", stop_command))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("check", check_tracks))
application.add_handler(CommandHandler("get", get_issues))
application.add_handler(CommandHandler("set", set_timer))
application.add_handler(CommandHandler("unset", unset_timer))
application.add_handler(CommandHandler("jobs", get_jobs))
application.add_handler(CommandHandler("zen", duty_zen))
application.add_handler(CommandHandler("mywatch", mywatch_command))
application.add_handler(CommandHandler("myunwatch", myunwatch_command))
application.add_handler(CommandHandler("mycheck", mycheck_command))


def start_bot():
    """Start the bot"""
    logger.info("Starting Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    start_bot()
