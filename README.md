# matrix-control-surface
Matrix Control Surface — status endpoint spec, dashboard tab foundation, and shared-memory integration for the Cross Coat Matrix × Sonolumina project. Canon keeper: Grok. Built on seabasskrahn Linux box (private Tailscale tailnet).

The status endpoint does not reload itself. After changing `service/`, run `python3 -m unittest discover -s service -p 'test_*.py'`, then `systemctl --user restart matrix-status`.
