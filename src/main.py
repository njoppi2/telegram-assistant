import logging
import signal
import asyncio
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from src.agent.graph import agent_graph
import src.agent.shared as shared
from src.config import settings

logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 10


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception while processing Telegram update", exc_info=context.error)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message or not update.message.text:
        return

    user_id = str(update.effective_user.id)
    username = update.effective_user.username or ""
    text = update.message.text

    # Command to kill the last execution
    if text.strip() in ("/kill", "MATAR"):
        shared.cancel_requested.add(user_id)
        proc = shared.active_subprocesses.get(user_id)
        status_msg = shared.active_status_messages.get(user_id)
        
        # Kill the process if active
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                logger.info(f"User {user_id} requested MATAR. Process {proc.pid} terminated.")
                await asyncio.sleep(0.5)
                if proc.returncode is None:
                    proc.kill()
            except Exception as e:
                logger.error(f"Failed to kill process: {e}")

        # Update status message if available
        if status_msg:
            try:
                await status_msg.edit_text("Execução interrompida.")
            except Exception as e:
                logger.error(f"Failed to edit status message on MATAR: {e}")
        
        # React with thumbs up on the MATAR message
        try:
            if update.message:
                await update.message.set_reaction(reaction="👍")
        except Exception as e:
            logger.error(f"Failed to react to MATAR: {e}")
            
        shared.active_subprocesses.pop(user_id, None)
        shared.active_status_messages.pop(user_id, None)
        return

    # If no password is configured, disable the auth gate entirely.
    auth_password = settings.AUTH_PASSWORD.strip()
    if not auth_password:
        auth = {"failed_attempts": 0, "is_blocked": 0, "is_authenticated": 1}
    else:
        # Load auth state from SQLite only when auth is enabled.
        auth = await shared.get_user_auth(user_id)
    
    if auth["is_blocked"]:
        logger.warning(f"Blocked user {user_id} attempted message")
        return

    if not auth["is_authenticated"]:
        if text.strip() == auth_password:
            await shared.update_user_auth(user_id, failed_attempts=0, is_blocked=0, is_authenticated=1)
            logger.info(f"User {user_id} authenticated successfully")
            await update.message.reply_text("Access granted. You can now use the bot.")
        else:
            new_failed = auth["failed_attempts"] + 1
            is_blocked = 1 if new_failed >= MAX_FAILED_ATTEMPTS else 0
            await shared.update_user_auth(user_id, failed_attempts=new_failed, is_blocked=is_blocked, is_authenticated=0)
            
            logger.warning(f"Failed auth attempt for user {user_id}: {new_failed} attempts")
            if is_blocked:
                logger.error(f"User {user_id} blocked after {MAX_FAILED_ATTEMPTS} failed attempts")
                return
            remaining = MAX_FAILED_ATTEMPTS - new_failed
            await update.message.reply_text(f"This bot is password protected. Send the password to access. ({remaining} attempts remaining)")
        return

    # LOCK and PROCESS
    async with shared.user_locks[user_id]:
        # CLEAR cancellation flag ONLY after acquiring the lock for a NEW message
        shared.cancel_requested.discard(user_id)
        
        async with shared.action_limiter:
            logger.info(f"Processing message from {user_id}: {text[:50]}...")

            status_msg = None
            history = await shared.get_user_history(user_id)
            history = history[-20:]

            initial_state = {
                "user_id": user_id,
                "username": username,
                "profile_slug": "",
                "profile_persona": "",
                "messages": history,
                "incoming_text": text,
                "response_text": "",
                "intent": "",
                "study_session": None,
            }

            final_state = initial_state.copy()

            try:
                async for event in agent_graph.astream(initial_state, stream_mode="updates"):
                    # Global check: if user cancelled while streaming, stop everything
                    if user_id in shared.cancel_requested:
                        logger.info(f"Stream for user {user_id} stopped due to MATAR.")
                        break

                    for node_name, state_update in event.items():
                        if "messages" in state_update:
                            new_msgs = state_update["messages"]
                            history.extend(new_msgs)
                            history = history[-20:]
                            await shared.save_user_history(user_id, history)
                        
                        final_state.update(state_update)

                    if node_name == "detect_intent" and final_state.get("intent") == "action":
                        try:
                            if update.message:
                                await update.message.set_reaction(reaction="👨‍💻")
                                status_msg = await update.message.reply_text("⏳ Processando ação no terminal...")
                                shared.active_status_messages[user_id] = status_msg
                        except Exception as e:
                            logger.error(f"Error in status setup: {e}")

            except Exception as e:
                logger.error(f"Graph execution failed: {e}")
                final_state["response_text"] = f"Erro na execução: {str(e)}"

        # Final cleanup of status message tracking
        shared.active_status_messages.pop(user_id, None)

        # Final suppression check before sending/editing
        if user_id in shared.cancel_requested:
            logger.info(f"Output for user {user_id} suppressed at final stage.")
            if update.message:
                try: await update.message.set_reaction(reaction=None)
                except: pass
            return

        response_text = final_state.get("response_text", "")
        if response_text and update.message:
            MAX_MSG_LEN = 4000
            if len(response_text) > MAX_MSG_LEN:
                response_text = response_text[:MAX_MSG_LEN] + "\n\n[Mensagem muito longa, truncada...]"

            try:
                if status_msg:
                    await status_msg.edit_text(response_text, parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN)
            except BadRequest as e:
                if "parse" in str(e).lower():
                    logger.warning(f"Markdown parse error, sending as plain text.")
                    if status_msg: await status_msg.edit_text(response_text)
                    else: await update.message.reply_text(response_text)
                else:
                    logger.error(f"Error sending message: {e}")
            
            if final_state.get("intent") == "action":
                try: await update.message.set_reaction(reaction=None)
                except: pass


def main():
    import asyncio
    import os
    import sys
    if settings.ARCH_GYM_PATH:
        sys.path.insert(0, settings.ARCH_GYM_PATH)
        os.environ.setdefault("ARCH_GYM_MODEL", "gemini/gemini-3-flash-preview")
        os.environ.setdefault("GEMINI_API_KEY", settings.GOOGLE_API_KEY)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(shared.init_db())
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    # Avoid logging Telegram request URLs (the bot token is part of the path).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).concurrent_updates(True).build()
    app.add_handler(MessageHandler(filters.TEXT, message_handler))
    app.add_error_handler(error_handler)
    logger.info("Bot starting with polling and concurrent updates...")
    app.run_polling()


if __name__ == "__main__":
    main()
