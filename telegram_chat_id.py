#!/usr/bin/env python3
"""Print chat IDs from recent messages sent to a Telegram bot."""

import getpass
import json
from urllib import error, request


def main() -> None:
    token = getpass.getpass("Bot token: ").strip()
    req = request.Request(f"https://api.telegram.org/bot{token}/getUpdates")
    try:
        with request.urlopen(req, timeout=15) as response:
            updates = json.load(response)
    except error.HTTPError as exc:
        raise SystemExit(f"Telegram returned HTTP {exc.code}") from None
    if not updates.get("ok"):
        raise SystemExit("Telegram rejected the request")
    chats = {
        (message["chat"]["id"], message["chat"].get("title") or message["chat"].get("first_name", ""))
        for update in updates["result"]
        for message in [update.get("message")]
        if message and "chat" in message
    }
    if not chats:
        raise SystemExit("No chats found. Send /start to the bot and try again.")
    for chat_id, name in sorted(chats):
        print(f"{chat_id}  {name}")


if __name__ == "__main__":
    main()
