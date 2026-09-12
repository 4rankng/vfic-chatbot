# Environment and dependencies

<!-- verified against hyperframes @ 0.7.99 on 2026-08-07 -->

## Node.js 22+

`hyperframes` requires Node.js 22 or newer.

```bash
node --version
# Node 22+? Good. Otherwise:
nvm install 22
nvm use 22
```

## FFmpeg

Required on `PATH` for the local render pipeline (Chromium capture → FFmpeg
encode).

```bash
# macOS
brew install ffmpeg

# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y ffmpeg

# verify
ffmpeg -version
```

## Verify both at once

```bash
node scripts/verify-prereqs.mjs
```

Prints `READY` and exits 0 when both checks pass; otherwise exits non-zero
with the specific remediation command for whichever check failed. Add
`--json` for machine-readable output.

## Optional: HeyGen cloud/lambda API key

Local rendering (Chromium + FFmpeg on this machine) does not require an API
key. Set `HEYGEN_API_KEY` only when using the separate `hyperframes cloud
render` command (see
[references/render-workflow.md](render-workflow.md#optional-remotecloud-render)):

```bash
export HEYGEN_API_KEY="hg_..."
```

Store it via the project's existing secret-management convention (e.g.
`.agentkit/.env`, `~/.agentkit/.env`) rather than committing it. Never print
or log the key value.
