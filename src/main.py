from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from src.agent.graph import agent_graph
from src.config import settings


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or ""
    text = update.message.text

    result = await agent_graph.ainvoke(
        {
            "user_id": user_id,
            "username": username,
            "profile_slug": "",
            "messages": [],
            "incoming_text": text,
            "response_text": "",
        }
    )

    await update.message.reply_text(result["response_text"])


def main():
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("Bot starting with polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
