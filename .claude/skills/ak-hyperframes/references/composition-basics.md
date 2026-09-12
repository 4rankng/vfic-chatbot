# Composition basics

A HyperFrames composition is a plain HTML file. Timing and sizing are
expressed as `data-*` attributes on the composition root and its timed child
elements — there is no separate scene-graph or timeline file to keep in sync.

## Attribute contract

| Attribute | Applies to | Meaning |
| --- | --- | --- |
| `data-composition-id` | Root element (once per file) | Stable identifier the CLI uses to address this composition. Required. |
| `data-width` | Root element | Output width in pixels. |
| `data-height` | Root element | Output height in pixels. |
| `data-start` | Any timed child element | Start time in seconds relative to composition start. |
| `data-duration` | Any timed child element (optional) | How long the element stays visible/active, in seconds. Omit for "until composition end". |
| `data-track-index` | Any timed child element (optional) | Timeline track number; controls z-ordering when elements overlap in time. |
| `class="clip"` | Any timed child element | Required — this is what tells the HyperFrames runtime to manage the element's visibility lifecycle from `data-start`/`data-duration`. An element without it is not treated as a timed clip. |

`lint` fails the composition if `data-composition-id` is missing/duplicated,
if any `data-start`/`data-duration` value doesn't parse, or if a timed
element is missing `class="clip"`.

## Vertical 1080×1920 example

```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      body { margin: 0; background: #0b0b0f; }
      .headline {
        position: absolute;
        left: 64px;
        right: 64px;
        top: 40%;
        font: 700 84px/1.1 system-ui, sans-serif;
        color: #ffffff;
      }
      .cta {
        position: absolute;
        left: 64px;
        bottom: 160px;
        font: 500 40px system-ui, sans-serif;
        color: #7cf29c;
      }
    </style>
  </head>
  <body>
    <main
      data-composition-id="product-launch-vertical"
      data-width="1080"
      data-height="1920"
    >
      <section class="clip headline" data-start="0" data-duration="2.5" data-track-index="0">
        <h1>Introducing AgentKit</h1>
      </section>
      <section class="clip headline" data-start="2.5" data-duration="3" data-track-index="0">
        <h1>Controlled agent engineering,<br />shipped fast.</h1>
      </section>
      <section class="clip cta" data-start="5.5" data-track-index="0">
        <p>Learn more at agentkit.best</p>
      </section>
    </main>
  </body>
</html>
```

The runtime handles show/hide timing for any element carrying `class="clip"`
— don't hand-roll opacity/visibility CSS keyed off `data-start`, the runtime
already does that. This composition is 5.5s+ long (the last clip has no
`data-duration`, so it holds through composition end). All three clips sit on
the same `data-track-index` because none of them overlap in time; give
overlapping clips distinct track indices so the runtime knows which one
paints on top. See [references/render-workflow.md](render-workflow.md) for
the `init` command and `--resolution portrait` flag that scaffold this
1080×1920 canvas size.
