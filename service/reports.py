"""Stage 7 Synod: agents report their own status to the Matrix (stdlib only).

Reports are self-reported and unauthenticated: only local processes can post,
but any local process can claim to be any agent on the list.
"""
import json
import os
import tempfile
import threading
import time

AGENTS = (
    "antigravity_gemini",
    "claude_code",
    "grokbot",
    "merlin",
    "gemini_spark",
    "openmanus",
)
STATES = ("working", "idle", "blocked", "done")
MAX_BODY = 4096
MAX_TEXT = 200
SILENT_AFTER_S = 24 * 3600
LOCAL_HOSTS = ("127.0.0.1", "localhost")
CLOSED_ISSUES = ("done", "cancelled")

_lock = threading.Lock()


def host_allowed(host, extra=()):
    """Refuse DNS rebinding: a web page's own name pointed at this machine."""
    name = (host or "").rsplit(":", 1)[0].lower()
    return name in LOCAL_HOSTS or name in extra or name.endswith(".ts.net")


class Refused(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def gate(client, host, ctype, origin, length):
    """Refuse anything but a same-machine, non-browser JSON post of sane size."""
    if client != "127.0.0.1":
        raise Refused(403, "reports are accepted from this machine only")
    if (host or "").rsplit(":", 1)[0] not in LOCAL_HOSTS:
        raise Refused(403, "bad host")
    if origin is not None:
        raise Refused(403, "browser requests are refused")
    if (ctype or "").split(";")[0].strip().lower() != "application/json":
        raise Refused(415, "content type must be application/json")
    if length is None or not length.isdigit():
        raise Refused(411, "content length required")
    if int(length) > MAX_BODY:
        raise Refused(413, "report too large")


def _text(d, key, required):
    v = d.get(key, "")
    if not isinstance(v, str):
        raise Refused(400, f"{key} must be text")
    v = v.strip()
    if required and not v:
        raise Refused(400, f"{key} is required")
    if len(v) > MAX_TEXT:
        raise Refused(400, f"{key} is longer than {MAX_TEXT} characters")
    return v


def validate(raw):
    try:
        d = json.loads(raw)
    except ValueError:
        raise Refused(400, "body is not JSON")
    if not isinstance(d, dict):
        raise Refused(400, "body must be an object")
    if d.get("agent") not in AGENTS:
        raise Refused(400, "unknown agent; use one of: " + ", ".join(AGENTS))
    if d.get("state") not in STATES:
        raise Refused(400, "state must be one of: " + ", ".join(STATES))
    return {
        "agent": d["agent"],
        "state": d["state"],
        "task": _text(d, "task", True),
        "needs_seabass": _text(d, "needs_seabass", False),
    }


def load(path):
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    return {
        k: v for k, v in d.items() if isinstance(v, dict) and isinstance(v.get("at"), int)
    }


def store(path, report, now=None):
    """Keep each agent's latest report; the server stamps the time."""
    record = {**report, "at": int(time.time() if now is None else now)}
    folder = os.path.dirname(path)
    with _lock:
        os.makedirs(folder, exist_ok=True)
        all_reports = load(path)
        all_reports[record["agent"]] = record
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".reports-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(all_reports, f, indent=2)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    return record


def _ago(seconds):
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    return f"{s // 3600}h ago"


def agent_view(all_reports, now):
    """Agent id -> 'state · age', or 'silent' if nothing recent was reported."""
    view = {}
    for agent in AGENTS:
        r = all_reports.get(agent)
        if not r or now - r.get("at", 0) > SILENT_AFTER_S:
            view[agent] = "silent"
        else:
            view[agent] = f"{r.get('state', '?')} · {_ago(now - r['at'])}"
    return view


def relay_view(all_reports, issue_counts, now):
    """Counts come from Paperclip plus agents' asks. Unknown is never shown as 0."""
    newest = max(all_reports, key=lambda a: all_reports[a]["at"], default=None)
    # An ask stays counted however old it is, until that agent reports again.
    items = [
        f"{a}: {r['needs_seabass']}"
        for a, r in all_reports.items()
        if r.get("needs_seabass")
    ]
    if issue_counts is None:
        open_tasks = needs = "unknown"
    else:
        open_tasks = sum(n for s, n in issue_counts.items() if s not in CLOSED_ISSUES)
        needs = (
            issue_counts.get("in_review", 0) + issue_counts.get("blocked", 0) + len(items)
        )
    return {
        "last_entry": (
            f"{newest}: {all_reports[newest].get('task')} "
            f"({_ago(now - all_reports[newest]['at'])})"
            if newest
            else "No agent has reported yet"
        ),
        "open_tasks": open_tasks,
        "needs_seabass": needs,
        "needs_seabass_items": items,
        "source": "Paperclip in_review + blocked, plus asks in agents' self-reports",
    }
