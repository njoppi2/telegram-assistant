"""Arch-gym study session node for LangGraph — topic-based dynamic system.

Handles /study, /skip, /stop, /stats commands and routes in-session
answers through arch-gym's topic_core API (LLM-generated questions per topic).
"""

import asyncio
import json
import logging
import time

from src.agent.shared import (
    clear_study_session,
    get_study_session,
    save_study_session,
)
from src.agent.state import AgentState

logger = logging.getLogger(__name__)

STUDY_COMMANDS = {"/study", "/skip", "/stop", "/stats", "/archstats", "/cancel", "/quit"}


def _get_topic_core():
    try:
        import arch_gym.bot.topic_core as tc
        return tc
    except ImportError as e:
        raise ImportError(f"arch-gym not available: {e}. Check ARCH_GYM_PATH in .env") from e


async def check_study_session_node(state: AgentState) -> dict:
    """Pre-intent routing: intercepts messages belonging to a study session."""
    user_id = state["user_id"]
    text = state["incoming_text"].strip()
    cmd = text.lower().split()[0] if text else ""
    capabilities = set(state.get("profile_capabilities", []))
    has_study = "study" in capabilities
    has_run = "run" in capabilities

    if cmd == "/run":
        if not has_run:
            return {
                "intent": "direct_response",
                "response_text": "This command is not enabled for your profile.",
                "study_session": None,
            }
        remainder = text[4:].strip()
        if not remainder:
            return {"intent": "arch_study", "study_session": None}
        return {"intent": "action", "incoming_text": remainder, "study_session": None}

    if cmd == "/help":
        if has_study or has_run:
            return {"intent": "arch_study", "study_session": None}
        return {
            "intent": "direct_response",
            "response_text": "This command is not enabled for your profile.",
            "study_session": None,
        }

    if cmd in STUDY_COMMANDS:
        if not has_study:
            return {
                "intent": "direct_response",
                "response_text": "This command is not enabled for your profile.",
                "study_session": None,
            }
        return {"intent": "arch_study", "study_session": None}

    if has_study:
        session = await get_study_session(user_id)
        if session:
            return {"intent": "arch_study", "study_session": session}

    return {"intent": "", "study_session": None}


async def arch_study_node(state: AgentState) -> dict:
    """Main study session dispatcher."""
    user_id = state["user_id"]
    text = state["incoming_text"].strip()
    cmd = text.lower().split()[0] if text else ""

    session = state.get("study_session") or await get_study_session(user_id)

    if cmd == "/study":
        return await _start_session(user_id)

    if cmd == "/help":
        return {
            "response_text": (
                "*Commands*\n\n"
                "/study — start today's study session\n"
                "/skip — skip current topic\n"
                "/stop — end session\n"
                "/stats — show progress\n"
                "/run <task> — execute a terminal action\n"
                "/kill — cancel a running /run\n"
                "/help — show this message"
            )
        }

    if cmd == "/run":
        return {"response_text": "Usage: /run <task description>"}

    if cmd in ("/stop", "/cancel", "/quit"):
        await clear_study_session(user_id)
        return {"response_text": "Study session ended. See you next time!"}

    if cmd in ("/stats", "/archstats"):
        return await _handle_stats()

    if cmd == "/skip":
        if not session:
            return {"response_text": "No active study session. Send /study to start."}
        return await _advance_to_next(user_id, session, skipped=True)

    if not session:
        return {"response_text": "No active study session. Send /study to start one."}

    phase = session.get("phase", "question")

    if phase == "question":
        return await _handle_answer(user_id, session, text)
    elif phase == "followup":
        return await _handle_followup_answer(user_id, session, text)

    return {"response_text": "Unexpected state. Send /study to restart."}


async def _start_session(user_id: str) -> dict:
    try:
        tc = _get_topic_core()
    except ImportError as e:
        return {"response_text": str(e)}

    try:
        queue = await asyncio.to_thread(tc.get_daily_topics)
    except Exception as e:
        logger.error(f"Failed to load topic queue: {e}")
        return {"response_text": f"Failed to load topic queue: {e}"}

    if not queue.topics:
        return {"response_text": "Nothing to study today! All caught up."}

    first_topic = queue.topics[0]
    topic_id = first_topic.topic["id"]

    # Generate first question
    try:
        question_prompt = await asyncio.to_thread(tc.ask_question, topic_id)
    except Exception as e:
        logger.error(f"Failed to generate question for {topic_id}: {e}")
        return {"response_text": f"Failed to generate question: {e}"}

    queue_json = json.dumps([t.to_dict() for t in queue.topics])
    question_json = json.dumps(question_prompt.to_dict())

    await save_study_session(
        user_id=user_id,
        queue_json=queue_json,
        current_index=0,
        phase="question",
        current_item_id=topic_id,
        started_at=time.time(),
        current_question_json=question_json,
    )

    label = "REVIEW" if first_topic.is_due else "NEW"
    score_line = (
        f" (avg {first_topic.card.avg_score:.1f}/5)" if first_topic.card else ""
    )
    return {
        "response_text": (
            f"Starting study session: {queue.summary}\n\n"
            f"[{label}] Topic 1/{queue.total}: *{first_topic.topic['name']}*{score_line}\n\n"
            f"{question_prompt.question_text}"
        )
    }


async def _handle_answer(user_id: str, session: dict, answer: str) -> dict:
    try:
        tc = _get_topic_core()
    except ImportError as e:
        return {"response_text": str(e)}

    topic_id = session["current_item_id"]
    question_json = session.get("current_question_json")

    if not question_json:
        return {"response_text": "Session state lost. Send /study to restart."}

    question = json.loads(question_json)
    question_id = question["question_id"]

    try:
        result = await asyncio.to_thread(tc.submit_answer, topic_id, question_id, answer)
    except Exception as e:
        logger.error(f"Evaluation failed for topic {topic_id}: {e}")
        return {"response_text": f"Evaluation failed: {e}"}

    score_bar = "⭐" * result.score + "☆" * (5 - result.score)
    response = (
        f"Score: {result.score}/5 {score_bar}\n"
        f"Topic avg: {result.topic_avg_score:.1f}/5\n\n"
        f"{result.feedback}"
    )

    if result.score < 4 and result.followup:
        await save_study_session(
            user_id=user_id,
            queue_json=session["queue_json"],
            current_index=session["current_index"],
            phase="followup",
            current_item_id=topic_id,
            started_at=session["started_at"],
            current_question_json=session["current_question_json"],
        )
        response += f"\n\n*Follow-up:*\n{result.followup}"
        return {"response_text": response}
    else:
        advance = await _advance_to_next(user_id, session)
        return {"response_text": response + "\n\n" + advance["response_text"]}


async def _handle_followup_answer(user_id: str, session: dict, answer: str) -> dict:
    advance = await _advance_to_next(user_id, session)
    return {"response_text": "Got it. " + advance["response_text"]}


async def _advance_to_next(user_id: str, session: dict, skipped: bool = False) -> dict:
    try:
        tc = _get_topic_core()
    except ImportError as e:
        return {"response_text": str(e)}

    queue_topics = json.loads(session["queue_json"])
    next_index = session["current_index"] + 1
    total = len(queue_topics)

    if next_index >= total:
        await clear_study_session(user_id)
        return {"response_text": "Session complete! All topics reviewed. Great work!"}

    next_topic_data = queue_topics[next_index]
    topic_id = next_topic_data["topic_id"]
    label = "REVIEW" if next_topic_data["is_due"] else "NEW"
    prefix = "Skipped. " if skipped else ""

    # Generate next question
    try:
        question_prompt = await asyncio.to_thread(tc.ask_question, topic_id)
    except Exception as e:
        logger.error(f"Failed to generate question for {topic_id}: {e}")
        question_text = f"(Question generation failed: {e})"
        question_json = None
    else:
        question_text = question_prompt.question_text
        question_json = json.dumps(question_prompt.to_dict())

    avg_score = next_topic_data.get("avg_score")
    score_line = f" (avg {avg_score:.1f}/5)" if avg_score is not None else ""

    await save_study_session(
        user_id=user_id,
        queue_json=session["queue_json"],
        current_index=next_index,
        phase="question",
        current_item_id=topic_id,
        started_at=session["started_at"],
        current_question_json=question_json,
    )

    return {
        "response_text": (
            f"{prefix}[{label}] Topic {next_index + 1}/{total}: "
            f"*{next_topic_data['topic_name']}*{score_line}\n\n"
            f"{question_text}"
        )
    }


async def _handle_stats() -> dict:
    try:
        tc = _get_topic_core()
    except ImportError as e:
        return {"response_text": str(e)}

    try:
        stats = await asyncio.to_thread(tc.get_topic_stats)
    except Exception as e:
        logger.error(f"Failed to get topic stats: {e}")
        return {"response_text": f"Failed to get stats: {e}"}

    lines = [
        f"*Arch-Gym Topic Progress*\n",
        f"Topics started: {stats['topics_started']}/{stats['topics_total']}",
        f"Total questions answered: {stats['total_questions_answered']}",
        f"Overall avg score: {stats['overall_avg_score']}/5\n",
        "*By Topic:*",
    ]

    for t in stats["topics"]:
        if t["question_count"] == 0:
            status = "⬜ not started"
        elif t.get("avg_score", 0) >= 4.0:
            status = f"✅ {t['avg_score']:.1f}/5"
        elif t.get("avg_score", 0) >= 3.0:
            status = f"🟡 {t['avg_score']:.1f}/5"
        else:
            status = f"🔴 {t['avg_score']:.1f}/5" if t["avg_score"] is not None else "⬜ not started"

        due_marker = " ⏰" if t["is_due"] else ""
        lines.append(
            f"P{t['priority']} {t['topic_name']}: {status} "
            f"({t['question_count']}q){due_marker}"
        )

    return {"response_text": "\n".join(lines)}
