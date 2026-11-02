# Remove the status endpoint's auto-reload

**Goal:** a save to `service/status_endpoint.py`, or a `git checkout`, must not change or stop the running feed. New code goes live only on a deliberate `systemctl --user restart matrix-status`.

**Why:** `snapshot_loop` re-execs itself within 30s of any file change, so a broken save by any agent takes down the feed every agent reports to, and a checkout silently swaps the live service. Found in the Stage 7 review.

**Spec:** the "LEFT OPEN (1)" item in shared memory `reference/2026-11-01-status-feed-truth.md`.

## Task 1: Remove the reload

- [ ] Write `service/test_no_reload.py`: load a copy of the module, change the copy's mtime, run one `snapshot_loop` pass, assert `os.execv` was not called and the snapshot was written.
- [ ] Run `python3 -m unittest discover -s service -p 'test_*.py'`. Expected: FAIL, execv called.
- [ ] Delete `SELF_PATH`, `SELF_MTIME` and the reload block.
- [ ] Run the suite. Expected: 15/15 pass.
- [ ] Say in `README.md` how to deploy a change.
- [ ] Commit.
