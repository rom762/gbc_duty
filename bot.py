import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import settings
from tools import etl

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logging.debug(f"Telegram bot token: {settings.telegram.telegram_bot_token}")

user_chat_ids = set()

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
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

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


# Create application
logger.info("Initializing Telegram bot...")
application = Application.builder().token(settings.telegram.telegram_bot_token).build()

# Create Queue
# общую очередь останавливаем теперь у каждого юзера своя
# job_queue = application.job_queue
# job_queue.run_repeating(
#     callback=send_updates,
#     interval=timedelta(minutes=settings.telegram.telegram_default_reminder_period)
# )

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


# Add handlers
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("stop", stop_command))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("check", check_tracks))
application.add_handler(CommandHandler("get", get_issues))
application.add_handler(CommandHandler("set", set_timer))
application.add_handler(CommandHandler("unset", unset_timer))
application.add_handler(CommandHandler("jobs", get_jobs))


def start_bot():
    """Start the bot"""
    logger.info("Starting Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    start_bot()
