Telegram bot serving multiple users from one bot token, routes each user to a different persona+tools via LangGraph based on their Telegram user_id.

## Core pattern
Each user maps to a YAML file in `profiles/`. Profile defines `telegram_user_id`, `persona` (system prompt), `capabilities`, and `tools` list. Router in `src/router/` loads profile by `user_id`. The bot is private: users without a profile are rejected. LangGraph graph in `src/agent/graph.py` passes `AgentState` through nodes for profile loading, capability-aware routing, and the final handler.

## Credentials
Secrets live in `.env` (project root).

Keys used by the current runtime:
- `TELEGRAM_BOT_TOKEN`
- `GOOGLE_API_KEY`
- `ARCH_GYM_PATH` (optional; enables local arch-gym integration)

There is no active WhatsApp/Meta integration in the current bot runtime.

## Runtime
Use Python 3.11+ if available. The repo now uses the supported `google-genai` SDK for Gemini calls.

## Adding a user
Copy any profile YAML, set `telegram_user_id` to their numeric Telegram ID (get it by having them message `@userinfobot`), set `persona`, and define `capabilities`.

Current capability model:
- `study`: can use `/study`, `/skip`, `/stop`, `/stats`, `/archstats`, and resume study sessions
- `run`: can use `/run`

## Run
`PYTHONPATH=. python3 src/main.py`
