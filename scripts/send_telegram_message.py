#!/usr/bin/env python3
import argparse
import json
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.config import settings  # noqa: E402
from src.router.profiles import load_profiles  # noqa: E402


def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.lower().strip().split())


def _iter_named_profiles():
    for user_id, profile in load_profiles().items():
        display_name = str(profile.get("display_name", "")).strip()
        slug = str(profile.get("slug", "")).strip()
        yield {
            "user_id": user_id,
            "display_name": display_name,
            "slug": slug,
            "profile": profile,
        }


def resolve_target(target: str):
    target_n = _norm(target)
    exact = []
    fuzzy = []
    for item in _iter_named_profiles():
        names = [
            item["user_id"],
            item["slug"],
            item["display_name"],
        ]
        names_n = [_norm(x) for x in names if x]
        if target_n in names_n:
            exact.append(item)
            continue
        if any(target_n and target_n in x for x in names_n):
            fuzzy.append(item)

    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(
            "Target matches multiple profiles exactly: "
            + ", ".join(f"{x['display_name']} ({x['user_id']})" for x in exact)
        )
    if len(fuzzy) == 1:
        return fuzzy[0]
    if len(fuzzy) > 1:
        raise ValueError(
            "Target is ambiguous. Matches: "
            + ", ".join(f"{x['display_name']} ({x['user_id']})" for x in fuzzy)
        )
    raise ValueError(f"No profile found for target: {target}")


def send_message(chat_id: str, text: str) -> dict:
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body)


def main():
    parser = argparse.ArgumentParser(
        description="Send a Telegram message to a known profile by name, slug, or user_id."
    )
    parser.add_argument("--list", action="store_true", help="List named profiles and exit")
    parser.add_argument("--to", help="Target profile display name, slug, or Telegram user_id")
    parser.add_argument("message", nargs="?", help="Message text to send")
    args = parser.parse_args()

    if args.list:
        for item in sorted(_iter_named_profiles(), key=lambda x: x["display_name"].lower()):
            print(f"{item['display_name']}\t{item['slug']}\t{item['user_id']}")
        return

    if not args.to or not args.message:
        parser.error("Use --to <name|slug|user_id> and provide a message, or use --list")

    target = resolve_target(args.to)
    result = send_message(target["user_id"], args.message)

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")

    msg_id = result.get("result", {}).get("message_id")
    print(
        f"Sent to {target['display_name']} ({target['user_id']})"
        + (f" message_id={msg_id}" if msg_id is not None else "")
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTPError {e.code}: {body}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
