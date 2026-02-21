# Telegram Assistant — Architecture & Tech Stack

## Overview

A Telegram-based personal assistant that serves multiple people (mom, sister, etc.) from one WhatsApp number. Each person gets different behavior/persona + different tools. Implemented as one bot with a routing layer.

## WhatsApp Number Setup

### How multi-user routing works

One WhatsApp Business number. Everyone texts the same number. The bot identifies who's talking by their phone number and routes to different personas/tools:

```
Mom texts the bot number   →  webhook receives from +5548991885506   →  router loads "mae_lucia" profile
Sister texts same number   →  webhook receives from +55489XXXXXXXX   →  router loads "irma" profile
Unknown number             →  router loads "default" profile (or rejects)
```

There's no separate LLM instance per person — it's one server, one webhook, one codebase. The router swaps the system prompt + allowed tools before calling the LLM.

### Getting a number

**Option 1: Free test number (for development)**
- When you create a WhatsApp app on Meta, you get a test phone number automatically
- No cost, no real number needed
- Can send messages to up to 5 verified phone numbers (mom, sister, yourself)
- 1,000 free service conversations per month

**Option 2: Register a real number (for production)**
- Buy a cheap SIM card or use a VoIP number
- The number must NOT be linked to any existing WhatsApp account (personal or business)
- Verify via SMS or phone call OTP
- Once registered, that number becomes the bot's number

### Setup steps

1. Go to developers.facebook.com → create an app (type: "Business")
2. Add the "WhatsApp" product to your app
3. You immediately get a test number + API access
4. Set up your webhook URL (your FastAPI server, exposed via ngrok for local dev)
5. Subscribe to message events (`messages`, `message_status`)
6. Start receiving messages — the whole setup takes ~30 minutes

### Local development with ngrok

Since WhatsApp needs a public HTTPS URL for webhooks, use ngrok during development:

```bash
# Terminal 1: run your FastAPI app
uvicorn src.main:app --reload --port 8000

# Terminal 2: expose it publicly
ngrok http 8000
```

Then set the ngrok URL (e.g. `https://abc123.ngrok-free.app/webhook`) as your webhook URL in the Meta developer dashboard.

### Pricing (as of 2026)

- 1,000 free service conversations/month (user-initiated)
- Click-to-WhatsApp Ad conversations: 72-hour free window
- Beyond free tier: pay per conversation (varies by country, ~$0.05-0.08 for Brazil)
- The Cloud API itself is free — you only pay for conversations

## High-Level Flow

```
WhatsApp Cloud API → Webhook (FastAPI) → Router → Agent Runtime → Tools → Storage/Queue
```

## Requirements

- **Channel:** WhatsApp (official WhatsApp Business / Cloud API; webhook-based)
- **Users:** initially 2–5 people, scalable to more
- **Multi-persona:** different instructions/persona, different allowed tools, separate memory/state per user
- **Code-first:** full GitHub version control (PRs, diffs, commits), no visual workflow tools
- **Environments:** staging + production

## Tech Stack

| Component | Choice | Rationale |
|---|---|---|
| **Language** | Python | Best LLM ecosystem, fast AI-assisted dev |
| **Web framework** | FastAPI | Async, lightweight, auto OpenAPI docs, resume-worthy |
| **Database** | PostgreSQL (Supabase) | Industry standard, free tier, managed |
| **Task queue** | Redis + ARQ | Async-native (matches FastAPI), lightweight, Redis as broker |
| **Agent framework** | LangGraph | Code-first graph DSL, built-in visualization, LangGraph Studio IDE, resume-worthy |
| **LLM provider** | OpenAI Responses API or Claude API | Both have mature tool calling; start with one, easy to swap |
| **Deployment** | Docker + docker-compose | Environment parity, reproducible, scales horizontally |
| **CI/CD** | GitHub Actions | Automated tests + lint on PRs, deploy on merge to main |
| **Config** | Pydantic Settings | Type-safe, validated config per environment |
| **Logging** | structlog | Structured JSON logs, searchable, production-grade |
| **LLM observability** | Langfuse (self-hosted) | Open source, visual traces of every LLM call + tool call, cost tracking |
| **DB migrations** | Alembic | Industry standard for SQLAlchemy |
| **Media storage** | Supabase Storage or S3 | Need to persist WhatsApp media (temp URLs expire) |

**Resume line:** Python, FastAPI, PostgreSQL, Redis, LangGraph, Docker, GitHub Actions, Langfuse, WhatsApp Cloud API, OpenAI/Claude API, Instagram Graph API

## Framework Decision

| Framework | Decision | Reason |
|---|---|---|
| **LangGraph** | **Use it** | Graph-based agent definition gives you visualization of all possible routes for free. LangGraph Studio = visual IDE with live execution. Each node is still a plain Python function. |
| **LangChain** | Skip | Heavy abstraction layer, not needed here. LangGraph is the standalone piece we want. |
| **OpenAI Agents SDK** | Skip for now | LangGraph covers the same ground and gives visualization on top. |

### Why LangGraph specifically

LangGraph lets you define your agent as a graph (nodes + edges) in ~15 lines, then gives you:

- **Static graph view**: `graph.get_graph().draw_png()` — renders a diagram of all possible routes at once
- **LangGraph Studio**: desktop IDE, see all routes + watch live execution + time-travel debug (go back to any step, fork, resume)
- **Langfuse agent graphs**: in production, every trace renders as a visual flow diagram

Each node is a plain Python function — no magic, clean Git diffs, fully testable:

```python
from langgraph.graph import StateGraph

graph = StateGraph(AgentState)

# nodes — each is a plain Python function
graph.add_node("router", route_by_phone)
graph.add_node("llm_call", call_agent)
graph.add_node("execute_tools", run_tools)
graph.add_node("send_response", send_whatsapp)

# edges — define all possible routes
graph.add_edge("router", "llm_call")
graph.add_conditional_edges("llm_call", has_tool_calls, {
    True: "execute_tools",
    False: "send_response"
})
graph.add_edge("execute_tools", "llm_call")  # loop back until done
graph.set_entry_point("router")

app = graph.compile()
```

This graph auto-renders as a diagram showing all branches — exactly the n8n-style "all possible routes" view, but from code.

## Components

### 1. WhatsApp Webhook Receiver
- Receives inbound messages and media events
- GET endpoint for webhook verification (challenge token)
- POST endpoint for incoming messages
- Message deduplication via `wa_message_id`

### 2. Router
- Looks up sender phone number → loads a `UserProfile`
- Profile defines: persona/instructions, tool permissions, linked accounts, memory namespace

### 3. Agent Runtime (LangGraph)
- Defined as a graph: `router → llm_call → [execute_tools → llm_call]* → send_response`
- Each node is a plain Python function; LangGraph manages state between them
- The `llm_call → execute_tools` loop repeats until the LLM stops calling tools
- LangGraph Studio lets you watch this loop live, pause at any node, inspect state

### 4. Tool Layer
- `draft_instagram_caption(media, style)` — propose caption for a post
- `publish_instagram(media_url, caption, account)` — publish to IG (or draft + approval)
- `update_website(entry)` — update portfolio/website
- `create_reminder(datetime, message, template_id?)` — schedule a reminder
- `save_note()` / `get_user_context()` — persistent per-user memory

### 5. State & Storage
- Users/profiles, conversations/messages, memories, reminders (see data model below)
- Media storage for uploaded images/videos

### 6. Reminders Worker (ARQ)
- Polls due reminders from DB
- If inside WhatsApp 24h window → send normal text
- If outside 24h window → use pre-approved template message

### 7. Observability (how you see what's going on)

Two layers of visibility:

**Layer 1 — LangGraph Studio (dev/staging): "watch the agent run live"**

Desktop IDE for your LangGraph agent. Shows all possible routes as a static graph, then highlights which path was taken in real time:

```
All routes (static diagram):                Live execution view:

  [router] ──→ [llm_call]                    [router] ──→ [llm_call] ← currently here
                    │                                           │
          ┌─────────┴──────────┐                     ┌────────┴────────┐
     has_tool_calls?        no tools             ✅ tool calls
          │                    │
    [execute_tools]    [send_response]
          │
          └──────→ [llm_call] (loop)
```

Features: pause at any node, inspect state, edit state and fork, time-travel to any previous step.

**Layer 2 — Langfuse (production): "what happened for each message?"**

Self-hosted, open source. LangGraph integration is native — every trace renders as an agent graph automatically. Shows every node, every LLM call, every tool call, cost, latency:

```
Trace: Mom sent "posta essa foto no insta com uma legenda bonita"
│
├─ [router] → profile: mae_lucia (2ms)
├─ [llm_call #1] → decided to call tool (1.2s, $0.002)
│   ├─ Tool: draft_instagram_caption({style: "poetic", media: "sunset.jpg"})
│   └─ Result: "Pôr do sol que só Floripa tem..."
├─ [llm_call #2] → decided to call tool (0.9s, $0.001)
│   ├─ Tool: publish_instagram({caption: "...", draft: true})
│   └─ Result: {status: "draft_created"}
├─ [llm_call #3] → final answer (0.6s, $0.001)
└─ [send_response] → WhatsApp sent (48ms)
     Total: 2.7s, $0.004
```

Runs as a Docker container alongside the app. LangGraph integration requires zero extra code — just set `LANGFUSE_*` env vars.

**Layer 2 — Admin Dashboard (business view): "what did the bot do today?"**

A simple read-only web UI built into the FastAPI app, reading from the existing DB tables:

```
/admin
├── /admin/conversations     — recent conversations per user
├── /admin/conversations/:id — full message thread with tool calls inline
├── /admin/actions           — log of all tool executions (IG posts, reminders created, etc.)
└── /admin/reminders         — upcoming + past reminders with status
```

No extra infrastructure needed — just queries over the `messages` and `reminders` tables.

**How the three layers fit together:**

```
                              You (developer)
               ┌──────────────────┼──────────────────┐
               │                  │                  │
     LangGraph Studio         Langfuse UI       Admin Dashboard
     (dev: live debug,    (prod: per-trace    (business: posts,
      all routes visual)   agent graph)        reminders, audit)
               │                  │                  │
               └──────────────────┼──────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
        WhatsApp msg in    LangGraph agent       Tool execution
        (mom sends photo)  (nodes + edges)   (posts to Instagram)
```

- **LangGraph Studio** = see all possible routes, debug live (dev/staging only)
- **Langfuse** = production traces with agent graph per message, cost tracking
- **Admin dashboard** = business view: what was posted, what's scheduled, what failed

## Repo Structure

```
whatsapp-assistant/
├── .github/
│   └── workflows/
│       ├── ci.yml              # lint + test on every PR
│       └── deploy.yml          # deploy to staging on merge to main
│
├── docker-compose.yml          # local dev: app + postgres + redis
├── docker-compose.staging.yml  # staging overrides
├── Dockerfile
│
├── .env.example
├── .env.staging.example
├── .env.production.example
│
├── pyproject.toml
├── alembic/                    # DB migrations
│   ├── env.py
│   └── versions/
│
├── src/
│   ├── __init__.py
│   ├── config.py               # Pydantic Settings (validates env vars)
│   ├── logging.py              # structlog setup
│   ├── main.py                 # FastAPI app entry
│   │
│   ├── whatsapp/
│   │   ├── webhook.py          # POST /webhook (verify + receive)
│   │   ├── sender.py           # send_text(), send_template(), send_media()
│   │   └── media.py            # download/upload media from WhatsApp
│   │
│   ├── router/
│   │   ├── profiles.py         # UserProfile model + loader
│   │   └── router.py           # phone_number → profile resolution
│   │
│   ├── agent/
│   │   ├── graph.py            # LangGraph graph definition (nodes + edges)
│   │   ├── nodes.py            # node functions: router, llm_call, execute_tools, send_response
│   │   ├── state.py            # AgentState TypedDict (data passed between nodes)
│   │   ├── context.py          # build conversation context from DB
│   │   └── prompts.py          # per-persona system prompts (or load from DB)
│   │
│   ├── tools/
│   │   ├── __init__.py         # tool registry (list of available tools per profile)
│   │   ├── instagram.py        # draft_caption, publish_post
│   │   ├── website.py          # update_portfolio
│   │   ├── reminders.py        # create_reminder, list_reminders
│   │   └── notes.py            # save_note, get_context
│   │
│   ├── storage/
│   │   ├── db.py               # async SQLAlchemy / Supabase client
│   │   ├── models.py           # ORM models
│   │   └── media_store.py      # S3/Supabase Storage wrapper
│   │
│   ├── admin/
│   │   ├── router.py           # /admin routes (conversations, actions, reminders)
│   │   └── templates/          # Jinja2 HTML templates for admin UI
│   │
│   └── workers/
│       ├── reminders.py        # ARQ worker: check due reminders
│       └── media_processor.py  # ARQ worker: download + store WA media
│
├── profiles/                   # YAML per-user configs (version controlled!)
│   ├── mae_lucia.yaml
│   └── irma.yaml
│
├── scripts/
│   ├── seed_profiles.py        # load YAML profiles into DB
│   └── create_wa_templates.py  # submit WA templates to Meta
│
└── tests/
    ├── conftest.py
    ├── test_router.py
    ├── test_agent.py
    └── test_tools/
        ├── test_instagram.py
        └── test_reminders.py
```

## Data Model

```sql
-- Who can use the bot
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone TEXT UNIQUE NOT NULL,        -- E.164 format: +5548991885506
    profile_slug TEXT NOT NULL,         -- maps to profiles/mae_lucia.yaml
    display_name TEXT,
    ig_account_id TEXT,                 -- linked Instagram Business account
    ig_access_token TEXT,               -- encrypted
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Conversation history (for context + audit)
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    role TEXT NOT NULL,                 -- 'user' | 'assistant' | 'tool_call' | 'tool_result'
    content TEXT,
    media_url TEXT,                     -- if message had image/video
    tool_name TEXT,                     -- if role is tool_call/tool_result
    tool_input JSONB,
    tool_output JSONB,
    wa_message_id TEXT,                 -- WhatsApp message ID for dedup
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Per-user persistent memory (key-value or structured)
CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    key TEXT NOT NULL,                  -- e.g. 'art_preferences', 'last_topic'
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, key)
);

-- Scheduled reminders
CREATE TABLE reminders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    message TEXT NOT NULL,
    due_at TIMESTAMPTZ NOT NULL,
    template_name TEXT,                 -- WA template to use if outside 24h window
    status TEXT DEFAULT 'pending',      -- 'pending' | 'sent' | 'failed' | 'cancelled'
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_reminders_due ON reminders(due_at) WHERE status = 'pending';
```

## Profile YAML Example

```yaml
# profiles/mae_lucia.yaml
slug: mae_lucia
display_name: Lúcia
phone: "+5548991885506"

persona: |
  Você é uma assistente criativa e de negócios da Lúcia, uma artista plástica
  de Florianópolis. Ajude com ideias de pintura, legendas para Instagram,
  estratégia de conteúdo e organização do trabalho. Seja direta e prática.
  Fale em português brasileiro.

tools:
  - draft_instagram_caption
  - publish_instagram
  - update_website
  - create_reminder
  - save_note

instagram:
  account_id: "${IG_LUCIA_ACCOUNT_ID}"

context_window: 20  # last N messages to include in LLM context
```

## Environment Strategy

```
main branch    ──push──→  staging (auto-deploy)
                              │
                          manual promote (or merge to prod branch)
                              │
                              ▼
                          production
```

- **Local**: `docker-compose up` — runs app + Postgres + Redis
- **Staging**: deployed on Railway/Fly.io, connected to a test WhatsApp number
- **Production**: same infra, different env vars, real WhatsApp number

## WhatsApp Gotchas

### 24-Hour Window + Reminders
- **Inside 24h of last user message:** can send any text freely
- **Outside 24h:** can ONLY send pre-approved template messages
- Templates must be submitted to Meta for review (~24h approval)
- Template categories: Utility (reminders, updates) and Marketing — Utility is cheaper and more likely approved

```python
async def send_reminder(reminder):
    last_msg = await get_last_user_message(reminder.user_id)
    within_window = (now() - last_msg.created_at) < timedelta(hours=24)

    if within_window:
        await send_text(reminder.user_id, reminder.message)
    else:
        await send_template(
            reminder.user_id,
            template_name="reminder_notification",
            parameters=[reminder.message]
        )
```

**Templates to pre-create:**
1. `reminder_notification` — "Oi {{1}}! Lembrete: {{2}}" (Utility)
2. `instagram_post_ready` — "{{1}}, seu post do Instagram está pronto para revisar!" (Utility)

### Webhook Verification
WhatsApp requires a GET endpoint for verification (challenge token). Must handle both GET (verify) and POST (receive).

### Message Deduplication
WhatsApp sometimes sends duplicate webhook events. Store `wa_message_id` and skip duplicates.

### Media Handling
When a user sends a photo, you get a `media_id`, not the file. Must:
1. Call `GET /v21.0/{media_id}` to get a temporary download URL
2. Download the file (URL expires quickly)
3. Store in S3/Supabase Storage

## What NOT to Add Yet

- **Kubernetes** — Docker + single host is fine for hundreds of users
- **Terraform** — manual infra setup is fine for 1-2 environments
- **Microservices** — keep monolithic, one repo, one deployable unit
- **Message broker (Kafka/RabbitMQ)** — Redis handles queue needs
- **LangChain** — LangGraph is the standalone piece we want; LangChain adds abstraction overhead on top

Scalability path: vertical first (bigger instance), then horizontal (multiple workers behind load balancer). Docker makes the horizontal step trivial.

## MVP Build Order

1. Implement WhatsApp webhook receiver + send-message endpoint
2. Implement router + `UserProfile` mapping for mom/sister
3. Define LangGraph graph (`graph.py`) with nodes: router → llm_call → execute_tools → send_response
4. Implement 2–3 tools: `draft_caption`, `save_note`, `create_reminder`
5. Open LangGraph Studio — confirm the graph visualization looks right, run first test messages
6. Add Instagram publish tool (start as "draft + approval required")
7. Add reminders worker + WhatsApp template logic for out-of-window sends
8. Add Langfuse — connect LangGraph integration, verify agent graphs appear in production traces
