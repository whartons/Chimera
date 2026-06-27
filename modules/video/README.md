# `video` — brand-aware image-to-video with native synchronized audio (LTX-2.3)

![A short looping clip of a sci-fi utility robot with subtle idle motion](../../docs/images/chimera-sample-video.gif)

*LTX-2.3 image-to-video — `chimera video --from-image robot.png`. Brand-neutral sample (silent GIF; the workflow also emits synced audio).*

A **tested, importable** LTX-2.3 22B image-to-video workflow that generates
**video and synchronized audio in a single ComfyUI pass** — no separate
audio-generation step. Built from the live ComfyUI node schemas, run end-to-end
on an RTX 5090 (768×512, 97 frames @ 25 fps, 48 kHz PCM audio).

## Files
- [`workflow.template.json`](workflow.template.json) — the ComfyUI **API-format**
  workflow (drop-in for `POST /prompt` or any MCP `enqueue_workflow` tool). A copy
  also lives in
  [`../../workflows/templates/brand-video-i2v.json`](../../workflows/templates/brand-video-i2v.json).
- [`models.md`](models.md) — the model files you need + where to get them.

## Use it — unified CLI

```
python scripts/generate.py video \
  --brand example-brand \
  --subject "<cinematic action + the sounds you want>" \
  --from-image rover.png \
  [--watermark] \
  [--length 97] \
  [--fps 25] \
  [--no-audio] \
  --comfy-output-dir "<ComfyUI output dir>"
```

- `--from-image` is a filename inside the brand's `products/` or `references/`
  folder (e.g. `products/rover.png`). The filler resolves it relative to the brand
  directory.
- Output routes to `brands/<brand>/outputs/video/<brand>_i2v_<seed>.mp4` with a
  reproducibility `.json` sidecar alongside it. If the file already exists it is
  overwritten (idempotent re-render).
- `--no-audio` skips the audio-generation path; all other flags remain the same.
- `--watermark` composites the brand logo over the final decoded video frames
  entirely in-graph, after the VAE decode — the synced audio track is never
  touched.

The filler reads the active brand's `brand.yaml` `video:` block for defaults:

```yaml
video:
  model: ltx-2.3-22b-dev-nvfp4      # checkpoint name (no extension needed)
  lora: ltx-2.3-22b-distilled-lora-384-1.1   # distilled LoRA
  width: 768
  height: 512
  length: 97                          # frames
  fps: 25
  audio: true
```

Override any key on the CLI; the CLI flag always wins over `brand.yaml`.

## How it works

### One-pass audio-video

LTX-2.3 natively generates **both modalities at once** using the
`LTXAVTextEncoderLoader` (Gemma-3 12B) and `MultimodalGuider` nodes from the
`ComfyUI-LTXVideo` pack. The guider applies **separate CFG scales** to the two
modalities (VIDEO `3.0` / AUDIO `7.0` in the template) so video sharpness can
be tuned independently without desyncing the audio. The output is a single MP4
container with an embedded 48 kHz PCM audio stream.

### Prompting tip — describe the sound

LTX-2.3 **only generates the audio you describe in the prompt**. Put the desired
sounds explicitly in the subject text; silent or non-descript prompts produce
silence or faint ambient noise:

```
# good: names the motion AND the sound
"a rover rolling over gravel, crunching rocks, mechanical servo whirr"

# bad: describes only the visual
"a rover rolling over gravel"
```

The filler automatically appends a brand-default negative prompt plus
**anti-frozen / anti-silence** terms (`static, no motion, muted, silent`) to help
the sampler avoid degenerate outputs.

### Prompting tip — what i2v motion is realistic (field-tested)

Image-to-video is strongest at **ambient / energy / atmospheric** motion layered over the
source still, and weak at **inventing articulated or mechanical** motion that isn't already
implied by the image. From production use (e.g. a logo/crest stinger):

```
# good: energy motion over a rigid subject — the emblem stays fixed, the ENERGY moves
"a metal emblem holding still, glowing embers drifting up, light flares pulsing, slow camera push-in"

# unreliable: asking the still to mechanically articulate
"the robot walks forward and turns its head"   # limbs/gears it can't see won't move convincingly
```

- **Reliable from one still:** glow/flare pulses, drifting particles/embers/smoke, shimmer,
  parallax, subtle drift, and camera moves (push-in, orbit, pan).
- **Unreliable from one still:** walking/articulated limbs, turning gears, parts assembling or
  transforming, anything requiring geometry the single frame doesn't contain.
- For genuine mechanical motion, drive it from a **video/animation source** (or a keyframed
  3D turntable — see [`../threed/`](../threed/) + [`../blender/`](../blender/)) rather than
  expecting i2v to author it.

### VRAM

The 22B nvfp4 model requires roughly the full 32 GB card. The CLI defaults
`--free-before ON` for the `video` modality, which calls `clear_vram` via the
MCP bridge before enqueuing — this unloads any resident image or audio models
first. Per-modality `--timeout` defaults to `3600 s` (video generation is slow).

## Local-only & security

The workflow uses **`LTXAVTextEncoderLoader`** (the in-graph Gemma loader from
the `ComfyUI-LTXVideo` pack). It does **not** use the pack's cloud
`GemmaAPITextEncode` node, which sends text to an external endpoint. Never swap
in that node.

The `ComfyUI-LTXVideo` pack also ships a prompt-enhancer node that sets
`trust_remote_code=True` when loading an enhancer model — **that node is not
used here**. Avoid it unless you have audited the model it loads.

The pack itself was security-scanned before adoption (same standard applied to
the MCP bridge). Verdict: **safe for local use** with the above two nodes
excluded. Re-scan on every pack update before advancing the pin.

## Why LTX-2.3 needs this exact graph (the gotchas)

- The checkpoint loads via **`CheckpointLoaderSimple`** (or the pack's
  `LTXVCheckpointLoader`) — *not* a split UNET+VAE loader.
- The text encoder is loaded separately via **`LTXAVTextEncoderLoader`**
  (Gemma-3 12B, local) — not a CLIP loader.
- Audio generation requires the **`MultimodalGuider`** node; the standard
  `KSampler` path cannot drive the audio branch.
- Use the pack's **normalizing sampler** (`LTXVNormalisedScheduler` /
  `LTXVSampler`) — standard Euler/DPM++ schedulers do not handle the
  LTX-2.3 latent space correctly.
- **LTX-2 LoRAs are incompatible.** LoRAs trained on LTX-2 (19B) will not
  work with LTX-2.3 (22B). Source or retrain LTX-2.3-native LoRAs.

## Watermark

`--watermark` composites the brand logo (the `logo.default` PNG under
`brands/<brand>/logos/`) over the decoded video frames using an in-graph
composite node placed **after** the VAE decode and **before** the video-encode step. The audio path is upstream
of this node and is unaffected — the composited output carries the original
synced audio without re-encoding the audio stream.

## Upscale (`--upscale`)

`--upscale` runs a **2× LTX spatial latent upscaler** before the VAE decode:

```
python scripts/generate.py video --brand example-brand \
  --subject "..." --from-image rover.png --upscale \
  [--upscale-model ltx-2.3-spatial-upscaler-x2-1.1.safetensors] \
  --comfy-output-dir "<ComfyUI output dir>"
```

- It splices an `LTXVLatentUpsampler` (fed by a `LatentUpscaleModelLoader`)
  between the separated video latent and `brand:decode`, doubling the spatial
  resolution **in latent space**. Because it works on the latent — not on
  decoded frames — the upscale is **temporally coherent** (no per-frame
  flicker), unlike a per-frame ESRGAN image upscaler.
- Default model: **`ltx-2.3-spatial-upscaler-x2-1.1.safetensors`**, installed in
  `ComfyUI/models/latent_upscale_models/`. Override with `--upscale-model` (the
  file must live in that folder). Use the `x2-1.1` file — its version is paired
  with the distilled LoRA.
- **VRAM / time:** the upsampler decodes and re-encodes through the VAE, and the
  2× decode at the end is heavier than the base-resolution decode. It fits on the
  32 GB card but adds noticeable time — budget extra minutes per render.
- If `--watermark` is also on, the logo composites over the **2× frames** (the
  filler doubles the watermark canvas geometry so the logo still lands in the
  correct corner). The upscale is latent-space and precedes the pixel-space
  watermark, so the order is: latent upscale → decode → watermark → encode.
  Because the upscale happens in latent space (before decode) while the watermark
  composites in pixel space (after), an opt-in watermark on an upscaled clip lands
  in the correct corner but renders at roughly **half its relative size** versus a
  non-upscaled clip — the logo is placed at its fixed pixel size and is not
  enlarged along with the frame.

## Performance (RTX 5090 / cu130 / SageAttention)

- `ltx-2.3-22b-dev-nvfp4` @ 768×512 / 97 frames / 25 fps: generation time
  varies with prompt complexity; expect several minutes for a cold start.
- First render of a session is slower (model load + one-time JIT). Keep the
  model resident for faster iteration.

## VRAM

~28–32 GB for the nvfp4 checkpoint. `--free-before` (default ON) clears other
resident models before queuing. See [`models.md`](models.md) for quantized and
distilled options.
