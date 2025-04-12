import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import settings
from tools import check_issues, etl, parse_jira_issues, prepare_message

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logging.info(f"Telegram bot token: {settings.telegram.telegram_bot_token}")

# There won't be many subscribers - we don't make databases or user models.
user_chat_ids = set()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    chat_id = update.effective_chat.id
    user_chat_ids.add(chat_id)
    logger.info(f"User {chat_id} subscribed to reminders")
    await update.message.reply_text(
        text="Привет! Я бот для напоминаний о новых треках.\nТеперь вы будете получать уведомления о ваших задачах.",
        parse_mode=ParseMode.HTML)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command"""
    msg = """
/start - подписаться на обновления о новых треках
/stop - отписаться от обновлений
/check - посмотреть какие в Open and Unassigned
/get <ltbetx-2977> - посмотреть конкретный трек
"""
    await update.message.reply_text(
        text=msg,
        parse_mode=ParseMode.MARKDOWN
    )
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop command"""
    chat_id = update.effective_chat.id
    if chat_id in user_chat_ids:
        user_chat_ids.remove(chat_id)
        logger.info(f"User {chat_id} unsubscribed from reminders")
        await update.message.reply_text("Вы больше не будете получать уведомления о новых треках.")
    else:
        await update.message.reply_text("Вы не подписаны на уведомления.")

async def get_subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id == settings.telegram.telegram_admin_chat_id:
        message = f'{user_chat_ids}'
    else:
        message = f'Forbidden! Only for admins'
    await update.message.reply_text(text=message)


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
        logger.info(f"Check Opened or Unnassigned issues for user {update.effective_chat.id}")
        json_data = check_issues()
        issues = parse_jira_issues(json_data)
        msg = prepare_message(issues)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
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


async def send_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle to reminders job"""
    message = etl(mode='broadcast')
    logging.info(message)
    await broadcast_reminder(broadcast_message=message)


# Create application
logger.info("Initializing Telegram bot...")
application = Application.builder().token(settings.telegram.telegram_bot_token).build()

# Create Queue
job_queue = application.job_queue
job_queue.run_repeating(callback=send_updates, interval=timedelta(seconds=60))

# Add handlers
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("stop", stop_command))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("check", check_tracks))
application.add_handler(CommandHandler("get", get_issues))
application.add_handler(CommandHandler("send", send_updates))
application.add_handler(CommandHandler("subscribers", get_subscribers))


def start_bot():
    """Start the bot"""
    logger.info("Starting Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    start_bot()
