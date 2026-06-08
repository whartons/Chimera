# `audio` — brand-aware music generation and video foley

Two modes of audio generation in a single unified CLI entry point:

- **`--mode music`** — ACE-Step 1.5 XL Turbo: text → on-brand instrumental
  stinger or loop. Generates music from the brand's `audio.music_tags` in
  `brand.yaml`, output as an `.mp3` (V0 quality).
- **`--mode foley`** — HunyuanVideo-Foley: video → synchronized SFX, muxed
  back onto the source frame batch → `.mp4`. Generates 48 kHz audio that the
  `Synchformer` dependency time-aligns to the on-screen motion.

## Files

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

(`--watermark` is silently ignored for music — there is no visual canvas.)

The filler reads `audio.music_tags` from the active brand's `brand.yaml` and
populates the `TextEncodeAceStepAudio1.5` node's `tags` field. The subject
string is used as-is or merged with the brand tags depending on your filler
implementation. Override any key via CLI; CLI always wins over `brand.yaml`.

Output routes to `brands/<brand>/outputs/audio/<brand>_music_<seed>.mp3`.

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
  The filler auto-probes fps/duration/size via **PyAV**; use `--fps` and
  `--duration` to override.
- Output routes to `brands/<brand>/outputs/video/<brand>_foley_<seed>.mp4` (a foley
  clip is a video, so it lands under `video/`).
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

### Music — ACE-Step 1.5 XL Turbo (8-step turbo)

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
| Music (ACE-Step Turbo) | ~12–14 GB | `--free-before` default ON |
| Foley (HunyuanVideo-Foley) | ~12–16 GB peak | `force_offload` default ON; offloads between passes |

`--free-before` (default ON for the `audio` modality) calls `clear_vram` via
the MCP bridge before enqueuing, unloading any resident image or video models.

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

The filler reads the source video's fps, duration, and frame size automatically
using **PyAV** — no manual frame counting needed. Supply `--fps` or
`--duration` on the CLI to override the probed values (useful when the source
has a non-standard container or when you want to generate foley for a sub-clip).

## Security — foley node pack

The node pack `phazei/ComfyUI-HunyuanVideo-Foley` was security-scanned before
adoption. **Verdict: safe-with-precautions, pinned at audited commit `afd2960`.**

Chimera's foley graph uses **only the pack's registered ComfyUI nodes** — and
just three of them: `HunyuanModelLoader`, `HunyuanDependenciesLoader`, and
`HunyuanFoleySampler` (the remaining nodes in the graph — `LoadVideo`,
`GetVideoComponents`, `CreateVideo`, `SaveVideo` — are ComfyUI core) — plus the
`.safetensors` weights. The pack also ships bundled CLI scripts (`cli.py`,
`infer.py`, `gradio_app.py`); these are **never executed** by the Chimera
workflow — they carry a `torch.load(weights_only=False)` call that can execute
arbitrary Python from a pickled model file (pickle-RCE risk). Do not run those
scripts.

**First-run auto-downloads (foley only)**

The `HunyuanDependenciesLoader` node auto-fetches two models on its first run:

- `google/siglip2-base-patch16-512` (SigLIP2 vision encoder)
- `laion/larger_clap_general` (CLAP audio encoder)

Both are **ungated** (no Hugging Face token required). The download is
one-time; subsequent runs load from the local HF cache. To run fully offline
after that first pass, pre-stage the cache and set `HF_HUB_OFFLINE=1`.

**Install the node pack:**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/phazei/ComfyUI-HunyuanVideo-Foley
cd ComfyUI-HunyuanVideo-Foley
git checkout afd2960
```

Then install **only the requirements that are not already present** in the
ComfyUI environment — do **not** run a blanket `pip install -r requirements.txt`,
which can upgrade `transformers`/`diffusers` and break other modules. On the
reference setup only three packages were missing (`accelerate`, `omegaconf`,
`loguru`); `torch`/`comfy`/`av` are provided by ComfyUI. Restart ComfyUI and
confirm the foley nodes register with no startup network egress.

Re-scan the pack before advancing the pin to a newer commit.

## Local-only & security (music)

The ACE-Step graph is ComfyUI-core-native — all nodes (`UNETLoader`,
`DualCLIPLoader`, `KSampler`, `SaveAudioMP3`, etc.) ship with ComfyUI and
require no additional node pack. No external network calls during inference.

## Performance (RTX 5090 / cu130 / SageAttention)

- **Music (8-step turbo):** an 8-second stinger generates in a few seconds on
  the 5090 after model load. First session is slower (model load).
- **Foley (50-step euler):** generation time scales with clip length and
  resolution. `force_offload` trades some speed for VRAM headroom; disable it
  if you have VRAM to spare.
