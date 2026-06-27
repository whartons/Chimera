# Field recipes — creator & community assets

Brand-neutral, production-tested recipes for common creator deliverables (live-streaming and
small-shop work — the audiences in the [README](../../README.md)). They build on this module's
Z-Image / FLUX.2 workflows plus a little host-side compositing. Swap in your own subject, palette,
and logo — the brand *data* stays private; only the **technique** lives here.

## Platform emotes / stickers

Emotes render tiny (generate large, downscale to 112 / 56 / 28 px) and must read on **both** light-
and dark-mode chat backgrounds. What worked, in priority order:

- **Bold, simple subject.** One bust / face / icon with chunky forms and high contrast — fine detail
  vanishes at 28 px. Generate at 1024² and downscale last.
- **Cut out the background, then add a dark outline.** Generate on a flat, contrasting background,
  flood-fill / key it to transparency, then add a 2–4 px **dark contour**. This is the single biggest
  legibility win: without it, dark linework disappears on dark themes and light edges disappear on
  light themes. The outline makes one asset work on every background.
- **One coherent set.** Lock seed + style across the set so every emote shares a look; vary only the
  expression/pose in the prompt.
- **Export sizes:** 112 / 56 / 28 px PNG with transparency (Twitch's three sizes; adjust per platform).

### Animated emotes

- **Export GIF, not APNG.** Most platforms (e.g. Twitch) accept animated **GIF** and reject APNG —
  encode to GIF.
- **Real motion needs matched keyframes.** A single still + a generic "animate" pass produces mushy
  morphing. Instead generate a few **matched-seed keyframes** (same seed + style, prompt only the pose
  change — e.g. arm-down → arm-up), so the frames share identity, then assemble the GIF from them. That
  yields true articulated motion (a wave, a bounce) instead of a melt.
- Keep the frame count low, loop cleanly, and keep the action punchy — the canvas is tiny.

## Tiered badge / loyalty sets

Sub / bit / loyalty badges are even smaller (72 / 36 / 18 px) and sit on busy UI.

- **One metaphor, escalating.** Pick a progression (a rank / tool / material ladder) and render each
  tier as the same object class growing richer. Lock the framing across tiers.
- **Metal-relief + dark outline survives downscaling.** A bright, bold, slightly-embossed look with a
  dark contour reads at 18 px far better than flat or dark art.
- **Go brighter than your reference.** Badges sit over busy chrome; dark, subtle designs vanish — err
  bolder and brighter than feels right on your monitor.
- **Export sizes:** 72 / 36 / 18 px PNG with transparency.

## Logo / crest stingers (animated)

For an animated logo sting, see the [`video`](../video/) module's i2v motion note: layer **energy**
motion (glow, embers, flares, a slow push-in) over a **rigid** emblem — image-to-video reliably
animates atmosphere around a fixed mark, but won't mechanically transform the mark itself.

## Notes

- Host-side steps (background cutout, dark outline, GIF assembly) are small PIL / ImageMagick passes.
  Keep your source PNGs and **re-export the sized variants on demand** rather than committing the
  derived files.
- These are techniques, not assets: no brand logos, palettes, or names belong in a tracked file.
