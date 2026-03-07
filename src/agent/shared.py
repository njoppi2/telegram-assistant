import aiosqlite
import json
import logging
from typing import Any, Dict, Set
from pathlib import Path
from aiolimiter import AsyncLimiter
from collections import defaultdict
import asyncio

logger = logging.getLogger(__name__)

# Map user_id -> active subprocess
active_subprocesses: Dict[str, Any] = {}
# Map user_id -> active status message (the "⏳ Processando" message)
active_status_messages: Dict[str, Any] = {}
# Set of user_ids that requested cancellation for the current running task
cancel_requested: Set[str] = set()

# Per-user locks to prevent concurrent actions from the same user
# while still allowing 'MATAR' to bypass the lock
user_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

DB_PATH = Path(__file__).parent.parent.parent / "bot_data.db"


# Rate limiter: 5 actions per minute per user (global for now, can be per-user if needed)
action_limiter = AsyncLimiter(5, 60)

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                user_id TEXT PRIMARY KEY,
                messages_json TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS study_sessions (
                user_id TEXT PRIMARY KEY,
                queue_json TEXT,
                current_index INTEGER DEFAULT 0,
                phase TEXT DEFAULT 'question',
                current_item_id TEXT,
                started_at REAL,
                current_question_json TEXT
            )
        """)
        # Migration: add current_question_json column if it doesn't exist yet
        try:
            await db.execute("ALTER TABLE study_sessions ADD COLUMN current_question_json TEXT")
            await db.commit()
        except Exception:
            pass  # column already exists
        await db.commit()
        logger.info("SQLite database initialized.")

async def get_user_history(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT messages_json FROM history WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return []

async def save_user_history(user_id: str, messages: list):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO history (user_id, messages_json)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET messages_json = excluded.messages_json
        """, (user_id, json.dumps(messages)))
        await db.commit()

async def get_study_session(user_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT queue_json, current_index, phase, current_item_id, started_at, current_question_json FROM study_sessions WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": user_id,
                    "queue_json": row[0],
                    "current_index": row[1],
                    "phase": row[2],
                    "current_item_id": row[3],
                    "started_at": row[4],
                    "current_question_json": row[5],
                }
            return None

async def save_study_session(
    user_id: str,
    queue_json: str,
    current_index: int,
    phase: str,
    current_item_id: str,
    started_at: float,
    current_question_json: str | None = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO study_sessions (user_id, queue_json, current_index, phase, current_item_id, started_at, current_question_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                queue_json = excluded.queue_json,
                current_index = excluded.current_index,
                phase = excluded.phase,
                current_item_id = excluded.current_item_id,
                started_at = excluded.started_at,
                current_question_json = excluded.current_question_json
        """, (user_id, queue_json, current_index, phase, current_item_id, started_at, current_question_json))
        await db.commit()

async def clear_study_session(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM study_sessions WHERE user_id = ?", (user_id,))
        await db.commit()
