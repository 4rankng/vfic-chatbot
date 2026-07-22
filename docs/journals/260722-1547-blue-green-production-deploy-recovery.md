---
title: Blue-green production deploy recovery
date: 2026-07-22
session: blue-green-production-deploy-recovery
---

# Blue-green production deploy recovery

## Context

We cut prod over to the new backend image with blue/green deploys and verified the live edge path. At the time of the deploy, production was serving `web-green` on `ACTIVE_COLOR=green` with image `franknguyenvd/vfic-backend:c5f4b2cd`, while local HEAD had already moved on to `4083e3d9`. The edge `/health` check was returning `200`; `/api/v1/health` returning `404` was just a bogus path, not a broken service.

## What Happened

The deploy exposed two script bugs that had to be worked around live. First, `bg_deploy.sh` and `flip_caddy.sh` still behaved as if the frontend belonged to the backend cutover path, so the deploy flow tried to pull `frontend:<tag>` even though the backend blue/green should only move `web-*` plus workers. Second, the Caddy flip was not actually taking effect through reload alone. The bind-mounted Caddyfile was being replaced in a way that changed the host inode, so the running Caddy container kept reading stale config until it was restarted.

The deploy-status quote bug was already fixed, which matters because we need the status command to stay shell-safe while we clean up the rest of this mess.

## The Brutal Truth

This was annoying in the exact way production failures always are: the deploy looked clean until it hit the parts nobody had exercised hard enough. The live workaround got prod across the line, but it also proved the scripts were lying to us about what they were actually doing. That wastes time, burns attention, and leaves too much luck in the release path.

## Technical Details

- Live prod: `ACTIVE_COLOR=green`
- Live image: `franknguyenvd/vfic-backend:c5f4b2cd`
- Local HEAD: `4083e3d9`
- Real health endpoint: `/health -> 200`
- Nonexistent probe: `/api/v1/health -> 404`
- Failure mode 1: backend cutover attempted `frontend:<tag>` pull
- Failure mode 2: `caddy reload` did not swap upstream because the bind-mounted Caddyfile inode changed

## What We Tried

- We completed the blue/green cutover manually and verified the active color served traffic.
- We confirmed the backend script bug by tracing the pull step and seeing the frontend image in the wrong place.
- We confirmed the Caddy issue by discovering reload was not enough and that only a restart forced the new upstream to be read.
- We fixed the status command quoting so the deploy diagnostics stop tripping over shell syntax.

## Root Cause Analysis

The root cause was bad deployment script ownership. The backend deploy path had drifted into frontend concerns, and the Caddy renderer was written as if file replacement on a bind mount were harmless. It is not. We shipped a cutover flow that had not been tested against the exact runtime conditions it depends on: separate images, bind-mounted config, and live reload semantics.

## Lessons Learned

- Backend blue/green must not touch the frontend image.
- A bind-mounted config file needs inode-preserving content replacement if the running process expects reload to pick up changes.
- “It reloaded” is not the same as “it used the new upstream.”
- Deploy scripts need explicit regression tests for the exact remote behavior, not just dry-run shape checks.

## Next Steps

- Keep the deployment script fixes in the tree and let `make deploy` exercise the corrected backend-only cutover path.
- Preserve the Caddyfile inode behavior in `flip_caddy.sh` so reload works without a restart.
- Leave the status quoting fix in place and add coverage if that path changes again.
- Owner: whoever touches deploy automation next. Timeline: before the next production cutover, not after another live workaround.
