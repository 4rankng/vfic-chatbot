# Render workflow

This reference owns the reproducibility pin `hyperframes@0.7.99` (verified as of
2026-08-07, verified via `npm view hyperframes version`). Update this pin —
and the matching pin in `SKILL.md` — in one commit when bumping.

## 1. Init

Scaffold a new composition project from a named preset:

```bash
npx -y hyperframes@0.7.99 init my-composition --resolution portrait
```

`--resolution` accepts named presets: `landscape` (1920×1080), `portrait`
(1080×1920), `landscape-4k` (3840×2160), `portrait-4k` (2160×3840), `square`
(1080×1080), `square-4k` (2160×2160) — plus aliases `1080p`, `4k`, `uhd`,
`1080p-square`, `square-1080p`, `4k-square`. Without `--resolution`, `init`
keeps the chosen template's own dimensions (typically 1920×1080). Run
`npx -y hyperframes@0.7.99 init --help` to confirm current flags before
relying on this list — it may lag a fast-moving upstream CLI surface.

## 2. Edit HTML

Edit the generated composition HTML directly. See
[references/composition-basics.md](composition-basics.md) for the
`data-composition-id` / `data-start` / `data-width` / `data-height` contract.
No build step is required — HyperFrames renders the HTML as-is.

## 3. Preview

Serve the composition locally with a scrubbable timeline:

```bash
npx -y hyperframes@0.7.99 preview my-composition
```

Open the printed local URL. Use the timeline scrubber to check that
`data-start`/`data-duration` values produce the intended sequencing before
spending render time.

## 4. Lint

Validate the composition's `data-*` attributes and catch malformed timing
before rendering:

```bash
npx -y hyperframes@0.7.99 lint my-composition
```

Fix every reported error before proceeding — a composition that lints clean
rarely fails at render time; one that doesn't almost always does.

## 5. Render

Render the composition to MP4:

```bash
npx -y hyperframes@0.7.99 render my-composition \
  --output ./assets/videos/my-composition.mp4
```

Verify the output the same way as any other rendered video artifact:

```bash
ffprobe -v error -show_streams -show_format -of json ./assets/videos/my-composition.mp4
```

The render is not proven complete until `ffprobe` reports a nonzero duration
and the expected width/height.

## Optional: remote/cloud render

If `HEYGEN_API_KEY` is set (see
[references/env-and-deps.md](env-and-deps.md)), cloud rendering is a
**separate top-level command**, not a `render` flag — `render` has no
`--engine`/cloud option:

```bash
npx -y hyperframes@0.7.99 cloud render my-composition \
  --output ./assets/videos/my-composition.mp4
```

`cloud list` / `cloud get` / `cloud delete` manage prior cloud renders. Run
`npx -y hyperframes@0.7.99 cloud render --help` before relying on exact flag
names — pinned docs here may lag a fast-moving upstream CLI surface. For
distributed self-hosted rendering (not HeyGen's managed cloud), see the
separate `lambda` (AWS) and `cloudrun` (GCP) top-level commands.
