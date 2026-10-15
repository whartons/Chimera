# `video` — brand-aware image-to-video (Wan 2.2 default · camera moves · LTX-2.3 with synced audio)

![A short clip of a sci-fi utility robot waving hello](../../docs/images/chimera-sample-video.gif)

*Wan 2.2 image-to-video, the default (`--quality fast`, about 30 s on an RTX 5090):
`chimera video --from-image robot.png --subject "the robot raises its right hand and waves hello…"`.
Brand-neutral sample.*

Two families, both run end-to-end on an RTX 5090:

| | Wan 2.2 14B *(default)* | LTX-2.3 22B (`--model ltx23`) |
|---|---|---|
| Camera | holds steady (≤ 0.8% zoom in the 2026-10 review); **`--camera`** gives a locked shot or a controlled pan / zoom / rotation | adds its own push-in or pan; a "parked" car drove off |
| Subject | keeps a face's identity | drifted a face's identity |
| Audio | silent: add sound with `audio --mode foley --from-video` | **synced audio in the same pass** |
| Time per clip (RTX 5090) | ~35 s (`fast`, 768×512, 5 s) · ~3 min (`full` / `--camera`) | ~50–80 s (3.9 s, with audio) |

Wan became the default after the 2026-10 model review measured camera drift on three shots (chained
feature tracking frame to frame). Use LTX when you want sound baked in.

## Files
- [`workflow.wan22-i2v.template.json`](workflow.wan22-i2v.template.json) — Wan 2.2 image-to-video (high/low
  experts with the lightx2v 4-step LoRAs). Copy in
  [`../../workflows/templates/brand-video-wan22-i2v.json`](../../workflows/templates/brand-video-wan22-i2v.json).
- [`workflow.wan22-camera.template.json`](workflow.wan22-camera.template.json) — Wan 2.2 Fun Camera
  (`--camera`). Copy in
  [`../../workflows/templates/brand-video-wan22-camera.json`](../../workflows/templates/brand-video-wan22-camera.json).
- [`workflow.template.json`](workflow.template.json) — the LTX-2.3 **API-format**
  workflow (drop-in for `POST /prompt` or any MCP `enqueue_workflow` tool). A copy
  also lives in
  [`../../workflows/templates/brand-video-i2v.json`](../../workflows/templates/brand-video-i2v.json).
- [`models.md`](models.md) — the model files you need + where to get them.

## Use it — Wan 2.2 (default)

```
python scripts/generate.py video \
  --brand example-brand \
  --subject "<the motion you want>" \
  --from-image rover.png \
  [--camera static|pan-left|pan-right|pan-up|pan-down|zoom-in|zoom-out|rotate-cw|rotate-ccw] \
  [--quality fast|full] \
  [--width 768 --height 512] [--length 81] [--fps 16] \
  [--watermark] \
  --comfy-output-dir "<ComfyUI output dir>"
```

- **`--quality`**: `fast` = the lightx2v 4-step LoRAs (~30–55 s), the default for plain image-to-video;
  `full` = 20 steps without the LoRAs (~3 min), more motion but it drifted the camera more in the review.
  Wan only: with `--model ltx23` it is an error.
- **`--camera <move>`** uses Wan 2.2 **Fun Camera**: `static` locks the camera while the scene moves (the
  fix for LTX's unavoidable push-in on looping backgrounds); the others are controlled moves. It defaults
  to `full` quality, because the 4-step mode kept the camera locked but cut the scene's motion to about a
  third (measured 2026-10); `--quality fast` (~35 s) is fine when the camera move is the point. Naming the
  Fun Camera model directly (`--model wan22-camera`) also needs a `--camera` move; without one it's an error.
- Wan's native clip is **81 frames at 16 fps (5 s)**; sizes snap down to multiples of 16. The brand
  `video:` block's `width`/`height` apply; its `length`/`fps`/`audio` are LTX settings.
- `--length` snaps down to the 4k+1 frame counts Wan renders (`--length 96` renders 93), and a note says
  so. Wan's motion is timed for 16 fps, so `--fps` only changes the playback speed (also noted).
- Flag combinations a family can't render are errors raised before the start frame is uploaded or the GPU
  freed.
- **Silent.** For sound, run `python scripts/generate.py audio --mode foley --from-video <clip>
  --subject "<the sounds>"`, or use `--model ltx23`.
- `--upscale` is LTX-only (its latent upscaler); for a bigger Wan clip ask for it with `--width`/`--height`.

## Use it — LTX-2.3 with synced audio (`--model ltx23`)

```
python scripts/generate.py video --model ltx23 \
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
  overwritten (idempotent re-render); a `chimera replay` lands beside it as `<name>_replay` instead.
- `--length` snaps down to the 8k+1 frame counts LTX renders (`--length 100` renders 97), with a note.
- `--quality` and `--camera` are Wan settings: with `--model ltx23` either one is an error.
- `--no-audio` skips the audio-generation path; all other flags remain the same.
- `--watermark` composites the brand logo over the final decoded video frames
  entirely in-graph, after the VAE decode — the synced audio track is never
  touched.

The filler reads the active brand's `brand.yaml` `video:` block for defaults:

```yaml
video:
  model: ltx23                        # pin LTX for this brand (null = the Wan 2.2 default); a file name works too
  width: 768
  height: 512
  length: 97                          # frames (LTX)
  fps: 25                             # (LTX)
  audio: true                          # (LTX) false = skip the synced-audio path (like --no-audio)
  upscale_model: ltx-2.3-spatial-upscaler-x2-1.1.safetensors   # optional --upscale override
```

Override any key on the CLI; an explicit CLI flag always wins over `brand.yaml`, and a brand
without a `video:` block falls back to the values above (768×512 · 97 frames · 25 fps · audio on).

## How it works — Wan 2.2

`LoadImage` + `CLIPTextEncode` (umt5-xxl) → **`WanImageToVideo`** (or, with `--camera`,
**`WanCameraEmbedding` → `WanCameraImageToVideo`**) → two `KSamplerAdvanced` passes: the **high-noise
expert** runs the first half of the steps and hands its leftover noise to the **low-noise expert**
(`ModelSamplingSD3` shift 5, or 8 for Fun Camera) → `VAEDecode` → `CreateVideo` (16 fps) → `SaveVideo`.
`fast` puts the lightx2v 4-step LoRA on each expert (4 steps, CFG 1, switch at step 2); `full` samples the
bare experts (20 steps, CFG 3.5, switch at 10). The brand negative is joined to Wan's own recommended
negative list. Core ComfyUI nodes only — no node pack.

## How it works — LTX-2.3

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

## Known issue: ComfyUI ≥ 0.40 breaks the pack's STG guidance (patch included)

ComfyUI **0.40.0** (2026-10-13) passes attention inputs to the attention backend wrapped in a single-use
`AttentionTensorContainer` (core PR #16806). The LTXVideo pack's spatiotemporal guidance (STG) patches
that call, and for the layers it skips it returns `v` unchanged. On 0.40 that is the container rather
than a tensor, so sampling fails:

```
SamplerCustomAdvanced: AttributeError: 'AttentionTensorContainer' object has no attribute 'shape'
```

This template uses STG (`"stg": 1.0` in both `GuiderParameters` nodes), so every Chimera video render fails
on 0.40 with any pack version up to at least `44c8a36` (2026-10-14). Fix it by applying
[`patches/ltxvideo-stg-comfyui-0.40.patch`](patches/ltxvideo-stg-comfyui-0.40.patch) to the pack, then
restart ComfyUI:

```bash
cd <ComfyUI>/custom_nodes/ComfyUI-LTXVideo
git apply <path-to-chimera>/modules/video/patches/ltxvideo-stg-comfyui-0.40.patch
```

The patch unwraps the container in the two skip shortcuts and changes nothing on older ComfyUI; it applies
cleanly at both the pinned `15d09ab` and `44c8a36`. Undo it with `git checkout stg.py`. If you can't patch the
pack, setting `"stg": 0.0` in both `GuiderParameters` nodes also renders, but without STG guidance. Remove
this section once the fix ships upstream.

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

| Run | Time (warm) |
|-----|-------------|
| Wan 2.2 `fast` (768×512, 81 frames) | ~35 s |
| Wan 2.2 `full` | ~170 s |
| Wan 2.2 Fun Camera, `full` (default for `--camera`) | ~170 s (768×512) – 250 s (720²) |
| Wan 2.2 Fun Camera, `--quality fast` | ~35 s |
| LTX-2.3 768×512, 97 frames, with audio | ~50–80 s |

- `ltx-2.3-22b-dev-nvfp4` @ 768×512 / 97 frames / 25 fps: generation time
  varies with prompt complexity; expect several minutes for a cold start.
- First render of a session is slower (model load + one-time JIT). Keep the
  model resident for faster iteration.

## VRAM

**Wan 2.2:** two fp8 experts (~13–14 GB each, sampled one after the other) plus the ~6 GB umt5 text
encoder. ComfyUI fills most of a 32 GB card while it runs (25–31 GB observed); the official template
reports about 84% of a 24 GB card at 640² (89% with the 4-step LoRAs). Smaller cards rely on ComfyUI's
offloading.

**LTX-2.3:** ~28–32 GB for the nvfp4 checkpoint. `--free-before` (default ON) clears other
resident models before queuing. See [`models.md`](models.md) for quantized and
distilled options.
