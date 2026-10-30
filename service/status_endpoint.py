#!/usr/bin/env python3
"""Matrix Control Surface status endpoint (stdlib only). Tailnet-bound, read-only."""

import json, os, subprocess, sys, threading, time, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BIND = os.environ.get("STATUS_BIND", "")
PORT = int(os.environ.get("STATUS_PORT", "8787"))
SNAPSHOT = os.environ.get("STATUS_SNAPSHOT", "/home/oem/matrix-status.json")
INTERVAL = 30
STARTED = time.time()


def sh(cmd):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        return ""


def active(unit, user=False):
    return (
        sh(["systemctl"] + (["--user"] if user else []) + ["is-active", unit])
        or "unknown"
    )


def disk(path):
    out = sh(["df", "-BG", "--output=size,used,avail,pcent", path]).splitlines()
    if len(out) < 2:
        return None
    s, u, a, p = out[1].split()
    return {"path": path, "size": s, "used": u, "avail": a, "pct": p}


def mem():
    out = sh(["free", "-g"]).splitlines()
    for l in out:
        if l.startswith("Mem:"):
            f = l.split()
            return {"total_gb": int(f[1]), "used_gb": int(f[2]), "avail_gb": int(f[6])}
    return None


def build():
    with open("/proc/uptime") as f:
        up = float(f.read().split()[0])
    sessions = [
        l.split()[0]
        for l in sh(["zellij", "list-sessions", "--no-formatting"]).splitlines()
        if l.strip()
    ]
    mm = "/mnt/agent-memory"
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "box": {
            "hostname": os.uname().nodename,
            "uptime_s": int(up),
            "ram": mem(),
            "disk_root": disk("/"),
            "disk_1tb": disk(mm) if os.path.ismount(mm) else None,
        },
        "network": {
            "tailscale_ip": sh(["tailscale", "ip", "-4"]),
            "lan_ip": (sh(["hostname", "-I"]).split() or [""])[0],
            "ssh": active("ssh"),
        },
        "services": {
            "ssh": active("ssh"),
            "docker": active("docker"),
            "zellij_sessions": sessions,
            "claude_code": "running" if sh(["pgrep", "-f", "claude"]) else "idle",
            "grokbot": "unknown",
        },
        "agents": {
            "claude_code": "unknown",
            "grokbot": "unknown",
            "merlin": "unknown",
            "gemini_spark": "unknown",
        },
        "shared_memory": {
            "drive": mm,
            "role": "1TB shared memory",
            "mounted": os.path.ismount(mm),
            "flag": "READ-ONLY SEARCH PENDING",
        },
        "sonolumina": {
            "repo": "skrahn-dot/matrix-control-surface",
            "home_note_hz": 110,
        },
        "relay": {"last_entry": None, "open_tasks": None, "needs_seabass": None},
        "phase": "Stage 3 NERVOUS SYSTEM - Pulse",
        "endpoint": {"version": "v2", "uptime_s": int(time.time() - STARTED)},
    }


_latest = {}


def snapshot_loop():
    global _latest
    while True:
        try:
            _latest = build()
            tmp = SNAPSHOT + ".tmp"
            with open(tmp, "w") as f:
                json.dump(_latest, f, indent=2)
            os.replace(tmp, SNAPSHOT)
        except Exception as e:
            print("snapshot error:", e, file=sys.stderr, flush=True)
        time.sleep(INTERVAL)


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/status":
            self._send(200, json.dumps(build(), indent=2))
        elif p == "/health":
            self._send(
                200, json.dumps({"ok": True, "uptime_s": int(time.time() - STARTED)})
            )
        elif p == "/":
            self._send(
                200, '<p>Matrix status: <a href="/status">/status</a></p>', "text/html"
            )
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, fmt, *a):
        print("%s %s" % (self.address_string(), fmt % a), flush=True)


if __name__ == "__main__":
    threading.Thread(target=snapshot_loop, daemon=True).start()
    # LAW: tailnet-only. No 0.0.0.0 fallback; retry until the Tailscale IP exists.
    while True:
        bind_host = BIND or (sh(["tailscale", "ip", "-4"]).splitlines() or [""])[0]
        if not bind_host:
            print(
                "tailscale ip -4 not available yet; retrying in 10s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(10)
            continue
        try:
            srv = ThreadingHTTPServer((bind_host, PORT), H)
            break
        except OSError as e:
            print(
                f"bind {bind_host}:{PORT} failed ({e}); retrying in 10s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(10)
    print(f"serving on http://{bind_host}:{PORT}", flush=True)
    srv.serve_forever()
