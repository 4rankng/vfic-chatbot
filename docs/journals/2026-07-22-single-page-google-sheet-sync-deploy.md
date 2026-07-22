# Single-page Google Sheet sync deployment

**Date:** 2026-07-22  
**Production:** `bot.tingting.vip`

## Outcome

The single-page Google Sheet sync shipped successfully. Production runs backend
and worker artifact `df250708` on the green color and frontend artifact
`2bcca717`. The public health endpoint and UI return HTTP 200, and every
production container is healthy.

## Deployment incident

The blue/green backend rollout, migration, health gate, and real chatbot smoke
test completed successfully. During the same command, another local commit
changed `HEAD` after the versioned images had been built. The frontend restart
therefore requested that newer commit tag, which had no published frontend
image, and failed after the backend traffic flip.

Production impact was limited to the new frontend not restarting on that first
attempt. The previous frontend stayed available, while the new backend and all
workers were already healthy.

## Recovery

The frontend restart was rerun with the immutable image tag that had actually
been built (`df250708`). A final audit then removed the remaining legacy
`sheet_gid: 0` submission path, required the explicit `gid` from the pasted URL
for every Google Sheet import, passed the full release gate again, and published
frontend artifact `2bcca717`.

## Learning

Composite deploy targets should capture the release tag once at the start and
pass it explicitly to every nested build and restart step. Recomputing a tag
from a mutable working copy between steps can mix artifacts when another local
process commits concurrently. Immutable tags and explicit post-deploy container
inspection made the failure safe to diagnose and recover.
