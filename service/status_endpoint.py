#!/usr/bin/env python3
"""Matrix Control Surface — Unified AI Operating System Portal & Status Endpoint (v3.1).
Stdlib only. Tailnet + loopback bound (:8787), read-only telemetry + unified AI OS UI.
"""

import datetime
import json
import mimetypes
import os
import posixpath
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BIND = os.environ.get("STATUS_BIND", "")
PORT = int(os.environ.get("STATUS_PORT", "8787"))
SNAPSHOT = os.environ.get("STATUS_SNAPSHOT", "/home/oem/matrix-status.json")
SONOLUMINA_DIR = Path(os.environ.get("SONOLUMINA_DIR", "/home/oem/sonolumina-repo")).resolve()
SONOLUMINA_LOOP_DIR = Path("/home/oem/sonolumina-loop").resolve()
MATRIX_DIR = Path("/home/oem/matrix/src/Cross Coat AI/cross-coat-matrix-master")
SHARED_MEM_DIR = Path("/mnt/agent-memory/shared-memory")
INTERVAL = 30
STARTED = time.time()
SELF_PATH = os.path.abspath(__file__)
try:
    SELF_MTIME = os.path.getmtime(SELF_PATH)
except OSError:
    SELF_MTIME = None


def sh(cmd, timeout=5):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        ).stdout.strip()
    except Exception:
        return ""


def active(unit, user=False):
    out = sh(["systemctl"] + (["--user"] if user else []) + ["is-active", unit])
    return out if out else "unknown"


def has_proc(pattern):
    return bool(sh(["pgrep", "-f", pattern]))


def probe_port(host, port, path=None, timeout=1.2):
    if path:
        try:
            req = urllib.request.Request(f"http://{host}:{port}{path}", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return f"online ({resp.status})"
        except urllib.error.HTTPError as e:
            return f"online ({e.code})"
        except Exception:
            pass
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "online"
    except Exception:
        return "offline"


def disk(path):
    out = sh(["df", "-BG", "--output=size,used,avail,pcent", path]).splitlines()
    if len(out) < 2:
        return None
    s, u, a, p = out[1].split()
    return {"path": path, "size": s, "used": u, "avail": a, "pct": p}


def mem_info():
    out = sh(["free", "-g"]).splitlines()
    ram = None
    swap = None
    for l in out:
        if l.startswith("Mem:"):
            f = l.split()
            ram = {"total_gb": int(f[1]), "used_gb": int(f[2]), "avail_gb": int(f[6])}
        elif l.startswith("Swap:"):
            f = l.split()
            swap = {"total_gb": int(f[1]), "used_gb": int(f[2]), "free_gb": int(f[3])}
    return ram, swap


def os_release():
    info = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    info[k] = v.strip('"')
    except Exception:
        pass
    uname = os.uname()
    return {
        "pretty_name": info.get("PRETTY_NAME", "Linux Mint"),
        "version": info.get("VERSION", ""),
        "kernel": uname.release,
        "arch": uname.machine,
        "motherboard": "ASUS ROG STRIX B550-F Gaming",
    }


def sensors_info():
    raw = sh(["sensors", "-j"])
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    res = {"fans": {}}
    k10 = data.get("k10temp-pci-00c3", {})
    if isinstance(k10, dict):
        tctl = k10.get("Tctl", {}).get("temp1_input")
        tccd1 = k10.get("Tccd1", {}).get("temp3_input")
        if tctl is not None:
            res["cpu_tctl_c"] = round(float(tctl), 1)
        if tccd1 is not None:
            res["cpu_tccd1_c"] = round(float(tccd1), 1)
    nvme = data.get("nvme-pci-0400", {})
    if isinstance(nvme, dict):
        comp = nvme.get("Composite", {}).get("temp1_input")
        if comp is not None:
            res["nvme_temp_c"] = round(float(comp), 1)
    iwl = data.get("iwlwifi_1_0-virtual-0", {})
    if isinstance(iwl, dict):
        wt = iwl.get("temp1", {}).get("temp1_input")
        if wt is not None:
            res["wifi_temp_c"] = round(float(wt), 1)
    for chip, cdata in data.items():
        if not isinstance(cdata, dict):
            continue
        for k, v in cdata.items():
            if isinstance(v, dict) and k.startswith("fan"):
                for fk, fv in v.items():
                    if fk.endswith("_input") and fv is not None:
                        res["fans"][k] = int(float(fv))
    return res


def cpu_info(sens):
    model = "AMD Ryzen 5 5600X 6-Core Processor"
    cores = 6
    threads = 12
    max_mhz = 5281.8
    out = sh(["lscpu"])
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        if k == "Model name":
            model = v
        elif k == "CPU(s)" and v.isdigit():
            threads = int(v)
        elif k == "Core(s) per socket" and v.isdigit():
            cores = int(v)
        elif k == "CPU max MHz":
            try:
                max_mhz = round(float(v), 0)
            except Exception:
                pass
    boost = None
    boost_file = Path("/sys/devices/system/cpu/cpufreq/boost")
    if boost_file.exists():
        try:
            boost = boost_file.read_text().strip() == "1"
        except Exception:
            pass
    load_1, load_5, load_15 = "0.00", "0.00", "0.00"
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            if len(parts) >= 3:
                load_1, load_5, load_15 = parts[0], parts[1], parts[2]
    except Exception:
        pass
    return {
        "model": model,
        "cores": cores,
        "threads": threads,
        "max_mhz": max_mhz,
        "boost_enabled": boost,
        "load_avg": f"{load_1} / {load_5} / {load_15}",
        "load_1m": float(load_1),
        "temp_c": sens.get("cpu_tctl_c"),
        "ccd_temp_c": sens.get("cpu_tccd1_c"),
    }


def gpu_info():
    out = sh([
        "nvidia-smi",
        "--query-gpu=name,driver_version,temperature.gpu,power.draw,power.limit,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return None
    line = out.splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 8:
        return None
    try:
        return {
            "name": parts[0],
            "driver": parts[1],
            "temp_c": int(float(parts[2])),
            "power_w": round(float(parts[3]), 1),
            "power_cap_w": int(float(parts[4])),
            "vram_used_mib": int(float(parts[5])),
            "vram_total_mib": int(float(parts[6])),
            "util_pct": int(float(parts[7])),
        }
    except Exception:
        return {"name": parts[0], "driver": parts[1]}


def block_devices(sens):
    raw = sh(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL"])
    if not raw:
        return []
    try:
        jb = json.loads(raw).get("blockdevices", [])
    except Exception:
        return []
    drives = []
    for d in jb:
        if d.get("type") != "disk":
            continue
        name = d.get("name", "")
        model = (d.get("model") or "").strip()
        size = d.get("size", "")
        parts = []
        for c in d.get("children") or []:
            parts.append({
                "name": c.get("name"),
                "size": c.get("size"),
                "mountpoint": c.get("mountpoint"),
            })
        drives.append({
            "name": name,
            "model": model or name,
            "size": size,
            "temp_c": sens.get("nvme_temp_c") if name.startswith("nvme") else None,
            "partitions": parts,
        })
    return drives


def audio_devices():
    play_raw = sh(["aplay", "-l"])
    cap_raw = sh(["arecord", "-l"])
    playback = []
    capture = []
    hdmi_monitors = []
    for line in play_raw.splitlines():
        if line.startswith("card "):
            m = re.match(r"card\s+(\d+):\s+([^\[]+)\[([^\]]+)\],\s+device\s+(\d+):\s+([^\[]+)\[([^\]]+)\]", line)
            if m:
                card_id, short, card_name, dev_id, dev_short, dev_name = [x.strip() for x in m.groups()]
                playback.append({
                    "card": int(card_id),
                    "device": int(dev_id),
                    "name": f"{card_name} · {dev_name}",
                    "short": dev_name,
                })
                if card_name == "HDA NVidia" and not dev_name.startswith("HDMI"):
                    hdmi_monitors.append(dev_name)
    for line in cap_raw.splitlines():
        if line.startswith("card "):
            m = re.match(r"card\s+(\d+):\s+([^\[]+)\[([^\]]+)\],\s+device\s+(\d+):\s+([^\[]+)\[([^\]]+)\]", line)
            if m:
                card_id, short, card_name, dev_id, dev_short, dev_name = [x.strip() for x in m.groups()]
                capture.append({
                    "card": int(card_id),
                    "device": int(dev_id),
                    "name": f"{card_name} · {dev_name}",
                })
    return playback, capture, hdmi_monitors


def display_devices(hdmi_monitors):
    connectors = []
    drm_root = Path("/sys/class/drm")
    mon_idx = 0
    if drm_root.exists():
        for p in sorted(drm_root.glob("card*-*")):
            st_file = p / "status"
            if not st_file.exists():
                continue
            try:
                status = st_file.read_text().strip()
            except Exception:
                continue
            port = re.sub(r"^card\d+-", "", p.name)
            monitor = None
            if status == "connected" and mon_idx < len(hdmi_monitors):
                monitor = hdmi_monitors[mon_idx]
                mon_idx += 1
            connectors.append({
                "port": port,
                "status": status,
                "monitor": monitor,
            })
    return connectors


def usb_devices():
    out = sh(["lsusb"])
    items = []
    for line in out.splitlines():
        if "root hub" in line.lower():
            continue
        m = re.match(r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-fA-F:]+)\s+(.*)", line)
        if m:
            bus, dev, usb_id, desc = m.groups()
            items.append({
                "bus": bus,
                "device": dev,
                "id": usb_id,
                "name": desc.strip(),
            })
    return items


def matrix_info():
    env_info = {
        "llm_provider": "gemini",
        "gemini_model": "gemini-2.5-flash",
        "xai_model": "grok-4.6",
        "claude_model": "claude-sonnet-4-5",
    }
    env_file = MATRIX_DIR / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "LLM_PROVIDER":
                    env_info["llm_provider"] = v
                elif k == "GEMINI_MODEL":
                    env_info["gemini_model"] = v
                elif k == "XAI_MODEL":
                    env_info["xai_model"] = v
                elif k == "CLAUDE_MODEL":
                    env_info["claude_model"] = v
        except Exception:
            pass

    roster = []
    names_file = MATRIX_DIR / "matrix_names.json"
    if names_file.exists():
        try:
            nd = json.loads(names_file.read_text())
            roster = nd.get("agents", [])
        except Exception:
            pass

    standing_job = ""
    sj_file = Path("/home/oem/matrix-job-next.txt")
    if sj_file.exists():
        try:
            standing_job = sj_file.read_text(errors="ignore").strip()
        except Exception:
            pass

    morning_note = ""
    mn_file = Path("/home/oem/matrix-morning-note.txt")
    if mn_file.exists():
        try:
            morning_note = mn_file.read_text(errors="ignore").strip()
        except Exception:
            pass

    return {
        "ceo": "Seabass Krahn",
        "mode": "Draft-Only (Approval Gate Enforced)",
        "brains": env_info,
        "roster": roster,
        "standing_job": standing_job,
        "morning_note": morning_note,
    }


def shared_memory_details(mm="/mnt/agent-memory"):
    mounted = os.path.ismount(mm)
    sm_root = Path(mm) / "shared-memory"
    index_lines = []
    entries = []
    folders = []
    if mounted and sm_root.exists():
        try:
            folders = sorted([p.name for p in sm_root.iterdir() if p.is_dir() and not p.name.startswith(".")])
        except Exception:
            pass
        idx_file = sm_root / "INDEX.md"
        if idx_file.exists():
            try:
                raw_lines = idx_file.read_text(errors="ignore").splitlines()
                index_lines = [l for l in raw_lines if l.strip()][:60]
                for l in raw_lines:
                    m = re.match(r"^\s*-\s*\[([^\]]+)\]\(([^)]+)\)\s*(?:—|--|-)?\s*(.*)$", l)
                    if m:
                        title, rel_p, summary = m.groups()
                        entries.append({
                            "title": title.strip(),
                            "path": rel_p.strip(),
                            "summary": summary.strip(),
                        })
            except Exception:
                pass
    return {
        "drive": mm,
        "role": "1TB shared memory (WD Blue SA510)",
        "mounted": mounted,
        "flag": "SHARED MEMORY READY" if (mounted and sm_root.exists()) else "READ-ONLY SEARCH PENDING",
        "folders": folders,
        "index_preview": index_lines,
        "entries": entries,
    }


def build():
    with open("/proc/uptime") as f:
        up = float(f.read().split()[0])
    sessions = [
        l.split()[0]
        for l in sh(["zellij", "list-sessions", "--no-formatting"]).splitlines()
        if l.strip()
    ]
    mm = "/mnt/agent-memory"
    ram, swap = mem_info()
    sens = sensors_info()
    cpu = cpu_info(sens)
    gpu = gpu_info()
    drives = block_devices(sens)
    playback, capture, hdmi_monitors = audio_devices()
    displays = display_devices(hdmi_monitors)
    usb = usb_devices()
    os_info = os_release()
    mat = matrix_info()
    sm = shared_memory_details(mm)

    claude_running = has_proc("claude")
    grok_running = has_proc("grok")
    agy_running = has_proc("antigravity")
    paperclip_state = active("paperclipai", user=True)
    keeper_running = has_proc("keeper_dashboard") or has_proc("keeper_worker")
    openmanus_running = has_proc("OpenManus") or has_proc("run_mcp")

    ep_health = {
        "paperclip_3100": probe_port("127.0.0.1", 3100, "/api/health"),
        "n8n_5678": probe_port("127.0.0.1", 5678, "/healthz"),
        "matrix_api_8000": probe_port("127.0.0.1", 8000, "/health"),
        "keeper_8766": probe_port("127.0.0.1", 8766, "/"),
        "status_8787": "online (200)",
    }

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "box": {
            "hostname": os.uname().nodename,
            "uptime_s": int(up),
            "ram": ram,
            "swap": swap,
            "disk_root": disk("/"),
            "disk_1tb": disk(mm) if os.path.ismount(mm) else None,
        },
        "hardware": {
            "os": os_info,
            "cpu": cpu,
            "gpu": gpu,
            "drives": drives,
            "sensors": sens,
        },
        "devices": {
            "displays": displays,
            "audio_playback": playback,
            "audio_capture": capture,
            "usb": usb,
        },
        "network": {
            "tailscale_ip": sh(["tailscale", "ip", "-4"]),
            "lan_ip": (sh(["hostname", "-I"]).split() or [""])[0],
            "ssh": active("ssh"),
        },
        "endpoints_health": ep_health,
        "services": {
            "ssh": active("ssh"),
            "docker": active("docker"),
            "paperclip": paperclip_state if paperclip_state != "unknown" else ("ready" if os.path.exists("/home/oem/.paperclip") else "inactive"),
            "keeper": "running" if keeper_running or "online" in ep_health["keeper_8766"] else "standby",
            "zellij_sessions": sessions,
            "claude_code": "running" if claude_running else "idle",
            "grokbot": "running" if grok_running else ("ready" if os.path.exists("/home/oem/.grok") else "standby"),
            "antigravity": "running" if agy_running else "online",
        },
        "agents": {
            "antigravity_gemini": "online" if agy_running else "ready",
            "claude_code": "running" if claude_running else "ready",
            "grokbot": "running" if grok_running else ("ready" if os.path.exists("/home/oem/.grok") else "standby"),
            "merlin": "active" if paperclip_state == "active" else "ready",
            "gemini_spark": "ready",
            "openmanus": "running" if openmanus_running else ("ready" if os.path.exists("/home/oem/OpenManus") else "standby"),
        },
        "matrix": mat,
        "shared_memory": sm,
        "sonolumina": {
            "repo": "seabasskrahn/sonolumina",
            "control_surface_repo": "skrahn-dot/matrix-control-surface",
            "home_note_hz": 110,
            "local_app_url": "/sonolumina/index.html",
            "local_dash_url": "/sonolumina/index.html#s-dash",
        },
        "relay": {"last_entry": "Stage 6/7 Unified AI OS Portal v3.1 live on :8787", "open_tasks": 0, "needs_seabass": 0},
        "phase": "Stage 6/7 UNIFIED AI OPERATING SYSTEM — Surface & Synod",
        "endpoint": {"version": "v3.1", "uptime_s": int(time.time() - STARTED)},
    }


PORTAL_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Seabass AI OS · Cross Coat Matrix × Sonolumina</title>
<style>
  :root {
    --bg: #07090e;
    --panel: #0e131d;
    --card: #131a28;
    --border: #222d42;
    --fg: #e8ecf4;
    --dim: #8b98b1;
    --gold: #e6b450;
    --blue: #4f8ef7;
    --green: #22c55e;
    --amber: #f59e0b;
    --red: #ef4444;
    --purple: #a855f7;
    --mono: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
    --sans: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font-family: var(--sans); font-size: 14px; line-height: 1.45;
    display: flex; flex-direction: column; min-height: 100vh;
  }
  header.os-bar {
    position: sticky; top: 0; z-index: 50;
    background: rgba(14, 19, 29, 0.92); backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border);
    padding: 0.65rem 1.1rem;
    display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
  }
  .os-brand { display: flex; align-items: center; gap: 0.75rem; }
  .os-orb {
    width: 12px; height: 12px; border-radius: 50%;
    background: var(--green); box-shadow: 0 0 12px var(--green);
  }
  .os-title { font-weight: 700; font-size: 1.05rem; letter-spacing: 0.02em; }
  .os-sub { color: var(--dim); font-size: 0.78rem; font-family: var(--mono); }
  .os-vitals { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
  .vital-chip {
    background: var(--card); border: 1px solid var(--border);
    padding: 0.25rem 0.6rem; border-radius: 999px;
    font-family: var(--mono); font-size: 0.76rem; color: var(--fg);
    display: inline-flex; align-items: center; gap: 0.35rem;
  }
  .vital-chip b { color: var(--gold); font-weight: 600; }
  nav.os-tabs {
    background: var(--panel); border-bottom: 1px solid var(--border);
    padding: 0.4rem 1.1rem; display: flex; gap: 0.45rem; overflow-x: auto;
  }
  nav.os-tabs button {
    background: transparent; color: var(--dim);
    border: 1px solid transparent; border-radius: 8px;
    padding: 0.45rem 0.85rem; font-size: 0.84rem; font-weight: 600;
    cursor: pointer; white-space: nowrap; transition: all 0.15s;
  }
  nav.os-tabs button:hover { color: var(--fg); background: rgba(255,255,255,0.04); }
  nav.os-tabs button.active {
    color: #0b0e14; background: var(--gold); border-color: var(--gold);
  }
  main.os-main { flex: 1; padding: 1.1rem; max-width: 1440px; width: 100%; margin: 0 auto; }
  .pane { display: none; }
  .pane.active { display: block; }
  .grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr));
    gap: 1rem; margin-bottom: 1rem;
  }
  .grid-wide {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr));
    gap: 1rem; margin-bottom: 1rem;
  }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 1rem 1.1rem;
  }
  .card h3 {
    margin: 0 0 0.7rem 0; font-size: 0.88rem; text-transform: uppercase;
    letter-spacing: 0.06em; color: var(--gold);
    display: flex; align-items: center; justify-content: space-between;
  }
  .stat-row {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 0.65rem; margin-bottom: 0.75rem;
  }
  .stat-box {
    background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px; padding: 0.55rem 0.7rem;
  }
  .stat-box .lbl { color: var(--dim); font-size: 0.72rem; text-transform: uppercase; display: block; }
  .stat-box .val { font-family: var(--mono); font-size: 1.02rem; font-weight: 700; margin-top: 0.15rem; display: block; }
  .stat-box .sub { color: var(--dim); font-size: 0.72rem; font-family: var(--mono); }
  .kv {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.36rem 0; border-bottom: 1px solid rgba(255,255,255,0.05);
    gap: 0.6rem; font-size: 0.84rem;
  }
  .kv:last-child { border-bottom: none; }
  .kv .k { color: var(--dim); }
  .kv .v { font-family: var(--mono); text-align: right; }
  .pill {
    display: inline-flex; align-items: center; padding: 0.15rem 0.55rem;
    border-radius: 999px; font-family: var(--mono); font-size: 0.72rem; font-weight: 600;
    text-transform: uppercase;
  }
  .pill.ok { background: rgba(34, 197, 94, 0.16); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.35); }
  .pill.warn { background: rgba(245, 158, 11, 0.16); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.35); }
  .pill.err { background: rgba(239, 68, 68, 0.16); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35); }
  .pill.info { background: rgba(79, 142, 247, 0.16); color: #93c5fd; border: 1px solid rgba(79, 142, 247, 0.35); }
  .btn {
    background: rgba(255,255,255,0.06); color: var(--fg);
    border: 1px solid var(--border); border-radius: 8px;
    padding: 0.42rem 0.8rem; font-size: 0.82rem; font-weight: 600;
    cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 0.4rem;
  }
  .btn:hover { border-color: var(--gold); color: var(--gold); }
  .btn.gold { background: var(--gold); color: #0b0e14; border-color: var(--gold); }
  .btn.gold:hover { filter: brightness(1.08); color: #0b0e14; }
  .roster-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 0.65rem;
  }
  .agent-tile {
    background: rgba(255,255,255,0.025); border: 1px solid var(--border);
    border-radius: 9px; padding: 0.65rem 0.75rem;
  }
  .agent-tile .top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.25rem; }
  .agent-tile .name { font-weight: 700; font-size: 0.88rem; }
  .agent-tile .role { color: var(--dim); font-size: 0.76rem; }
  pre.codebox {
    background: #080b11; border: 1px solid var(--border); border-radius: 8px;
    padding: 0.75rem; font-family: var(--mono); font-size: 0.78rem;
    color: #cbd5e1; overflow-x: auto; white-space: pre-wrap; margin: 0.4rem 0 0 0;
    max-height: 440px; overflow-y: auto;
  }
  .mem-list {
    max-height: 460px; overflow-y: auto; display: flex; flex-direction: column; gap: 0.4rem;
  }
  .mem-item {
    background: rgba(255,255,255,0.025); border: 1px solid var(--border);
    border-radius: 8px; padding: 0.55rem 0.7rem; cursor: pointer; text-align: left; color: var(--fg);
  }
  .mem-item:hover { border-color: var(--gold); }
  .mem-item b { color: var(--gold); display: block; font-size: 0.84rem; }
  .mem-item small { color: var(--dim); font-size: 0.76rem; display: block; margin-top: 0.15rem; }
  .frame-wrap {
    background: #000; border: 1px solid var(--border); border-radius: 12px;
    overflow: hidden; height: calc(100vh - 155px); min-height: 620px;
    display: flex; flex-direction: column;
  }
  .frame-bar {
    background: var(--panel); border-bottom: 1px solid var(--border);
    padding: 0.5rem 0.85rem; display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap;
  }
  .frame-bar select {
    background: var(--card); color: var(--fg); border: 1px solid var(--border);
    border-radius: 6px; padding: 0.35rem 0.65rem; font-size: 0.84rem;
  }
  iframe.os-frame { width: 100%; flex: 1; border: 0; background: #07090e; }
</style>
</head>
<body>
  <header class="os-bar">
    <div class="os-brand">
      <span class="os-orb" id="orb"></span>
      <div>
        <div class="os-title">SEABASS AI OPERATING SYSTEM</div>
        <div class="os-sub" id="osSub">Cross Coat Matrix × Sonolumina · Connecting to :8787…</div>
      </div>
    </div>
    <div class="os-vitals" id="osVitals">
      <span class="vital-chip">Home Note <b>110 Hz</b></span>
    </div>
  </header>

  <nav class="os-tabs" id="osTabs">
    <button type="button" class="active" data-pane="overview">⊞ Command Center</button>
    <button type="button" data-pane="hardware">⚙ Hardware &amp; Devices</button>
    <button type="button" data-pane="matrix">◇ Matrix &amp; Synod Agents</button>
    <button type="button" data-pane="memory">◈ 1 TB Shared Memory</button>
    <button type="button" data-pane="sonolumina">◉ Sonolumina + #s-dash</button>
    <button type="button" data-pane="garden">🌿 First Garden &amp; Gates (1–11)</button>
  </nav>

  <main class="os-main">
    <section id="pane-overview" class="pane active">
      <div class="grid" id="ovCards"></div>
    </section>

    <section id="pane-hardware" class="pane">
      <div class="grid" id="hwCards"></div>
    </section>

    <section id="pane-matrix" class="pane">
      <div class="grid-wide" id="matTop"></div>
      <div class="card" style="margin-bottom:1rem">
        <h3><span>Cross Coat Matrix · Agent Hierarchy (SUNDAY → STEWARD &amp; BEZEL → Specialists)</span><span class="pill info">Draft-Only · CEO: Seabass</span></h3>
        <div class="roster-grid" id="matRoster"></div>
      </div>
    </section>

    <section id="pane-memory" class="pane">
      <div class="grid-wide" id="memCards"></div>
      <div class="grid-wide">
        <div class="card">
          <h3><span>Shared Memory Notes (Tap to Read)</span><span class="pill info" id="memCount">0 notes</span></h3>
          <div class="mem-list" id="memList"></div>
        </div>
        <div class="card">
          <h3><span id="memDocTitle">Document Reader</span><span class="pill ok" id="memDocPath">INDEX.md</span></h3>
          <pre class="codebox" id="memDocBody">Select any note on the left to read its full contents from /mnt/agent-memory/shared-memory/.</pre>
        </div>
      </div>
    </section>

    <section id="pane-sonolumina" class="pane">
      <div class="frame-wrap">
        <div class="frame-bar">
          <div><b>Sonolumina · Word in Sound &amp; Light + Matrix Control Surface (#s-dash)</b></div>
          <div style="display:flex;gap:0.5rem;flex-wrap:wrap">
            <button type="button" class="btn" id="btnSonoListen">◉ Listen</button>
            <button type="button" class="btn gold" id="btnSonoDash">⊞ Open #s-dash Inside App</button>
            <a class="btn" href="/sonolumina/index.html" target="_blank" rel="noopener">Open Full Tab ↗</a>
          </div>
        </div>
        <iframe class="os-frame" id="sonoFrame" title="Sonolumina"></iframe>
      </div>
    </section>

    <section id="pane-garden" class="pane">
      <div class="frame-wrap">
        <div class="frame-bar">
          <div style="display:flex;align-items:center;gap:0.65rem;flex-wrap:wrap">
            <b>The First Garden &amp; Gates:</b>
            <select id="gateSel">
              <option value="/sonolumina/sonolumina.html">Gates 1–2 · The First Garden (Naming &amp; Rhythm)</option>
              <option value="/sonolumina/gates/sonolumina_gate3.html">Gate 3 · The Dwelling</option>
              <option value="/sonolumina/gates/sonolumina_gate4.html">Gate 4 · Sound &amp; Light</option>
              <option value="/sonolumina/gates/sonolumina_gate5.html" selected>Gate 5 · Daily Bread</option>
              <option value="/sonolumina/gates/sonolumina_gate6.html">Gate 6 · The Wider World</option>
              <option value="/sonolumina/gates/sonolumina_gate7.html">Gate 7 · Trial &amp; Exile</option>
              <option value="/sonolumina/gates/sonolumina_gate8.html">Gate 8 · Return &amp; Restoration</option>
              <option value="/sonolumina/gates/sonolumina_gate9.html">Gate 9 · Law Written on Hearts</option>
              <option value="/sonolumina/gates/sonolumina_gate10.html">Gate 10 · Home Key, New Creation</option>
              <option value="/sonolumina/gates/sonolumina_gate11_garden_growth.html">Gate 11–12 · Garden Growth (Levels 1–9: Dwelling to Home)</option>
            </select>
          </div>
          <a class="btn gold" id="gateOpen" href="/sonolumina/gates/sonolumina_gate5.html" target="_blank" rel="noopener">Open Full Screen ↗</a>
        </div>
        <iframe class="os-frame" id="gateFrame" title="First Garden Gate"></iframe>
      </div>
    </section>
  </main>

<script>
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function pillCls(v) {
  const s = String(v ?? '').toLowerCase();
  if (['active','running','online','ok','mounted','connected','ready','true'].some(k => s.includes(k))) return 'ok';
  if (['idle','standby','unknown','paused'].some(k => s.includes(k))) return 'warn';
  return 'err';
}
function fmtUp(sec) {
  const n = Number(sec);
  if (!Number.isFinite(n) || n < 0) return '—';
  const d = Math.floor(n / 86400), h = Math.floor((n % 86400) / 3600), m = Math.floor((n % 3600) / 60);
  return d > 0 ? `${d}d ${h}h ${m}m` : (h > 0 ? `${h}h ${m}m` : `${m}m`);
}

let currentPane = 'overview';
document.querySelectorAll('#osTabs button').forEach(btn => {
  btn.onclick = () => {
    currentPane = btn.dataset.pane;
    document.querySelectorAll('#osTabs button').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.pane').forEach(p => p.classList.toggle('active', p.id === 'pane-' + currentPane));
    if (currentPane === 'sonolumina') {
      const f = document.getElementById('sonoFrame');
      if (!f.getAttribute('src')) f.src = '/sonolumina/index.html#s-dash';
    } else if (currentPane === 'garden') {
      const gf = document.getElementById('gateFrame');
      if (!gf.getAttribute('src')) gf.src = document.getElementById('gateSel').value;
    }
  };
});

document.getElementById('btnSonoListen').onclick = () => {
  document.getElementById('sonoFrame').src = '/sonolumina/index.html';
};
document.getElementById('btnSonoDash').onclick = () => {
  document.getElementById('sonoFrame').src = '/sonolumina/index.html#s-dash';
};
document.getElementById('gateSel').onchange = e => {
  document.getElementById('gateFrame').src = e.target.value;
  document.getElementById('gateOpen').href = e.target.value;
};

async function openMemoryNote(path, title) {
  document.getElementById('memDocTitle').textContent = title || path;
  document.getElementById('memDocPath').textContent = path;
  document.getElementById('memDocBody').textContent = 'Loading ' + path + '…';
  try {
    const r = await fetch('/memory-doc?path=' + encodeURIComponent(path));
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || 'Failed to read');
    document.getElementById('memDocBody').textContent = j.content;
  } catch (e) {
    document.getElementById('memDocBody').textContent = 'Could not read ' + path + ': ' + e.message;
  }
}

function render(s) {
  const box = s.box || {};
  const hw = s.hardware || {};
  const cpu = hw.cpu || {};
  const gpu = hw.gpu || {};
  const osInfo = hw.os || {};
  const dev = s.devices || {};
  const net = s.network || {};
  const svc = s.services || {};
  const ag = s.agents || {};
  const sm = s.shared_memory || {};
  const mat = s.matrix || {};
  const eph = s.endpoints_health || {};
  const host = location.hostname || '127.0.0.1';

  document.getElementById('osSub').textContent =
    `${box.hostname || 'Seabass'} · ${osInfo.pretty_name || 'Linux Mint'} · Kernel ${osInfo.kernel || ''} · Updated ${new Date(s.generated_at).toLocaleTimeString()}`;

  document.getElementById('osVitals').innerHTML = `
    <span class="vital-chip">CPU <b>${esc(cpu.temp_c ?? '—')}°C</b> · Load ${esc(cpu.load_1m ?? '—')}</span>
    <span class="vital-chip">GPU <b>${esc(gpu.temp_c ?? '—')}°C</b> · ${esc(gpu.vram_used_mib ?? '—')}/${esc(gpu.vram_total_mib ?? '—')} MiB</span>
    <span class="vital-chip">RAM <b>${esc(box.ram?.used_gb ?? '—')}/${esc(box.ram?.total_gb ?? '—')} GB</b></span>
    <span class="vital-chip">1TB Mem <b>${esc(box.disk_1tb?.pct ?? '—')}</b></span>
    <span class="vital-chip">Tailscale <b>${esc(net.tailscale_ip || 'local')}</b></span>
    <span class="vital-chip">Home <b>110 Hz</b></span>
    <button class="btn" onclick="poll()" style="padding:0.2rem 0.55rem;font-size:0.74rem">↻ Refresh</button>
  `;

  // 1. Overview Cards
  const dispConn = (dev.displays || []).filter(d => d.status === 'connected');
  document.getElementById('ovCards').innerHTML = `
    <div class="card">
      <h3><span>System &amp; Hardware Pulse</span><span class="pill ok">UP ${esc(fmtUp(box.uptime_s))}</span></h3>
      <div class="stat-row">
        <div class="stat-box"><span class="lbl">CPU (6C/12T)</span><span class="val">${esc(cpu.temp_c ?? '—')}°C</span><span class="sub">Ryzen 5 5600X</span></div>
        <div class="stat-box"><span class="lbl">GPU (8GB)</span><span class="val">${esc(gpu.temp_c ?? '—')}°C · ${esc(gpu.util_pct ?? 0)}%</span><span class="sub">GTX 1070 Ti</span></div>
        <div class="stat-box"><span class="lbl">Memory</span><span class="val">${esc(box.ram?.used_gb)}/${esc(box.ram?.total_gb)} GB</span><span class="sub">${esc(box.ram?.avail_gb)} GB free</span></div>
      </div>
      <div class="kv"><span class="k">Motherboard</span><span class="v">${esc(osInfo.motherboard)}</span></div>
      <div class="kv"><span class="k">NVMe Root (WD_BLACK 500GB)</span><span class="v">${esc(box.disk_root?.used)} / ${esc(box.disk_root?.size)} (${esc(box.disk_root?.pct)}) · ${esc(hw.sensors?.nvme_temp_c ?? '—')}°C</span></div>
      <div class="kv"><span class="k">SATA 1TB Memory (WD Blue)</span><span class="v">${esc(box.disk_1tb?.used)} / ${esc(box.disk_1tb?.size)} (${esc(box.disk_1tb?.pct)})</span></div>
    </div>

    <div class="card">
      <h3><span>Connected Peripherals</span><span class="pill info">${esc(dispConn.length)} Displays · ${esc((dev.usb||[]).length)} USB</span></h3>
      ${dispConn.map(d =>
        `<div class="kv"><span class="k">Display · ${esc(d.port)}</span><span class="v"><span class="pill ok">${esc(d.monitor || 'Connected')}</span></span></div>`
      ).join('')}
      ${(dev.audio_capture || []).map(a =>
        `<div class="kv"><span class="k">Mic Input</span><span class="v">${esc(a.name)}</span></div>`
      ).join('')}
      ${(dev.usb || []).slice(0, 4).map(u =>
        `<div class="kv"><span class="k">USB ${esc(u.id)}</span><span class="v">${esc(u.name)}</span></div>`
      ).join('')}
    </div>

    <div class="card">
      <h3><span>Synod Agents &amp; Live Ports</span><span class="pill ok">LIVE</span></h3>
      ${Object.entries(ag).map(([k, v]) =>
        `<div class="kv"><span class="k">Agent · ${esc(k)}</span><span class="v"><span class="pill ${pillCls(v)}">${esc(v)}</span></span></div>`
      ).join('')}
      ${Object.entries(eph).map(([k, v]) =>
        `<div class="kv"><span class="k">Port · ${esc(k)}</span><span class="v"><span class="pill ${pillCls(v)}">${esc(v)}</span></span></div>`
      ).join('')}
    </div>

    <div class="card">
      <h3><span>AI OS Quick Launchers</span><span class="pill info">ALL IN ONE</span></h3>
      <p style="color:var(--dim);margin-top:0">Jump directly into any layer of the unified system:</p>
      <div style="display:flex;gap:0.5rem;flex-wrap:wrap">
        <button class="btn gold" onclick="document.querySelector('[data-pane=sonolumina]').click()">◉ Sonolumina &amp; #s-dash</button>
        <button class="btn" onclick="document.querySelector('[data-pane=garden]').click()">🌿 First Garden (Gates 1–11)</button>
        <button class="btn" onclick="document.querySelector('[data-pane=hardware]').click()">⚙ Full Hardware Audit</button>
        <button class="btn" onclick="document.querySelector('[data-pane=matrix]').click()">◇ Cross Coat Matrix</button>
        <button class="btn" onclick="document.querySelector('[data-pane=memory]').click()">◈ 1 TB Shared Memory</button>
        <a class="btn" href="http://${host}:3100" target="_blank" rel="noopener">◇ Paperclip Desk (:3100) ↗</a>
        <a class="btn" href="http://${host}:5678" target="_blank" rel="noopener">🔗 n8n (:5678) ↗</a>
        <a class="btn" href="http://127.0.0.1:8766" target="_blank" rel="noopener">🛡 Keeper (:8766) ↗</a>
        <a class="btn" href="/status" target="_blank">JSON /status ↗</a>
      </div>
    </div>
  `;

  // 2. Full Hardware & Devices Pane
  const fans = hw.sensors?.fans || {};
  const fanRows = Object.entries(fans).map(([k, rpm]) =>
    `<div class="kv"><span class="k">Motherboard ${esc(k)}</span><span class="v">${esc(rpm)} RPM</span></div>`
  ).join('');
  document.getElementById('hwCards').innerHTML = `
    <div class="card">
      <h3><span>Processor &amp; Thermals</span><span class="pill ok">${esc(cpu.temp_c ?? '—')}°C</span></h3>
      <div class="kv"><span class="k">CPU Model</span><span class="v">${esc(cpu.model)}</span></div>
      <div class="kv"><span class="k">Topology</span><span class="v">${esc(cpu.cores)} Cores / ${esc(cpu.threads)} Threads</span></div>
      <div class="kv"><span class="k">Max Boost Clock</span><span class="v">${esc(cpu.max_mhz)} MHz (${cpu.boost_enabled ? 'Boost ON' : 'Base Clock Mode'})</span></div>
      <div class="kv"><span class="k">Load Average (1m / 5m / 15m)</span><span class="v">${esc(cpu.load_avg)}</span></div>
      <div class="kv"><span class="k">CPU Die (Tctl / Tccd1)</span><span class="v">${esc(cpu.temp_c ?? '—')}°C / ${esc(cpu.ccd_temp_c ?? '—')}°C</span></div>
      <div class="kv"><span class="k">Wi-Fi 6 AX200 Temp</span><span class="v">${esc(hw.sensors?.wifi_temp_c ?? '—')}°C</span></div>
      ${fanRows}
    </div>

    <div class="card">
      <h3><span>NVIDIA GPU &amp; Displays</span><span class="pill ok">${esc(gpu.temp_c ?? '—')}°C · ${esc(gpu.power_w ?? '—')}W</span></h3>
      <div class="kv"><span class="k">GPU</span><span class="v">${esc(gpu.name)}</span></div>
      <div class="kv"><span class="k">NVIDIA Driver</span><span class="v">${esc(gpu.driver)} (CUDA 13.0)</span></div>
      <div class="kv"><span class="k">VRAM Usage</span><span class="v">${esc(gpu.vram_used_mib)} / ${esc(gpu.vram_total_mib)} MiB (${esc(gpu.util_pct)}% util)</span></div>
      <div class="kv"><span class="k">Power Draw</span><span class="v">${esc(gpu.power_w)} W / ${esc(gpu.power_cap_w)} W</span></div>
      ${(dev.displays || []).map(d =>
        `<div class="kv"><span class="k">Port ${esc(d.port)}</span><span class="v"><span class="pill ${d.status === 'connected' ? 'ok' : 'warn'}">${esc(d.status)}${d.monitor ? ' · ' + esc(d.monitor) : ''}</span></span></div>`
      ).join('')}
    </div>

    <div class="card">
      <h3><span>Storage Drives &amp; Memory</span><span class="pill ok">${esc(box.ram?.total_gb)} GB RAM</span></h3>
      <div class="kv"><span class="k">System RAM</span><span class="v">${esc(box.ram?.used_gb)} GB used / ${esc(box.ram?.total_gb)} GB (${esc(box.ram?.avail_gb)} GB avail)</span></div>
      <div class="kv"><span class="k">Swap</span><span class="v">${esc(box.swap?.used_gb ?? 0)} GB / ${esc(box.swap?.total_gb ?? 2)} GB</span></div>
      ${(hw.drives || []).map(d =>
        `<div class="kv"><span class="k">/dev/${esc(d.name)} · ${esc(d.model)}</span><span class="v">${esc(d.size)}${d.temp_c ? ' · ' + esc(d.temp_c) + '°C' : ''}</span></div>`
      ).join('')}
      <div class="kv"><span class="k">Root Filesystem (/)</span><span class="v">${esc(box.disk_root?.used)} / ${esc(box.disk_root?.size)} (${esc(box.disk_root?.pct)})</span></div>
      <div class="kv"><span class="k">Agent Memory (/mnt/agent-memory)</span><span class="v">${esc(box.disk_1tb?.used)} / ${esc(box.disk_1tb?.size)} (${esc(box.disk_1tb?.pct)})</span></div>
    </div>

    <div class="card">
      <h3><span>Audio Playback &amp; Capture (ALSA)</span><span class="pill info">${esc((dev.audio_playback||[]).length)} Out · ${esc((dev.audio_capture||[]).length)} In</span></h3>
      ${(dev.audio_capture || []).map(a =>
        `<div class="kv"><span class="k">🎤 Capture (Card ${esc(a.card)}.${esc(a.device)})</span><span class="v">${esc(a.name)}</span></div>`
      ).join('')}
      ${(dev.audio_playback || []).map(a =>
        `<div class="kv"><span class="k">🔊 Playback (Card ${esc(a.card)}.${esc(a.device)})</span><span class="v">${esc(a.name)}</span></div>`
      ).join('')}
    </div>

    <div class="card">
      <h3><span>Connected USB Devices</span><span class="pill ok">${esc((dev.usb||[]).length)} Active</span></h3>
      ${(dev.usb || []).map(u =>
        `<div class="kv"><span class="k">Bus ${esc(u.bus)} Dev ${esc(u.device)} (${esc(u.id)})</span><span class="v">${esc(u.name)}</span></div>`
      ).join('')}
    </div>

    <div class="card">
      <h3><span>Network &amp; Daemons</span><span class="pill ok">${esc(net.ssh)}</span></h3>
      <div class="kv"><span class="k">Tailscale IP (Tailnet)</span><span class="v">${esc(net.tailscale_ip)}</span></div>
      <div class="kv"><span class="k">LAN IP (Intel I225-V 2.5GbE)</span><span class="v">${esc(net.lan_ip)}</span></div>
      ${Object.entries(svc).filter(([k]) => k !== 'zellij_sessions').map(([k, v]) =>
        `<div class="kv"><span class="k">Service · ${esc(k)}</span><span class="v"><span class="pill ${pillCls(v)}">${esc(v)}</span></span></div>`
      ).join('')}
    </div>
  `;

  // 3. Matrix & Synod Pane
  const brains = mat.brains || {};
  document.getElementById('matTop').innerHTML = `
    <div class="card">
      <h3><span>Brain Routing &amp; Governance</span><span class="pill ok">Main: ${esc(brains.llm_provider)}</span></h3>
      <div class="kv"><span class="k">CEO &amp; Authority</span><span class="v">${esc(mat.ceo)}</span></div>
      <div class="kv"><span class="k">Execution Policy</span><span class="v">${esc(mat.mode)}</span></div>
      <div class="kv"><span class="k">Default Brain (LLM_PROVIDER)</span><span class="v">${esc(brains.llm_provider)}</span></div>
      <div class="kv"><span class="k">STEWARD Brain (xAI Grok)</span><span class="v">${esc(brains.xai_model)}</span></div>
      <div class="kv"><span class="k">BEZEL Brain (Google Gemini)</span><span class="v">${esc(brains.gemini_model)}</span></div>
      <div class="kv"><span class="k">Architect Brain (Claude)</span><span class="v">${esc(brains.claude_model)}</span></div>
      <div style="margin-top:0.8rem;display:flex;gap:0.5rem;flex-wrap:wrap">
        <a class="btn gold" href="http://${host}:3100" target="_blank" rel="noopener">Open Paperclip Agent Desk (:3100) ↗</a>
        <a class="btn" href="http://${host}:5678" target="_blank" rel="noopener">Open n8n Workflows (:5678) ↗</a>
        <a class="btn" href="http://${host}:8000" target="_blank" rel="noopener">Matrix Agent API (:8000) ↗</a>
        <a class="btn" href="http://127.0.0.1:8766" target="_blank" rel="noopener">Keeper Dashboard (:8766) ↗</a>
      </div>
    </div>

    <div class="card">
      <h3><span>Standing Orders &amp; Morning Queue</span><span class="pill info">CANON</span></h3>
      <pre class="codebox">${esc(mat.standing_job || 'No standing job file.')}</pre>
      ${mat.morning_note ? `<pre class="codebox" style="margin-top:0.6rem">${esc(mat.morning_note)}</pre>` : ''}
    </div>
  `;

  document.getElementById('matRoster').innerHTML = (mat.roster || []).map(a => `
    <div class="agent-tile" style="border-left: 3px solid ${esc(a.color || '#4f8ef7')}">
      <div class="top">
        <span class="name">${esc(a.icon || '◇')} ${esc(a.display || a.id)}</span>
        <span class="pill info">${esc(a.kind)}</span>
      </div>
      <div class="role">${esc(a.description)}</div>
      ${a.reports_to ? `<div class="role" style="margin-top:0.25rem;font-family:var(--mono)">Reports to: ${esc(a.reports_to)}</div>` : ''}
    </div>
  `).join('');

  // 4. Shared Memory Pane
  document.getElementById('memCards').innerHTML = `
    <div class="card">
      <h3><span>1 TB Shared Agent Memory</span><span class="pill ${sm.mounted ? 'ok' : 'err'}">${sm.mounted ? 'MOUNTED' : 'UNMOUNTED'}</span></h3>
      <div class="kv"><span class="k">Mount Path</span><span class="v">${esc(sm.drive)}</span></div>
      <div class="kv"><span class="k">Hardware Drive</span><span class="v">WD Blue SA510 1TB (/dev/sda1)</span></div>
      <div class="kv"><span class="k">Capacity</span><span class="v">${esc(box.disk_1tb?.used)} used / ${esc(box.disk_1tb?.size)} (${esc(box.disk_1tb?.avail)} free)</span></div>
      <div class="kv"><span class="k">Status Flag</span><span class="v">${esc(sm.flag)}</span></div>
      <div class="kv"><span class="k">Topic Folders</span><span class="v">${esc((sm.folders || []).join(', ') || '—')}</span></div>
    </div>

    <div class="card">
      <h3><span>Raw INDEX.md Overview</span><span class="pill info">${esc((sm.index_preview||[]).length)} lines</span></h3>
      <pre class="codebox" style="max-height:190px">${esc((sm.index_preview || []).join('\\n') || 'INDEX.md not loaded in current mount view.')}</pre>
    </div>
  `;

  const entries = sm.entries || [];
  document.getElementById('memCount').textContent = entries.length + ' notes';
  const memListEl = document.getElementById('memList');
  if (entries.length && !memListEl.dataset.loaded) {
    memListEl.dataset.loaded = '1';
    memListEl.innerHTML = entries.slice().reverse().map(e => `
      <button type="button" class="mem-item" data-path="${esc(e.path)}" data-title="${esc(e.title)}">
        <b>${esc(e.title)} <span style="color:var(--dim);font-family:var(--mono);font-weight:400;font-size:0.74rem">(${esc(e.path)})</span></b>
        <small>${esc(e.summary)}</small>
      </button>
    `).join('');
    memListEl.querySelectorAll('.mem-item').forEach(btn => {
      btn.onclick = () => openMemoryNote(btn.dataset.path, btn.dataset.title);
    });
  }
}

async function poll() {
  try {
    const r = await fetch('/status', { cache: 'no-store' });
    const s = await r.json();
    document.getElementById('orb').style.background = '#22c55e';
    render(s);
  } catch (e) {
    document.getElementById('orb').style.background = '#ef4444';
    document.getElementById('osSub').textContent = 'Connection error: ' + e.message;
  }
}

poll();
setInterval(poll, 15000);
</script>
</body>
</html>
"""


_latest = {}


def snapshot_loop():
    global _latest
    while True:
        try:
            if SELF_MTIME is not None:
                try:
                    cur_mtime = os.path.getmtime(SELF_PATH)
                    if cur_mtime != SELF_MTIME:
                        print("status_endpoint.py updated on disk; hot-reloading via execv", flush=True)
                        os.execv(sys.executable, [sys.executable, SELF_PATH] + sys.argv[1:])
                except Exception:
                    pass
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
        b = body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _serve_memory_doc(self, query_str):
        qs = parse_qs(query_str)
        rel = (qs.get("path") or [""])[0].strip()
        if not rel:
            self._send(400, json.dumps({"error": "missing path"}))
            return
        clean_rel = posixpath.normpath("/" + unquote(rel)).lstrip("/")
        if any(part.startswith(".") for part in clean_rel.split("/")):
            self._send(403, json.dumps({"error": "forbidden path"}))
            return
        target = (SHARED_MEM_DIR / clean_rel).resolve()
        if not str(target).startswith(str(SHARED_MEM_DIR.resolve())) or not target.is_file():
            self._send(404, json.dumps({"error": f"note not found: {clean_rel}"}))
            return
        try:
            txt = target.read_text(errors="replace")[:100_000]
            self._send(200, json.dumps({"path": clean_rel, "content": txt}))
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

    def _serve_sonolumina_static(self, rel_path):
        clean_rel = posixpath.normpath("/" + unquote(rel_path)).lstrip("/")
        if not clean_rel or clean_rel == ".":
            clean_rel = "index.html"
        # Serve the completed Levels 1-9 Gate 11 read-only if requested
        if clean_rel == "gates/sonolumina_gate11_garden_growth.html":
            loop_gate11 = (SONOLUMINA_LOOP_DIR / clean_rel).resolve()
            if str(loop_gate11).startswith(str(SONOLUMINA_LOOP_DIR)) and loop_gate11.is_file():
                try:
                    self._send(200, loop_gate11.read_bytes(), "text/html; charset=utf-8")
                    return
                except Exception:
                    pass
        target = (SONOLUMINA_DIR / clean_rel).resolve()
        if not str(target).startswith(str(SONOLUMINA_DIR)) or not target.is_file():
            self._send(404, json.dumps({"error": "file not found"}))
            return
        ctype, _ = mimetypes.guess_type(str(target))
        if not ctype:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        try:
            data = target.read_bytes()
            self._send(200, data, ctype)
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

    def do_GET(self):
        parsed = urlparse(self.path)
        p = parsed.path
        if p == "/status":
            self._send(200, json.dumps(build(), indent=2))
        elif p == "/health":
            self._send(
                200, json.dumps({"ok": True, "version": "v3.1", "uptime_s": int(time.time() - STARTED)})
            )
        elif p == "/memory-doc":
            self._serve_memory_doc(parsed.query)
        elif p == "/" or p == "/index.html":
            self._send(200, PORTAL_HTML, "text/html; charset=utf-8")
        elif p == "/sonolumina" or p == "/sonolumina/":
            self._serve_sonolumina_static("index.html")
        elif p.startswith("/sonolumina/"):
            self._serve_sonolumina_static(p[len("/sonolumina/"):])
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, fmt, *a):
        print("%s %s" % (self.address_string(), fmt % a), flush=True)


def start_loopback_listener(port):
    try:
        lo_srv = ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=lo_srv.serve_forever, daemon=True).start()
        print(f"serving loopback on http://127.0.0.1:{port}", flush=True)
    except OSError as e:
        print(f"loopback bind 127.0.0.1:{port} skipped ({e})", file=sys.stderr, flush=True)


if __name__ == "__main__":
    threading.Thread(target=snapshot_loop, daemon=True).start()
    start_loopback_listener(PORT)
    # LAW: tailnet-only (plus 127.0.0.1 loopback). No 0.0.0.0 fallback; retry until Tailscale IP exists.
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
        if bind_host == "127.0.0.1":
            while True:
                time.sleep(3600)
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
    print(f"serving tailnet on http://{bind_host}:{PORT}", flush=True)
    srv.serve_forever()
