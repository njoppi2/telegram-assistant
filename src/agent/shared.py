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
            CREATE TABLE IF NOT EXISTS auth (
                user_id TEXT PRIMARY KEY,
                failed_attempts INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                is_authenticated INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                user_id TEXT PRIMARY KEY,
                messages_json TEXT
            )
        """)
        await db.commit()
        logger.info("SQLite database initialized.")

async def get_user_auth(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT failed_attempts, is_blocked, is_authenticated FROM auth WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"failed_attempts": row[0], "is_blocked": row[1], "is_authenticated": row[2]}
            return {"failed_attempts": 0, "is_blocked": 0, "is_authenticated": 0}

async def update_user_auth(user_id: str, failed_attempts: int, is_blocked: int, is_authenticated: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO auth (user_id, failed_attempts, is_blocked, is_authenticated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                failed_attempts = excluded.failed_attempts,
                is_blocked = excluded.is_blocked,
                is_authenticated = excluded.is_authenticated
        """, (user_id, failed_attempts, is_blocked, is_authenticated))
        await db.commit()

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
