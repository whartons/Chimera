# Audio module — models

Two stacks, one per mode. Download each file and drop it into the matching
`ComfyUI/models/...` subfolder. Filenames must match those in the template
JSONs (or edit the templates to match what you downloaded). No machine-absolute
paths — all destinations are relative to your `ComfyUI/` root.

---

## Music stack — ACE-Step 1.5 XL Turbo

ACE-Step 1.5 XL Turbo is **ComfyUI core-native** — no custom node pack
required. All nodes used (`UNETLoader`, `DualCLIPLoader`, `VAELoader`,
`KSampler`, `SaveAudioMP3`, etc.) ship with ComfyUI. Generates ~8 s of
instrumental audio in ~8 steps with cfg 1.0 (turbo-distilled).

Download from `Comfy-Org/ace_step_1.5_ComfyUI_files` on Hugging Face.

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `split_files/diffusion_models/acestep_v1.5_xl_turbo_bf16.safetensors` | `Comfy-Org/ace_step_1.5_ComfyUI_files` | `diffusion_models/` | ~10 GB | ⚠️ see note |
| `split_files/text_encoders/qwen_0.6b_ace15.safetensors` | `Comfy-Org/ace_step_1.5_ComfyUI_files` | `text_encoders/` | small | ⚠️ see note |
| `split_files/text_encoders/qwen_4b_ace15.safetensors` | `Comfy-Org/ace_step_1.5_ComfyUI_files` | `text_encoders/` | ~8.4 GB | ⚠️ see note |
| `split_files/vae/ace_1.5_vae.safetensors` | `Comfy-Org/ace_step_1.5_ComfyUI_files` | `vae/` | small | ⚠️ see note |

> **License note:** ACE-Step base architecture is MIT. The XL weights
> distributed via `Comfy-Org/ace_step_1.5_ComfyUI_files` reportedly carry a
> StepFun proprietary license — **unverified as of 2026-06-06**. Verify before
> any commercial distribution. Does not gate personal use here; recorded as
> neutral reference for anyone who forks.

### What each file does

- **`acestep_v1.5_xl_turbo_bf16`** — the main diffusion model; loaded via
  `UNETLoader` (not `CheckpointLoaderSimple` — this is a split-file layout).
- **`qwen_0.6b_ace15` + `qwen_4b_ace15`** — **both are required** for the
  `DualCLIPLoader` with `type: ace`. The loader instantiates a dual-encoder
  conditioning stack; if either file is missing, loading fails.
- **`ace_1.5_vae`** — the audio VAE; loaded via `VAELoader` and used by
  `VAEDecodeAudio` to decode the latent into a waveform.

---

## Foley stack — HunyuanVideo-Foley

HunyuanVideo-Foley requires the `phazei/ComfyUI-HunyuanVideo-Foley` custom
node pack (see node pack section below).

All three `.safetensors` files go into `models/foley/` (a non-standard
subfolder that the pack's loaders target directly — do not move them to
`checkpoints/` or `diffusion_models/`).

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `hunyuanvideo_foley_fp8_e4m3fn.safetensors` | `phazei/HunyuanVideo-Foley` | `foley/` | ~5.3 GB | ❓ verify |
| `synchformer_state_dict_fp16.safetensors` | `phazei/HunyuanVideo-Foley` | `foley/` | small | ❓ verify |
| `vae_128d_48k_fp16.safetensors` | `phazei/HunyuanVideo-Foley` | `foley/` | small | ❓ verify |

### What each file does

- **`hunyuanvideo_foley_fp8_e4m3fn`** — the core video-conditioned audio
  diffusion model (fp8 e4m3fn quantized; loaded in bf16 precision by
  `HunyuanModelLoader`).
- **`synchformer_state_dict_fp16`** — the Synchformer synchrony encoder that
  aligns generated audio to the video frame timing.
- **`vae_128d_48k_fp16`** — the 128-channel, 48 kHz audio VAE used to decode
  the audio latents into a waveform.

### Auto-downloaded on first run (no HF token needed)

Two models are fetched automatically by `HunyuanDependenciesLoader` on the
first run and cached in the standard Hugging Face cache (`~/.cache/huggingface`
or `$HF_HOME`). Both repos are **ungated** — no token required:

| Model | HuggingFace repo | Purpose |
|-------|-----------------|---------|
| SigLIP2 vision encoder | `google/siglip2-base-patch16-512` | Visual conditioning for the foley model |
| CLAP audio encoder | `laion/larger_clap_general` | Text-audio cross-modal conditioning |

After the first run these are loaded entirely from cache. To run fully offline,
pre-stage the cache once and set `HF_HUB_OFFLINE=1`.

---

## Required node pack — HunyuanVideo-Foley

| | |
|---|---|
| **Repo** | `https://github.com/phazei/ComfyUI-HunyuanVideo-Foley` |
| **Audited commit** | `afd2960` |
| **Security verdict** | Safe-with-precautions (scanned at `afd2960`) |
| **Nodes used** | Only 3 of the pack's nodes: `HunyuanModelLoader`, `HunyuanDependenciesLoader`, `HunyuanFoleySampler` (the rest of the graph — `LoadVideo`, `GetVideoComponents`, `CreateVideo`, `SaveVideo` — is ComfyUI core) |
| **Excluded scripts** | `cli.py`, `infer.py`, `gradio_app.py` — carry `torch.load(weights_only=False)` pickle-RCE; never execute these |

### Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/phazei/ComfyUI-HunyuanVideo-Foley
cd ComfyUI-HunyuanVideo-Foley
git checkout afd2960
```

Install **only the requirements not already present** in the ComfyUI
environment — do **not** run a blanket `pip install -r requirements.txt`, which
can upgrade `transformers`/`diffusers` and break other modules. On the reference
setup only `accelerate`, `omegaconf`, and `loguru` were missing; `torch`,
`comfy`, and `av` are provided by ComfyUI. Restart ComfyUI and confirm the foley
nodes register with no startup network egress.

Re-scan the pack before advancing the pinned commit to a newer revision.

---

## Caveats

- **DualCLIPLoader requires both Qwen files.** `qwen_0.6b_ace15` and
  `qwen_4b_ace15` must both be present in `text_encoders/`. The 0.6B model is
  the fast-path encoder; the 4B model provides the richer conditioning. Neither
  is optional.
- **Foley model subfolder:** the three foley `.safetensors` files go in
  `models/foley/`, not the standard `models/checkpoints/`. The
  `HunyuanModelLoader` and `HunyuanDependenciesLoader` nodes target that path.
- **No node pack needed for music.** ACE-Step 1.5 XL Turbo is fully core-native;
  installing the foley pack does not affect the music workflow.
- **Post-Jan-2026 models:** ACE-Step 1.5 XL and HunyuanVideo-Foley are recent
  releases. Smoke-test after any update, and re-scan the foley node pack before
  advancing its pin.
