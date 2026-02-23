Telegram bot serving multiple users from one bot token, routes each user to a different persona+tools via LangGraph based on their Telegram user_id.

## Core pattern
Each user maps to a YAML file in `profiles/`. Profile defines `telegram_user_id`, `persona` (system prompt), and `tools` list. Router in `src/router/` loads profile by `user_id`. LangGraph graph in `src/agent/graph.py` passes `AgentState` through nodes: `load_profile` → `call_llm` (→ more nodes as tools are added).

## Credentials
Secrets live in `.env` (project root). Keys used by the current code: `TELEGRAM_BOT_TOKEN`, `GOOGLE_API_KEY`, `AUTH_PASSWORD` (optional).

## Adding a user
Copy any profile YAML, set `telegram_user_id` to their numeric Telegram ID (get it by having them message `@userinfobot`), set `persona`.

## Run
`PYTHONPATH=. python3 src/main.py`
