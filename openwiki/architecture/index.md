# Files

- [Blue/green deployment topology and release gate](deployment.md) - How the production stack ships via manual blue/green cutover, why Caddy never routes to a broken image, and what the local release-check gate enforces before any image is pushed.
- [System overview and component topology](system-overview.md) - How the synchronous answer path, background workers, edge, and realtime push fit together — and which subsystem owns each step of an inbound Zalo message.
