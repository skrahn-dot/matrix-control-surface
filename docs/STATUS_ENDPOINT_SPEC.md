# STATUS ENDPOINT SPEC — Matrix Control Surface
**Date:** October 18, 2026
**Author:** Grok (canon keeper)
**Status:** SPEC READY — Claude Code builds on the Linux box

## Purpose
A tiny HTTP service on the Linux box serving one JSON file: live Matrix status.
The Sonolumina web app's Dashboard tab fetches it over Tailscale.

## Architecture
- status_endpoint.py on the box, bound to the box's Tailscale IP (`tailscale ip -4`, port `:8787`)
- GET /status returns JSON (box health, services, agents, relay, shared memory)
- GET / writes a one-line HTML pointer page
- Snapshot also written to /home/oem/matrix-status.json every 30s (atomic)
- No auth on v1: tailnet-only, read-only, no secrets in JSON

## JSON schema (key fields)
- generated_at, box (uptime, RAM, disk root + 1TB), network (tailscale IP, LAN IP, SSH), services (ssh/zellij/docker/claude_code/grokbot), agents (claude_code/grokbot/merlin/gemini_spark status), shared_memory (1TB drive role + READ-ONLY SEARCH PENDING flag), sonolumina (repo pointers, home note 110 Hz), relay (last entry, open tasks, needs Seabass), phase

## Implementation notes for Claude Code
- Python 3 stdlib only (http.server, json, subprocess, time, datetime)
- Bind to the Tailscale IP (`STATUS_BIND` or `tailscale ip -4`) on `:8787`; tailnet-only (no `0.0.0.0` fallback)
- Metrics via: /proc/uptime, free -g, df -BG, tailscale ip -4, systemctl is-active, zellij list-sessions
- Run inside zellij session named 'status'
- systemd user service is v2

## Sonolumina dashboard tab
- Nav button + section id s-dash matching existing setTab pattern
- fetch STATUS_URL, render cards, poll every 30s while tab visible
- Dark theme, mono numbers, green/amber/red status colors

## Rollout
1. Claude Code builds on box, tests with curl from the box
2. Seabass tests from phone off home Wi-Fi
3. Dashboard tab renders on the phone
4. Merlin logs to AI Matrix Relay
5. Seabass confirms render

## Not this
- Not the Keeper dashboard (localhost-only, approval-gated)
- Not public; not the cinematic Site Alpha layer (Phase 2)
- Not a Relay replacement

## Open flags for Seabass
- [ ] Port 8787 OK?
- [ ] 1 TB mount point name (/mnt/matrix-memory proposed)
- [ ] /health endpoint for uptime monitors?
- [ ] v2 systemd auto-start
