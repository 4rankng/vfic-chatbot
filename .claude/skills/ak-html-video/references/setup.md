## Setup

Prefer a published `html-video` binary if one exists in the user's environment. If it does not, use a source checkout; do not vendor the upstream engine into the user's project or kit.

As of the upstream `main` metadata checked when this skill was authored, `html-video` declares Node `>=20`, pnpm `>=9`, and package manager `pnpm@9.15.0`. If upstream `package.json` differs, follow upstream.

```bash
# Source checkout path is a convention, not a requirement.
git clone https://github.com/nexu-io/html-video "$HOME/html-video"
cd "$HOME/html-video"
corepack enable
corepack prepare pnpm@9.15.0 --activate
pnpm install
pnpm -r build

# If source-checkout rendering reports a missing Playwright browser:
pnpm --filter @html-video/adapter-hyperframes exec playwright install chromium
```

Use this helper in shell sessions so commands work with either a global binary or a source checkout:

```bash
html_video() {
  if command -v html-video >/dev/null 2>&1; then
    html-video "$@"
    return
  fi

  local home="${HTML_VIDEO_HOME:-$HOME/html-video}"
  if [ -f "$home/packages/cli/dist/bin.js" ]; then
    node "$home/packages/cli/dist/bin.js" "$@"
    return
  fi

  echo "html-video CLI not found. Install it or set HTML_VIDEO_HOME to the source checkout." >&2
  return 127
}
```

Always start with diagnostics:

```bash
html_video doctor
html_video list-engines
```

The CLI defaults to JSON output. Add `--no-color` for logs and `--cwd <path>` when rendering projects outside the current directory.
