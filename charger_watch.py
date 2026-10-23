#!/usr/bin/env python3
"""Watch ChargeLab chargers and send a WeChat alert when a port opens up."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path
from urllib import error, parse, request


LOG = logging.getLogger("charger-watch")
API_URL = "https://api-v1-green.chargelab.io/core/v1/chargers"
SERVERCHAN_URL = "https://sctapi.ftqq.com"
TIMEOUT_SECONDS = 15
USER_AGENT = "charger-watch (+https://github.com/iMilesHo/charger-watch)"

# Errors expected from network problems or a changed/odd API response.
CHECK_ERRORS = (error.URLError, TimeoutError, ValueError, RuntimeError, OSError)


def fetch_status(name: str, api_url: str = API_URL) -> bool:
    query = parse.urlencode({"filter_eq[name]": name, "role": "DRIVER"})
    req = request.Request(
        f"{api_url}?{query}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        payload = json.load(response)

    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, list):
        raise ValueError("Unexpected API response: missing 'entities' list")

    matches = [
        item for item in entities
        if isinstance(item, dict) and str(item.get("name") or "").casefold() == name.casefold()
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one charger named {name}, got {len(matches)}")

    charger = matches[0]
    if charger.get("maintenanceFlag"):
        return False
    ports = charger.get("ports")
    if not isinstance(ports, list) or not ports:
        raise ValueError(f"No ports returned for {name}")
    return any(isinstance(port, dict) and port.get("status") == "AVAILABLE" for port in ports)


def send_serverchan(name: str, sendkey: str, *, available: bool = True) -> None:
    if not re.fullmatch(r"SCT[A-Za-z0-9]+", sendkey):
        raise ValueError("Invalid SERVERCHAN_SENDKEY")
    data = parse.urlencode({
        "title": f"充电桩 {name} {'空闲了' if available else '被占用了'}",
        "desp": f"{time.strftime('%Y-%m-%d %H:%M')}\n\nhttps://charge.id/{name.lower()}",
    }).encode()
    req = request.Request(
        f"{SERVERCHAN_URL}/{sendkey}.send",
        data=data,
        method="POST",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            result = json.load(response)
    except error.HTTPError as exc:
        # HTTPError includes the request URL, which contains the SendKey.
        raise RuntimeError(f"ServerChan returned HTTP {exc.code}") from None
    except error.URLError as exc:
        raise RuntimeError(f"Could not reach ServerChan: {exc.reason}") from None
    if not isinstance(result, dict) or result.get("code") != 0:
        code = result.get("code") if isinstance(result, dict) else None
        raise RuntimeError(f"ServerChan rejected the message (code {code})")


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


def check_once(names: list[str], sendkey: str, path: Path, *, api_url: str = API_URL) -> None:
    try:
        state = read_state(path)
    except (ValueError, OSError) as exc:
        # A corrupt state file should not stop the watcher; start fresh.
        LOG.warning("Ignoring unreadable state file: %s", exc)
        state = {}

    changed = False
    for name in names:
        try:
            available = fetch_status(name, api_url)
        except CHECK_ERRORS as exc:
            LOG.error("Could not check %s: %s", name, exc)
            continue
        except Exception:  # noqa: BLE001 - keep the daemon alive on surprises
            LOG.exception("Unexpected error while checking %s", name)
            continue

        previous = state.get(name, False)
        label = "available" if available else "not available"
        if available != previous:
            try:
                send_serverchan(name, sendkey, available=available)
            except CHECK_ERRORS as exc:
                # Leave the state unchanged so the next round retries.
                LOG.error("%s is %s but the notification failed: %s", name, label, exc)
                continue
            LOG.info("%s is %s; notification sent", name, label)
        else:
            LOG.debug("%s unchanged (%s)", name, label)

        if state.get(name) != available:
            state[name] = available
            changed = True

    if changed:
        try:
            write_state(path, state)
        except OSError as exc:
            LOG.error("Could not save state to %s: %s", path, exc)


class _Stop(Exception):
    pass


def _raise_stop(*_):
    raise _Stop


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="check once, then exit")
    parser.add_argument("--status", action="store_true", help="print current status without sending messages")
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    names = list(dict.fromkeys(
        item.strip().upper() for item in os.getenv("CHARGERS", "").split(",") if item.strip()
    ))
    sendkey = os.getenv("SERVERCHAN_SENDKEY", "").strip()
    path = Path(os.getenv("STATE_FILE", "./state.json"))
    api_url = os.getenv("CHARGELAB_API_URL", API_URL)
    try:
        interval = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
    except ValueError:
        parser.error("POLL_INTERVAL_SECONDS must be a whole number")

    if not names:
        parser.error("Set CHARGERS, e.g. CHARGERS=EVS-1234,EVS-5678")
    if interval < 60:
        parser.error("POLL_INTERVAL_SECONDS must be at least 60")
    if not args.status and not re.fullmatch(r"SCT[A-Za-z0-9]+", sendkey):
        parser.error("Set SERVERCHAN_SENDKEY to your Server酱 SendKey (starts with SCT)")

    if args.status:
        failed = False
        for name in names:
            try:
                print(f"{name}: {'available' if fetch_status(name, api_url) else 'not available'}")
            except CHECK_ERRORS as exc:
                print(f"{name}: check failed: {exc}", file=sys.stderr)
                failed = True
        return 1 if failed else 0

    # systemd stops services with SIGTERM; exit cleanly instead of dumping a traceback.
    signal.signal(signal.SIGTERM, _raise_stop)
    LOG.info("Watching %s every %ss", ", ".join(names), interval)
    try:
        while True:
            started = time.monotonic()
            check_once(names, sendkey, path, api_url=api_url)
            if args.once:
                return 0
            # Keep a steady cadence regardless of how long the checks took.
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
    except (_Stop, KeyboardInterrupt):
        LOG.info("Stopping")
        return 0


if __name__ == "__main__":
    sys.exit(main())
