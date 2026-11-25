"""The Uncle Whisperer - a personal agent for the week of Thanksgiving.

You paste a message a relative sent you. The agent tells you what is really
bothering the person who wrote it, what you should not answer, and one sentence
you can send back. It remembers each relative on the Sprite's disk, so the next
time the same relative writes, the agent reminds you what bothered them before.

Runs on a Fly.io Sprite. Talks to a language model only through the Sprites
OpenRouter connector (the Sprites gateway), so this code never holds an API key.

Python standard library only. Start with:  python3 app.py
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("PORT", "8080"))
HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("UNCLE_DATA_DIR", str(Path.home() / "uncle-data")))
MEMORY_FILE = DATA_DIR / "memory.json"

GATEWAY_LIST_URL = "https://api.sprites.dev/v1/gateway/list"
# Optional override. If empty, the app asks the gateway which connectors exist.
GATEWAY_BASE_URL = os.environ.get("OPENROUTER_GATEWAY_URL", "").rstrip("/")
CHAT_PATH = os.environ.get("OPENROUTER_CHAT_PATH", "/v1/chat/completions")
# Tried in order. The first model that returns a usable reading wins.
MODELS = [m.strip() for m in os.environ.get(
    "UNCLE_MODELS",
    "nvidia/nemotron-3-ultra-550b-a55b:free,baidu/ernie-5.5-flash-preview:free,google/gemma-4-31b-it:free,openrouter/free",
).split(",") if m.strip()]

MAX_MESSAGE_CHARS = 1500
MAX_NAME_CHARS = 40
MAX_READS_PER_DAY = int(os.environ.get("UNCLE_MAX_READS_PER_DAY", "300"))
MAX_READS_PER_FAMILY_PER_HOUR = 20
KEEP_PER_RELATIVE = 5

SYSTEM_PROMPT = """You are The Uncle Whisperer, a personal agent that helps one person
(the "reader") answer a message from a relative before a family holiday dinner.

The reader pastes a message that a relative wrote to them. Read the relative's
exact words and work out what is really bothering the relative. The thing that
bothers a person is usually not the topic they write about. Someone who writes
"don't bother cooking, we'll eat before we come" is rarely writing about food.

Rules:
- Stay with the words on the page. Quote the few words that gave it away.
- Do not diagnose, do not use therapy language, do not insult the relative.
- "dont" is the one answer the reader is most tempted to send and should not,
  and what that answer would do to the relative.
- "reply" is one or two sentences the reader can send as they are. Warm, plain,
  no sarcasm, no apology the reader does not owe. It answers what is bothering
  the relative, not the surface topic.
- If earlier readings of the same relative are given, say in "seen_before"
  whether the same thing is bothering the relative again, in one sentence that
  names the earlier message. If there are none, use an empty string.
- Write to the reader as "you". Name the relative by the name the reader gave.

Answer with one JSON object and nothing else:
{"bothering": "...", "clue": "the exact words from the message", "dont": "...", "reply": "...", "seen_before": "..."}"""

_lock = threading.Lock()
_gateway_cache = {"base": None, "at": 0.0, "raw": None}
_day_counter = {"day": "", "count": 0}
_family_hits = {}


def _http_json(url, payload=None, timeout=45):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _walk(node):
    """Yield every dict inside a nested JSON value."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def gateway_status(force=False):
    """Ask the Sprites gateway which connectors this Sprite may use.

    Returns (openrouter_base_url_or_None, public_summary). The summary lists
    provider names only. Connection ids stay on the Sprite.
    """
    now = time.time()
    if not force and _gateway_cache["raw"] is not None and now - _gateway_cache["at"] < 300:
        return _gateway_cache["base"], _gateway_cache["raw"]
    summary = {"reachable": False, "connected_providers": [], "error": ""}
    base = GATEWAY_BASE_URL or None
    try:
        listing = _http_json(GATEWAY_LIST_URL, timeout=15)
        summary["reachable"] = True
        for item in _walk(listing):
            provider = item.get("provider") or item.get("name")
            url = item.get("gateway_base_url")
            if isinstance(provider, str) and isinstance(url, str) and url:
                if provider not in summary["connected_providers"]:
                    summary["connected_providers"].append(provider)
                if base is None and "openrouter" in provider.lower():
                    base = url.rstrip("/")
    except Exception as exc:  # outside a Sprite the gateway answers 401
        summary["error"] = type(exc).__name__
    _gateway_cache.update(base=base, at=now, raw=summary)
    return base, summary


def load_memory():
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_memory(memory):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MEMORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(memory, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(MEMORY_FILE)


def allow_read(family):
    """Small limits so a public demo cannot spend the whole budget."""
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    with _lock:
        if _day_counter["day"] != today:
            _day_counter.update(day=today, count=0)
        if _day_counter["count"] >= MAX_READS_PER_DAY:
            return False, "The agent has read its limit of messages for today. Come back tomorrow."
        hits = [t for t in _family_hits.get(family, []) if now - t < 3600]
        if len(hits) >= MAX_READS_PER_FAMILY_PER_HOUR:
            return False, "You sent the agent 20 messages in the last hour. Try again later."
        hits.append(now)
        _family_hits[family] = hits
        _day_counter["count"] += 1
    return True, ""


def parse_reading(text):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model did not return JSON")
    raw = json.loads(text[start:end + 1])
    return {key: str(raw.get(key, "")).strip()[:900]
            for key in ("bothering", "clue", "dont", "reply", "seen_before")}


def read_message(relative, message, earlier):
    base, _ = gateway_status()
    if not base:
        raise RuntimeError("no OpenRouter connector is available to this Sprite")
    user_parts = []
    if earlier:
        user_parts.append("Earlier messages from %s that you already read:" % relative)
        for item in earlier:
            user_parts.append('- On %s, %s wrote: "%s". What was bothering %s then: %s'
                              % (item["day"], relative, item["message"], relative, item["bothering"]))
        user_parts.append("")
    user_parts.append('New message from %s to the reader:\n"""\n%s\n"""' % (relative, message))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
    last_error = None
    for model in MODELS + MODELS[:2]:  # free models are rate-limited at times
        payload = {"model": model, "max_tokens": 900, "temperature": 0.4, "messages": messages}
        try:
            answer = _http_json(base + CHAT_PATH, payload)
            reading = parse_reading(answer["choices"][0]["message"]["content"] or "")
            if reading["bothering"] and reading["reply"]:
                reading["model"] = model
                return reading
            last_error = ValueError("empty reading")
        except Exception as exc:  # try the next model
            last_error = exc
    raise last_error or RuntimeError("no model configured")


def clean(text, limit):
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", str(text or "")).strip()
    return text[:limit]


class Handler(BaseHTTPRequestHandler):
    server_version = "UncleWhisperer/1.0"

    def log_message(self, fmt, *args):  # keep the log free of visitor text
        pass

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _family(self):
        family = self.headers.get("X-Family", "")
        return family if re.fullmatch(r"[a-f0-9]{16,64}", family) else ""

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/connected":
            base, summary = gateway_status(force=True)
            self._send(200, {
                "runs_on_sprite": summary["reachable"],
                "gateway": "api.sprites.dev/v1/gateway",
                "connected_providers": summary["connected_providers"],
                "openrouter_ready": bool(base),
                "models": MODELS,
                "error": summary["error"],
            })
        elif path == "/api/relatives":
            family = self._family()
            relatives = load_memory().get(family, {}) if family else {}
            self._send(200, {"relatives": [
                {"name": name, "times": len(items), "last": items[-1]}
                for name, items in relatives.items() if items]})
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._send(404, {"error": "Not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/api/read":
            self._send(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 20000:
                raise ValueError
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            relative = clean(body.get("relative"), MAX_NAME_CHARS)
            message = clean(body.get("message"), MAX_MESSAGE_CHARS)
        except (ValueError, AttributeError):
            self._send(400, {"error": "The agent could not read what you sent."})
            return
        family = self._family()
        if not family or not relative or len(message) < 3:
            self._send(400, {"error": "Write who sent the message, and paste the message."})
            return
        ok, why = allow_read(family)
        if not ok:
            self._send(429, {"error": why})
            return
        key = relative.lower()
        with _lock:
            earlier = list(load_memory().get(family, {}).get(key, []))
        try:
            reading = read_message(relative, message, earlier[-3:])
        except urllib.error.HTTPError as exc:
            self._send(502, {"error": "The language model did not answer (HTTP %d). Try again in a minute." % exc.code})
            return
        except Exception as exc:
            self._send(502, {"error": "The agent could not finish the reading (%s). Try again in a minute." % type(exc).__name__})
            return
        entry = {"day": time.strftime("%B %d", time.gmtime()), "relative": relative,
                 "message": message[:300], "bothering": reading["bothering"]}
        with _lock:
            memory = load_memory()
            items = memory.setdefault(family, {}).setdefault(key, [])
            items.append(entry)
            del items[:-KEEP_PER_RELATIVE]
            save_memory(memory)
        reading["times_read"] = len(earlier) + 1
        reading["relative"] = relative
        self._send(200, reading)


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("The Uncle Whisperer listens on port %d" % PORT, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
