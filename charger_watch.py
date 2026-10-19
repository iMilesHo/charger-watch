#!/usr/bin/env python3
"""Watch ChargeLab chargers and send a Telegram alert when a port opens up."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib import error, parse, request


LOG = logging.getLogger("charger-watch")
API_URL = "https://api-v1-green.chargelab.io/core/v1/chargers"
TELEGRAM_URL = "https://api.telegram.org"


def fetch_status(name: str, api_url: str = API_URL) -> bool:
    query = parse.urlencode({"filter_eq[name]": name, "role": "DRIVER"})
    req = request.Request(f"{api_url}?{query}", headers={"Accept": "application/json"})
    with request.urlopen(req, timeout=15) as response:
        payload = json.load(response)

    matches = [item for item in payload.get("entities", []) if item.get("name", "").casefold() == name.casefold()]
    if len(matches) != 1:
        raise ValueError(f"Expected one charger named {name}, got {len(matches)}")

    charger = matches[0]
    if charger.get("maintenanceFlag"):
        return False
    ports = charger.get("ports")
    if not isinstance(ports, list) or not ports:
        raise ValueError(f"No ports returned for {name}")
    return any(port.get("status") == "AVAILABLE" for port in ports)


def send_telegram(name: str, token: str, chat_id: str) -> None:
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise ValueError("Invalid TELEGRAM_BOT_TOKEN")
    message = f"充电桩 {name} 空闲了\nhttps://charge.id/{name.lower()}"
    data = parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    req = request.Request(f"{TELEGRAM_URL}/bot{token}/sendMessage", data=data, method="POST")
    try:
        with request.urlopen(req, timeout=15) as response:
            result = json.load(response)
    except error.HTTPError as exc:
        # HTTPError includes the request URL, which contains the bot token.
        raise RuntimeError(f"Telegram returned HTTP {exc.code}") from None
    if result.get("ok") is not True:
        raise RuntimeError("Telegram did not accept the message")


def read_state(path: Path) -> dict[str, bool]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict) or not all(isinstance(v, bool) for v in data.values()):
        raise ValueError(f"Invalid state file: {path}")
    return data


def write_state(path: Path, state: dict[str, bool]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True) + "\n")
    temporary.replace(path)


def check_once(names: list[str], token: str, chat_id: str, path: Path, *, api_url: str = API_URL) -> None:
    state = read_state(path)
    for name in names:
        try:
            available = fetch_status(name, api_url)
            if available and not state.get(name, False):
                send_telegram(name, token, chat_id)
                LOG.info("%s is available; notification sent", name)
            elif available:
                LOG.info("%s is still available", name)
            else:
                LOG.info("%s is not available", name)
            state[name] = available
            write_state(path, state)
        except (error.URLError, TimeoutError, ValueError, RuntimeError, OSError) as exc:
            LOG.error("Could not check %s: %s", name, exc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="check once, then exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    names = [item.strip().upper() for item in os.getenv("CHARGERS", "").split(",") if item.strip()]
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    interval = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
    path = Path(os.getenv("STATE_FILE", "./state.json"))
    api_url = os.getenv("CHARGELAB_API_URL", API_URL)
    if not names or not token or not chat_id or interval < 60:
        parser.error("Set CHARGERS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and POLL_INTERVAL_SECONDS >= 60")

    while True:
        check_once(names, token, chat_id, path, api_url=api_url)
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
