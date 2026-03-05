import os
import re
import time
from flask import Flask, request
import telebot
from telebot.types import Update, ChatPermissions

# ============== CONFIG ==============
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Please set BOT_TOKEN environment variable on Render")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
# ===================================

def contains_telegram_link(message):
    """Detect t.me / telegram.me / telegram.dog links in text, caption, or entities"""
    if not message:
        return False

    text = (message.text or message.caption or "").lower()

    # Check message entities (proper Telegram links)
    entities = message.entities or message.caption_entities or []
    for entity in entities:
        if entity.type in ("url", "text_link"):
            url = entity.url if entity.type == "text_link" else text[entity.offset:entity.offset + entity.length]
            if re.search(r"(t\.me|telegram\.(me|dog))", url, re.IGNORECASE):
                return True

    # Fallback regex for plain text
    if re.search(r"(?:https?://)?(?:www\.)?(t\.me|telegram\.(me|dog))", text, re.IGNORECASE):
        return True

    return False


# ====================== BOT HANDLERS ======================

@bot.message_handler(func=lambda m: True, content_types=["text", "photo", "video", "document", "audio", "voice", "sticker", "animation", "video_note"])
def handle_messages(message):
    if message.chat.type not in ["group", "supergroup"]:
        return

    if contains_telegram_link(message):
        try:
            # Delete the message
            bot.delete_message(message.chat.id, message.message_id)

            # Mute user for 1 hour (you can change 3600 to any seconds)
            until_date = int(time.time()) + 3600
            bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False,
                ),
                until_date=until_date,
            )

            bot.send_message(
                message.chat.id,
                f"🚫 **Telegram links are forbidden!**\n"
                f"User {message.from_user.first_name} (@{message.from_user.username or 'no-username'}) "
                f"has been muted for 1 hour.",
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"Error handling spam: {e}")


@bot.message_handler(content_types=["new_chat_members"])
def welcome_new_members(message):
    for member in message.new_chat_members:
        if member.id == bot.get_me().id:
            bot.send_message(
                message.chat.id,
                "👋 Hello everyone!\n\n"
                "I'm your group manager bot.\n"
                "• I delete Telegram links and mute the sender\n"
                "• I welcome new members\n"
                "Make sure I'm an **Admin** with these permissions:\n"
                "• Delete messages\n"
                "• Restrict members",
            )
            return

        bot.send_message(
            message.chat.id,
            f"👋 Welcome to the group, {member.first_name}!\n"
            "Please follow the rules — no Telegram links!",
        )


@bot.message_handler(commands=["help", "start"])
def send_help(message):
    if message.chat.type == "private":
        bot.send_message(
            message.chat.id,
            "🤖 This bot is for groups only.\n\n"
            "1. Add me to your group\n"
            "2. Make me Admin (delete messages + restrict members)\n"
            "3. Done! I will auto-delete Telegram links and mute spammers.",
        )
    else:
        bot.reply_to(
            message,
            "✅ **Bot Commands**\n"
            "/help — show this message\n\n"
            "Automatic features:\n"
            "• Deletes any Telegram link (t.me, telegram.me, etc.)\n"
            "• Mutes the sender for 1 hour\n"
            "• Welcomes new members",
        )


# ====================== WEBHOOK (Render) ======================

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook_handler():
    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data().decode("utf-8")
        update = Update.de_json(json_string)
        bot.process_new_updates([update])
    return "OK", 200


@app.route("/setwebhook", methods=["GET"])
def set_webhook_route():
    """Manual trigger to set webhook (visit once after deploy)"""
    bot.remove_webhook()
    url = f"{os.environ.get('RENDER_EXTERNAL_URL')}/{TOKEN}"
    bot.set_webhook(url=url)
    return f"✅ Webhook set to: {url}"


@app.route("/")
def home():
    return "🤖 Telegram Group Manager Bot is running on Render!"


# ====================== START ======================
if __name__ == "__main__":
    # Auto-set webhook on Render startup
    if "RENDER_EXTERNAL_URL" in os.environ:
        bot.remove_webhook()
        webhook_url = f"{os.environ['RENDER_EXTERNAL_URL']}/{TOKEN}"
        bot.set_webhook(url=webhook_url)
        print(f"✅ Webhook successfully set to {webhook_url}")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
