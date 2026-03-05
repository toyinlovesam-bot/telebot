import os
import re
import logging
import asyncio
from datetime import timedelta, datetime
from dotenv import load_dotenv
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask
import threading

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ALLOWED_CHAT_IDS = os.getenv('ALLOWED_CHAT_IDS', '').split(',') if os.getenv('ALLOWED_CHAT_IDS') else []
MUTE_DURATION = int(os.getenv('MUTE_DURATION', '60'))  # Mute duration in minutes
PORT = int(os.getenv('PORT', 8080))

# Telegram link patterns
TELEGRAM_LINK_PATTERNS = [
    r'(?:https?://)?(?:www\.)?t\.me/\S+',
    r'(?:https?://)?(?:www\.)?telegram\.me/\S+',
    r'(?:https?://)?(?:www\.)?telegram\.dog/\S+',
    r'(?:https?://)?(?:www\.)?telesco\.pe/\S+',
    r'@\w+',  # Telegram usernames
]

# Flask app for keep-alive
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

def contains_telegram_link(text: str) -> bool:
    """Check if text contains any Telegram link patterns"""
    if not text:
        return False
    
    for pattern in TELEGRAM_LINK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

async def mute_user(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    """Mute a user in the chat"""
    try:
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False
        )
        
        mute_until = datetime.now() + timedelta(minutes=MUTE_DURATION)
        
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=mute_until
        )
        return True
    except Exception as e:
        logger.error(f"Failed to mute user {user_id}: {e}")
        return False

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    try:
        # Check if message exists
        if not update.message:
            return
        
        # Check if message is from a group/supergroup
        if not update.message.chat.type in ['group', 'supergroup']:
            return
        
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        # Check if this chat is allowed to be monitored
        if ALLOWED_CHAT_IDS and str(chat_id) not in ALLOWED_CHAT_IDS:
            return
        
        # Get message text (including captions)
        message_text = ""
        if update.message.text:
            message_text = update.message.text
        elif update.message.caption:
            message_text = update.message.caption
        
        # Check for forwarded messages
        if update.message.forward_date:
            # Check if forwarded from a channel with Telegram link
            if update.message.forward_from_chat and update.message.forward_from_chat.username:
                if contains_telegram_link(update.message.forward_from_chat.username):
                    await update.message.delete()
                    await mute_user(context, chat_id, user_id)
                    return
        
        # Check if message contains a Telegram link
        if contains_telegram_link(message_text):
            logger.info(f"Telegram link detected from user {user_id} in chat {chat_id}")
            
            # Delete the message
            try:
                await update.message.delete()
                logger.info(f"Message deleted from user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete message: {e}")
            
            # Mute the user
            muted = await mute_user(context, chat_id, user_id)
            
            if muted:
                # Send notification
                try:
                    user_mention = f"@{update.effective_user.username}" if update.effective_user.username else f"User {user_id}"
                    warning_message = await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ {user_mention} has been muted for {MUTE_DURATION} minutes for posting Telegram links.",
                        parse_mode='HTML'
                    )
                    
                    # Auto-delete warning message after 30 seconds
                    asyncio.create_task(delete_message_after_delay(context.bot, warning_message.chat_id, warning_message.message_id, 30))
                except Exception as e:
                    logger.error(f"Failed to send warning: {e}")
    
    except Exception as e:
        logger.error(f"Error handling message: {e}")

async def delete_message_after_delay(bot, chat_id: int, message_id: int, delay: int):
    """Delete a message after a delay"""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "🤖 Bot is active!\n\n"
        "This bot automatically deletes Telegram links and mutes users.\n\n"
        "Commands:\n"
        "/status - Check bot status\n"
        "/help - Show this help message"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    try:
        # Check if user is admin
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        is_admin = chat_member.status in ['administrator', 'creator']
        
        if is_admin:
            await update.message.reply_text(
                f"✅ Bot is running!\n\n"
                f"Chat ID: `{chat_id}`\n"
                f"Mute duration: {MUTE_DURATION} minutes\n"
                f"Monitoring: {'All chats' if not ALLOWED_CHAT_IDS else 'Selected chats'}\n"
                f"Bot uptime: Active",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("This command is only for admins.")
    except Exception as e:
        logger.error(f"Status command error: {e}")
        await update.message.reply_text("Error checking status. Make sure I'm an admin in this group.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await update.message.reply_text(
        "📚 **How to use this bot:**\n\n"
        "1. Add the bot to your group as an **administrator**\n"
        "2. Give the bot permission to delete messages and restrict members\n"
        "3. The bot will automatically detect and delete Telegram links\n"
        "4. Users posting Telegram links will be muted\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/status - Check bot status (admins only)\n"
        "/help - Show this help message\n\n"
        "**Note:** The bot must be an admin to function properly.",
        parse_mode='Markdown'
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")

async def post_init(application: Application):
    """Run after bot initialization"""
    logger.info("Bot initialized successfully!")
    logger.info(f"Monitoring chats: {ALLOWED_CHAT_IDS if ALLOWED_CHAT_IDS else 'All chats'}")
    logger.info(f"Mute duration: {MUTE_DURATION} minutes")

def main():
    """Start the bot"""
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN provided! Please set it in .env file or environment variables.")
        return
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask server started on port {PORT}")
    
    # Create application with post_init
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Message handler for all messages
    application.add_handler(MessageHandler(
        filters.TEXT | filters.CAPTION | filters.FORWARDED,
        handle_message
    ))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    logger.info("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
