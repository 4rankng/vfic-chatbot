# HeyGen HyperFrames agent skills

<!-- verified: 2026-08-08, against hyperframes@0.7.99's `skills` command output -->

HeyGen ships a family of specialized agent skills alongside the
[`hyperframes`](https://github.com/heygen-com/hyperframes) CLI, each covering
one facet of HTML-first video composition. `ak:hyperframes` does not copy or
re-implement any of them — it wraps the CLI itself and points here so the
agent can install the deeper skill set on demand.

Install the full set with the CLI's own `skills` command (not a separate
`skills` package — there is no `skills add` subcommand):

```bash
npx -y hyperframes@0.7.99 skills
```

Run non-interactively it auto-detects the coding agent (Claude Code,
Universal, etc.) and clones+installs every published skill under
`~/.agents/skills/`. `hyperframes skills check` reports whether installed
skills are current; `hyperframes skills update` updates them in place.

As of `0.7.99` this installs 25 skills:

| Group | Skills |
| --- | --- |
| Core | `hyperframes`, `hyperframes-animation`, `hyperframes-cli`, `hyperframes-core`, `hyperframes-creative`, `hyperframes-keyframes`, `hyperframes-registry`, `media-use` |
| General | `captions-overlay`, `changelog-video`, `cut-the-curve`, `embedded-captions`, `faceless-explainer`, `figma`, `general-video`, `motion-doctrine`, `motion-graphics`, `music-to-video`, `oversized-cursor`, `pr-to-video`, `product-launch-video`, `remotion-to-hyperframes`, `seam-craft`, `slideshow`, `talking-head-recut` |

This list is upstream's own to change; re-run the install command and diff
`~/.agents/skills/` before treating names or counts here as current — update
the `<!-- verified: ... -->` marker above when you do.

Once installed, each skill's `SKILL.md` auto-discovers in Claude Code and
other supported agents — consult them directly for composition-level
technique rather than duplicating their content here.
