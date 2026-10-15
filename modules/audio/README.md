# `audio` — brand-aware music, sound effects and video foley

Three modes of audio generation in a single unified CLI entry point:

- **`--mode music`**: text → on-brand instrumental stinger, loop or track, output as an `.mp3` (V0).
  - **Default: Stable Audio 3 Medium**, which won the 2026-10 listening comparison by a wide margin.
  - **`--model acestep`:** ACE-Step 1.5 XL Turbo (e.g. for songs with lyrics/vocals).
  - Both take the brand's `audio.music_tags` from `brand.yaml`.
- **`--mode sfx`** — Stable Audio 3's **sound-effects** mode: text → a short sound effect (stinger
  whooshes, sword rings, UI and alert sounds) → `.mp3`.
- **`--mode foley`** — HunyuanVideo-Foley: video → synchronized SFX, muxed
  back onto the source frame batch → `.mp4`. Generates 48 kHz audio that the
  `Synchformer` dependency time-aligns to the on-screen motion.

## Files

- [`workflow.sa3.template.json`](workflow.sa3.template.json) — the Stable Audio 3 Medium graph (music and
  sfx), built from Comfy's official template with its prompt enhancer. A copy also lives in
  [`../../workflows/templates/brand-audio-sa3.json`](../../workflows/templates/brand-audio-sa3.json).
- [`workflow.music.template.json`](workflow.music.template.json) — ComfyUI
  **API-format** workflow for the ACE-Step music path. A copy also lives in
  [`../../workflows/templates/brand-audio-music.json`](../../workflows/templates/brand-audio-music.json).
- [`workflow.foley.template.json`](workflow.foley.template.json) — ComfyUI
  **API-format** workflow for the HunyuanVideo-Foley path. A copy also lives in
  [`../../workflows/templates/brand-audio-foley.json`](../../workflows/templates/brand-audio-foley.json).
- [`models.md`](models.md) — model files, HF repos, and install instructions.

## Use it — unified CLI

### Music stinger / loop

```
python scripts/generate.py audio \
  --brand <brand> \
  --mode music \
  --subject "upbeat electronic intro sting" \
  [--comfy-output-dir <dir>] \
  [--duration 8.0] [--bpm 120] [--keyscale "C minor"]
```

(`--watermark` is silently ignored for music and sfx — there is no visual canvas.)

The brief is the brand's `audio.music_tags` plus `--subject`.
- **Stable Audio 3** has no tempo or key inputs, so an explicit `--bpm` / `--keyscale` joins the brief
  (e.g. "…, 128 BPM, in A minor"). The brand's ACE-tuned `music_bpm` / `music_keyscale` defaults don't.
- **ACE-Step** (`--model acestep`) takes the brief as `TextEncodeAceStepAudio1.5` tags, and uses BPM / key
  directly.
- **Stable Audio 3 renders at least 1 s** (ComfyUI's minimum); a shorter `--duration` is an error before
  anything is queued. Render 1 s and trim it.

Override any key via CLI; CLI always wins over `brand.yaml`.

Output routes to `brands/<brand>/outputs/audio/<brand>_music_<seed>.mp3`.

### Sound effect

```
python scripts/generate.py audio --mode sfx \
  --subject "a heavy medieval sword unsheathing with a bright metallic ring" \
  [--duration 4] [--comfy-output-dir <dir>]
```

Stable Audio 3 with its prompt enhancer in sound-effects mode. The brief is the subject alone: a sound
effect doesn't inherit the brand's musical tags. Default length 4 s, minimum 1 s. Output:
`…/outputs/audio/<brand>_sfx_<seed>.mp3`.

### Foley (video → SFX)

```
python scripts/generate.py audio \
  --brand <brand> \
  --mode foley \
  --from-video clip.mp4 \
  --subject "mechanical servo whirr, rolling on gravel" \
  [--comfy-output-dir <dir>] \
  [--watermark] \
  [--fps 25] \
  [--duration 3.88]
```

- `--from-video` is the input clip — a file in the brand's
  `outputs/video/`, `outputs/`, `references/`, or `products/` folder (searched in
  that order; `outputs/video/` is where the media-type router puts generated clips).
  The filler takes fps/duration/size from the clip's own Chimera sidecar, or probes them with **PyAV**;
  use `--fps` and `--duration` to override.
- Output routes to `brands/<brand>/outputs/video/<brand>_foley_<seed>.mp4` (a foley
  clip is a video, so it lands under `video/`).
- Foley always runs HunyuanVideo-Foley: `--model sa3` or `--model acestep` (music models) is an error,
  raised before the clip is uploaded.
- `--watermark` composites the brand logo over the **source frame batch**
  before the mux step. The SFX audio edge is untouched.

### brand.yaml audio block

```yaml
audio:
  music_tags: "electronic, upbeat, cinematic, instrumental"
  music_bpm: 120
  music_keyscale: "C minor"
  music_duration: 8.0
  foley: "hunyuan"            # backend selector
  foley_negative: "music, speech, voice, singing, noisy, harsh"
```

Field names match the `Audio` block in `scripts/brandkit/manifest.py`
(`music_bpm`/`music_keyscale`/`music_duration`, not `bpm`/`key`/`duration`) —
unknown keys are ignored with a warning. Override `--duration`/`--bpm`/
`--keyscale` on the CLI; the CLI flag always wins.

## How it works

### Music and sfx — Stable Audio 3 Medium (default)

The official Comfy graph, core nodes only (ComfyUI 0.40):

1. **Prompt enhancer.** A small LLM (**Qwen3.5-2B** via `TextGenerate`) rewrites the brief using the
   template's own system prompt for the mode (`Music` or `SFX`), sized to the target length. Its sampling
   seed is the render seed, so a replay gets the same rewrite.
2. **`CheckpointLoaderSimple(stable_audio_3_medium)`** with a **T5Gemma** text encoder
   (`CLIPLoader(type="stable_audio")`) → `CLIPTextEncode` (empty negative) → `EmptyLatentAudio(seconds)`.
3. **`KSampler`:** 8 steps, `lcm`, CFG 1 → `VAEDecodeAudio` → `SaveAudioAdvanced` (mp3 V0).

About 4–10 s per clip on an RTX 5090. The sidecar records your brief; the enhancer's rewrite is
re-derived on replay.

### Music — ACE-Step 1.5 XL Turbo (`--model acestep`, 8-step turbo)

The graph uses:

1. **`UNETLoader`** — loads `acestep_v1.5_xl_turbo_bf16.safetensors` from
   `models/diffusion_models/`.
2. **`ModelSamplingAuraFlow`** — wraps the model for the AuraFlow sampler
   schedule (shift 1.73).
3. **`DualCLIPLoader`** — loads **both** `qwen_0.6b_ace15.safetensors` and
   `qwen_4b_ace15.safetensors` with `type: ace` (both are required; the loader
   will fail if either is missing).
4. **`VAELoader`** — `ace_1.5_vae.safetensors`.
5. **`TextEncodeAceStepAudio1.5`** — encodes the genre/style tags plus optional
   lyrics. CFG scale 2.0 (note: this is the text-encode CFG, separate from the
   KSampler CFG).
6. **`ConditioningZeroOut`** — serves as the negative conditioning (no explicit
   negative text prompt needed for the turbo path).
7. **`EmptyAceStep1.5LatentAudio`** — allocates the latent buffer.
8. **`KSampler`** — 8 steps, euler, cfg 1.0 (turbo distilled — CFG 1.0 is
   correct; higher values will degrade output).
9. **`VAEDecodeAudio`** → **`SaveAudioMP3`** (V0 quality, `audio/brand_music`
   prefix).

### Foley — HunyuanVideo-Foley (50-step euler)

The graph uses:

1. **`LoadVideo`** → **`GetVideoComponents`** — splits the source clip into
   frame images + audio components.
2. **`HunyuanModelLoader`** — loads `hunyuanvideo_foley_fp8_e4m3fn.safetensors`
   (fp8 quantized, loads in bf16 precision in-graph).
3. **`HunyuanDependenciesLoader`** — loads `synchformer_state_dict_fp16` and
   `vae_128d_48k_fp16`. SigLIP2 and CLAP are fetched from HF cache on this
   node's first run (see Security section below).
4. **`HunyuanFoleySampler`** — 50 steps, euler, cfg_scale 4.5; `force_offload`
   defaults to `true` (offloads after each forward pass to keep VRAM
   manageable). The prompt describes the desired sound; the negative prompt
   excludes music/speech artefacts.
5. **`CreateVideo`** — muxes the decoded audio back onto the source frame
   images at the source fps.
6. **`SaveVideo`** — writes `video/brand_foley_*.mp4` (h264).

## VRAM

| Mode | Approximate VRAM | Notes |
|------|-----------------|-------|
| Music / sfx (Stable Audio 3 Medium) | ~14 GB of weights (8.6 GB model + 1.1 GB T5Gemma + 4.2 GB Qwen3.5-2B enhancer) | `--free-before` default ON |
| Music (ACE-Step Turbo) | ~12–14 GB | `--free-before` default ON |
| Foley (HunyuanVideo-Foley) | ~12–16 GB peak | `force_offload` default ON; offloads between passes |

`--free-before` (default ON for the `audio` modality) asks ComfyUI to unload its models (`POST /free`) just
before queueing, so resident image or video models don't crowd the audio graph.

## Watermark

**Foley only.** `--watermark` composites the brand logo (the `logo.default`
PNG under `brands/<brand>/logos/`) over the source frame batch inside the graph,
placed **before** the `CreateVideo` mux node. The SFX audio output from the
sampler is written directly into the mux step and is never touched by the
watermark composite.

**Music has no visual canvas** — `--watermark` is silently ignored for
`--mode music`.

**If the source clip is already watermarked** (e.g. a foley operation on a
clip produced by the `video` module with `--watermark`), do **not** also pass
`--watermark` to the foley step — that would double-stamp the logo. The mux
inherits the already-composited frames from the source.

## Auto-probe (foley)

The filler reads the source video's fps, duration, and frame size automatically, with no manual frame
counting needed:

1. from the clip's own **Chimera sidecar** (`<clip>.json`, written by `chimera video`): exact, and needs
   no extra package;
2. else by probing the file with **PyAV** (the `[video]` extra);
3. else it falls back to 25 fps / 5 s and warns.

The sidecar step matters for Wan 2.2 clips (16 fps): before it, a host without PyAV re-timed them at
25 fps, so they played about 1.6× too fast. Supply `--fps` or `--duration` on the CLI to override (useful
for a non-standard container or a sub-clip).

## Security — foley node pack

The foley node pack `phazei/ComfyUI-HunyuanVideo-Foley` is **safe-with-precautions, pinned at audited
commit `afd2960`**. Chimera's graph uses **only three of its nodes** (`HunyuanModelLoader`,
`HunyuanDependenciesLoader`, `HunyuanFoleySampler`; the rest of the graph — `LoadVideo`,
`GetVideoComponents`, `CreateVideo`, `SaveVideo` — is ComfyUI core) plus the `.safetensors` weights. The
pack's bundled CLI scripts (`cli.py`, `infer.py`, `gradio_app.py`) carry a `torch.load(weights_only=False)`
pickle-RCE and are **never executed** by the workflow — don't run them.

The **install steps, the `afd2960` pin + no-blanket-`pip` caution, and the first-run auto-downloads**
(SigLIP2 + CLAP, both ungated) are single-sourced in
**[`models.md`](models.md#required-node-pack--hunyuanvideo-foley)** — re-scan before advancing the pin.

## Local-only & security (music)

The ACE-Step graph is ComfyUI-core-native — all nodes (`UNETLoader`,
`DualCLIPLoader`, `KSampler`, `SaveAudioMP3`, etc.) ship with ComfyUI and
require no additional node pack. No external network calls during inference.

## Performance (RTX 5090 / cu130 / SageAttention)

- **Stable Audio 3 (music / sfx):** a 12 s track in ~10 s, a 4 s sound effect in ~4 s, including the
  prompt enhancer (2026-10 live runs).
- **ACE-Step (8-step turbo):** an 8-second stinger generates in a few seconds on
  the 5090 after model load. First session is slower (model load).
- **Foley (50-step euler):** generation time scales with clip length and
  resolution. `force_offload` trades some speed for VRAM headroom; disable it
  if you have VRAM to spare.
