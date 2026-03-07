import asyncio
import logging
import re
import json
from pathlib import Path

import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.router.router import get_profile
import src.agent.shared as shared

logger = logging.getLogger(__name__)

GEMINI_BIN = "/home/njoppi2/.nvm/versions/node/v24.11.1/bin/gemini"
GEMINI_NODE_BIN = str(Path(GEMINI_BIN).with_name("node"))
GEMINI_TIMEOUT_SECONDS = 120

OPENCODE_BIN = str(Path.home() / ".opencode/bin/opencode")
OPENCODE_MODEL = "opencode/minimax-m2.5-free"
OPENCODE_TIMEOUT_SECONDS = 300 

if settings.GOOGLE_API_KEY:
    genai.configure(api_key=settings.GOOGLE_API_KEY)
    logger.info("Gemini API configured")

def strip_ansi(text: str) -> str:
    # Comprehensive ANSI/VT100 escape sequence regex
    ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)

def parse_json_stream(text: str):
    """Parses a string that might contain multiple JSON objects or a JSON array."""
    results = []
    text = strip_ansi(text)
    
    # 1. Try as a single JSON array
    try:
        start_idx = text.find('[')
        end_idx = text.rfind(']')
        if start_idx != -1 and end_idx != -1:
            snippet = text[start_idx:end_idx+1]
            try:
                return json.loads(snippet), "array"
            except json.JSONDecodeError:
                pass
    except Exception:
        pass

    # 2. Incremental decoding using raw_decode
    decoder = json.JSONDecoder()
    pos = 0
    max_iter = 1000
    iters = 0
    while pos < len(text) and iters < max_iter:
        iters += 1
        try:
            match = re.search(r'[\[\{]', text[pos:])
            if not match: break
            pos += match.start()
            
            obj, next_pos = decoder.raw_decode(text[pos:])
            if isinstance(obj, list):
                results.extend(obj)
            elif isinstance(obj, dict):
                results.append(obj)
            pos += next_pos
        except (json.JSONDecodeError, ValueError, IndexError):
            pos += 1
            
    if results:
        unique = []
        seen_part_ids = set()
        for res in results:
            if not isinstance(res, dict): 
                unique.append(res)
                continue
            p_id = res.get('part', {}).get('id')
            if p_id:
                if p_id not in seen_part_ids:
                    unique.append(res)
                    seen_part_ids.add(p_id)
            else:
                unique.append(res)
        return unique, "robust_decoder"
            
    return [], "failed"

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def generate_content_with_retry(model, prompt):
    return await asyncio.to_thread(model.generate_content, prompt)

SYSTEM_CAPABILITIES = """
You have access to the following system capabilities and scripts:

## Smart Home
- callSmartBulb: Control smart bulbs (turn on/off, change colors)
- smartBulb: Smart bulb management

## Screenshots & Images
- takeScreenshotAndSave: Take a screenshot and save it
- createImageGrids: Create image grids from screenshots
- currentPrintDirectory: Get current print directory
- deleteFiles: Delete files
- fillMissedPrints: Fill missed prints
- insertPromptsIntoGrid: Insert prompts into image grids
- partialPrompt: Generate partial prompts
- promptIfNeeded: Prompt user if needed
- promptUser: Interactive user prompting
- commitDailyPrints: Commit daily prints

## System Control
- makeComputerUnusable: Lock down computer (disable wifi, minimize windows)
- makeComputerUsable: Restore computer to normal state
- shutdown: Shutdown the computer
- duck: Update DuckDNS IP address

## Projects Available
- lucia-art: Lucia's art project (AI image generation)
- lucia-anita-artes.github.io: Lucia's website
- telegram-assistant: This bot
- my-scripts: System scripts repository
- playwright-mcp-humanized: Browser automation

## AI Agents Available
- ai-claude: Claude CLI agent
- ai-codex: Codex CLI agent
- ai-gemini: Gemini CLI agent
- ai-phone: Phone workflow assistant

You can execute commands, read files, write code, browse the web, and control the system.

IMPORTANT INSTRUCTION FOR ALL RESPONSES:
Your response will be sent directly to the user via Telegram.
- Format for Telegram Markdown.
- Use *text* for bold (single asterisk), NOT **text**.
- Use _text_ for italic.
- Use `inline code` or ```code blocks``` for code.
- NEVER use standard markdown like **bold**, __underline__, or HTML tags.
- Use standard unicode bullets (•) for lists instead of hyphens or asterisks.
"""


def get_gemini_model():
    if not settings.GOOGLE_API_KEY:
        return None
    return genai.GenerativeModel("gemini-3-flash-preview")


def format_history(messages: list[dict[str, str]]) -> str:
    if not messages:
        return "No history."
    
    formatted = []
    # Count assistant messages to keep only the last 3 full ones
    assistant_msgs = [i for i, m in enumerate(messages) if m["role"] == "assistant"]
    keep_from_idx = assistant_msgs[-3] if len(assistant_msgs) > 3 else -1

    for i, m in enumerate(messages):
        role = m["role"].capitalize()
        content = m["content"]
        
        if m["role"] == "assistant" and i < keep_from_idx:
            if len(content) > 100:
                content = f"[Resposta anterior do Lucas oculta para brevidade: {content[:50]}...]"
        
        formatted.append(f"{role}: {content}")
        
    return "\n".join(formatted)


async def load_profile_node(state) -> dict:
    profile = get_profile(state["user_id"])
    if not profile:
        logger.warning(f"No profile found for user {state['user_id']}")
        return {"profile_slug": "", "profile_persona": "", "profile_capabilities": []}
    logger.info(f"Loaded profile '{profile['slug']}' for user {state['user_id']}")
    return {
        "profile_slug": profile["slug"],
        "profile_persona": profile["persona"],
        "profile_capabilities": profile.get("capabilities", []),
    }


async def direct_response_node(state) -> dict:
    return {"response_text": state.get("response_text", "")}


async def handle_query_node(state) -> dict:
    user_message = state["incoming_text"]
    history = state.get("messages", [])
    persona = state.get("profile_persona", "")
    model = get_gemini_model()
    
    if not model:
        return {"response_text": "Gemini API key not configured. Cannot process simple queries."}
    
    try:
        telegram_instruction = (
            "IMPORTANT: Your response will be sent directly to Telegram. "
            "Format for Telegram Markdown: "
            "Use *text* for bold (single asterisk), NOT **text**. "
            "Use _text_ for italic. "
            "Use `inline code` or ```code blocks``` for code. "
            "NEVER use standard markdown like **bold**, __underline__, or HTML tags. "
            "Use standard unicode bullets (•) for lists instead of hyphens or asterisks."
        )
        
        history_text = format_history(history)
        
        full_prompt = (
            f"{persona}\n\n"
            f"{telegram_instruction}\n\n"
            f"Conversation History:\n{history_text}\n\n"
            f"User message: {user_message}"
        )
        
        response = await generate_content_with_retry(model, full_prompt)
        logger.info(f"Query handled successfully via Gemini API")
        return {"response_text": response.text, "messages": [{"role": "user", "content": user_message}, {"role": "assistant", "content": response.text}]}
    except Exception as e:
        logger.error(f"Query handling failed: {e}")
        return {"response_text": f"Error calling Gemini API: {str(e)}"}


async def handle_action_node(state) -> dict:
    persona = state.get("profile_persona", "")
    user_id = state.get("user_id", "default")
    user_message = state["incoming_text"]
    history = state.get("messages", [])
    history_text = format_history(history)

    system_instruction = (
        "You are running in a HEADLESS AUTOMATED MODE. "
        "You have FULL PERMISSION to read any directory or file requested. "
        "Access directories using absolute paths. "
        "Your task is to provide the substantive answer requested by the user. "
        "DO NOT output your internal process or thoughts as messages for the user. "
        "Only output the final result."
    )

    full_prompt = (
        f"{persona}\n\n"
        f"{system_instruction}\n\n"
        f"{SYSTEM_CAPABILITIES}\n\n"
        f"Conversation History:\n{history_text}\n\n"
        f"User message: {user_message}"
    )
    
    logger.info(f"Executing action for user {user_id} via OpenCode: {user_message[:50]}...")

    shared.active_subprocesses[user_id] = None 
    
    if user_id in shared.cancel_requested:
        shared.active_subprocesses.pop(user_id, None)
        logger.info(f"Action for user {user_id} cancelled before starting.")
        return {"response_text": "Ação cancelada pelo usuário."}

    proc = await asyncio.create_subprocess_exec(
        OPENCODE_BIN,
        "run",
        "--model", OPENCODE_MODEL,
        "--thinking",
        "--format", "json",
        full_prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
    )
    
    shared.active_subprocesses[user_id] = proc

    # --- Streaming read with live status updates ---
    stdout_chunks: list[bytes] = []
    thinking_log: list[str] = []
    user_answer_parts: list[str] = []
    last_edit_time: float = 0.0
    EDIT_INTERVAL = 1.5  # seconds between Telegram message edits

    async def _try_edit_status(text: str):
        nonlocal last_edit_time
        now = asyncio.get_event_loop().time()
        if now - last_edit_time < EDIT_INTERVAL:
            return
        status_msg = shared.active_status_messages.get(user_id)
        if not status_msg:
            return
        try:
            await status_msg.edit_text(text)
            last_edit_time = now
        except Exception:
            pass  # rate limit or already deleted — ignore

    partial_buf = ""

    async def _read_stdout():
        nonlocal partial_buf
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            if user_id in shared.cancel_requested:
                break
            stdout_chunks.append(chunk)
            partial_buf += chunk.decode(errors="replace")

            # Try to parse any complete JSON objects from the buffer
            events, _ = parse_json_stream(partial_buf)
            for event in events:
                if not isinstance(event, dict):
                    continue
                e_type = event.get("type")
                part = event.get("part", {})
                p_text = part.get("text", "").strip()

                if e_type == "reasoning" and p_text:
                    snippet = p_text[:200] + ("…" if len(p_text) > 200 else "")
                    await _try_edit_status(f"🧠 _Thinking…_\n\n{snippet}")
                    thinking_log.append(f"[Reasoning] {p_text}")

                elif e_type == "tool_use":
                    tool = part.get("tool", "unknown")
                    state_data = part.get("state", {})
                    t_input = state_data.get("input")
                    t_output = state_data.get("output")
                    await _try_edit_status(f"🔧 _Running tool:_ `{tool}`")
                    thinking_log.append(f"[Tool: {tool}] Input: {t_input}")
                    if isinstance(t_output, str) and len(t_output) > 500:
                        thinking_log.append(f"[Tool Result] (Long output, {len(t_output)} chars)")
                    else:
                        thinking_log.append(f"[Tool Result] {t_output}")

                elif e_type == "text" and p_text:
                    if p_text not in user_answer_parts:
                        user_answer_parts.append(p_text)

    try:
        await asyncio.wait_for(_read_stdout(), timeout=OPENCODE_TIMEOUT_SECONDS)
        await asyncio.wait_for(proc.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

        logger.error(f"OpenCode timed out after {OPENCODE_TIMEOUT_SECONDS}s")
        shared.active_subprocesses.pop(user_id, None)
        return {"response_text": "Erro: A operação demorou demais e foi interrompida."}

    shared.active_subprocesses.pop(user_id, None)

    if user_id in shared.cancel_requested:
        logger.info(f"Action for user {user_id} finished but suppressed.")
        return {"response_text": "Ação interrompida. O resultado foi descartado."}

    # If streaming parse caught nothing, fall back to batch parse of full output
    raw_output = b"".join(stdout_chunks).decode(errors="replace").strip()
    if not user_answer_parts and not thinking_log:
        events, method = parse_json_stream(raw_output)
        if events:
            for event in events:
                if not isinstance(event, dict):
                    continue
                e_type = event.get("type")
                part = event.get("part", {})
                p_text = part.get("text", "").strip()
                if e_type == "reasoning" and p_text:
                    thinking_log.append(f"[Reasoning] {p_text}")
                elif e_type == "text" and p_text:
                    user_answer_parts.append(p_text)
                elif e_type == "tool_use":
                    tool = part.get("tool", "unknown")
                    thinking_log.append(f"[Tool: {tool}]")
        else:
            logger.warning(f"Structured parsing failed for {user_id}. Fallback activated.")
            clean_text = strip_ansi(raw_output)
            substantive_lines = []
            for line in clean_text.split('\n'):
                l = line.strip()
                if l.startswith('{') or l.startswith('[') or l.endswith('}') or l.endswith(']'): continue
                if '"type":' in l or '"part":' in l or '"timestamp":' in l: continue
                if any(l.lower().startswith(x) for x in ['thinking:', 'thought:', '✱', '→', '> build']): continue
                if l: substantive_lines.append(line)
            user_answer_parts = ["\n".join(substantive_lines).strip()]

    if thinking_log:
        logger.info(f"OpenCode stream for {user_id}:\n" + "\n".join(thinking_log))

    response_text = "\n\n".join(user_answer_parts).strip()
    if not response_text:
        if thinking_log:
            response_text = "Ação concluída no terminal (nenhum resumo final gerado pelo modelo)."
        else:
            response_text = "Ação concluída, mas o modelo não forneceu uma resposta clara."

    if user_id in shared.cancel_requested:
        return {"response_text": "Ação interrompida. O resultado foi descartado."}

    logger.info(f"Action completed for {user_id}. Answer length: {len(response_text)}")
    return {
        "response_text": response_text,
        "messages": [{"role": "user", "content": user_message}, {"role": "assistant", "content": response_text}]
    }
