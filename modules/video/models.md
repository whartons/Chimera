# Video module — models

## Wan 2.2 14B (default) — core ComfyUI nodes, no pack

Two experts per model (high-noise and low-noise, fp8), plus the lightx2v 4-step LoRAs for `fast`
quality. All Apache-2.0, from `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` (the text encoder and VAE from
`Comfy-Org/Wan_2.1_ComfyUI_repackaged`). Those repos nest files under `split_files/<type>/`: place them in
`ComfyUI/models/<type>/`, without the `split_files` folder.

| File | Destination (`ComfyUI/models/…`) | Size | Needed for |
|------|----------------------------------|------|------------|
| `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` | `diffusion_models/` | ~13.3 GB | image-to-video |
| `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` | `diffusion_models/` | ~13.3 GB | image-to-video |
| `wan2.2_fun_camera_high_noise_14B_fp8_scaled.safetensors` | `diffusion_models/` | ~14.3 GB | `--camera` |
| `wan2.2_fun_camera_low_noise_14B_fp8_scaled.safetensors` | `diffusion_models/` | ~14.3 GB | `--camera` |
| `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` | `loras/` | ~1.1 GB | `--quality fast` |
| `wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors` | `loras/` | ~1.1 GB | `--quality fast` |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `text_encoders/` | ~6.3 GB | all Wan |
| `wan_2.1_vae.safetensors` | `vae/` | ~0.25 GB | all Wan |

---

## LTX-2.3 22B (`--model ltx23`) — synced audio

LTX-2.3 22B is a **multimodal checkpoint** that generates video and synchronized
48 kHz audio in a single pass. It requires the
[`ComfyUI-LTXVideo`](https://github.com/Lightricks/ComfyUI-LTXVideo) custom-node
pack for its `MultimodalGuider`, normalizing sampler, and spatial-upscaler nodes.

Download the files below from Hugging Face and drop each into the matching
`ComfyUI/models/...` folder. Filenames must match the ones in
[`workflow.template.json`](workflow.template.json) (or edit the template to match
what you downloaded).

## Model files

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `ltx-2.3-22b-dev-nvfp4.safetensors` | `Lightricks/LTX-2.3-nvfp4` | `checkpoints/` | ~21.7 GB | open weights |
| `ltx-2.3-22b-distilled-lora-384-1.1.safetensors` | `Lightricks/LTX-2.3` | `loras/` | ~7.6 GB | open weights |
| `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` | `Lightricks/LTX-2.3` | `latent_upscale_models/` | ~1 GB | open weights |
| `gemma_3_12B_it_fp4_mixed.safetensors` *(LTX-2.3 text encoder)* | fetched with the LTX-2.3 setup / the `ComfyUI-LTXVideo` pack | `text_encoders/` | ~7 GB | ❓ verify |

### What each file does

- **`ltx-2.3-22b-dev-nvfp4`** — the primary checkpoint; nvfp4-quantized for 32 GB
  cards. This is the daily-driver path. Load via the pack's `LTXVCheckpointLoader`
  or `CheckpointLoaderSimple`.
- **`ltx-2.3-22b-distilled-lora-384-1.1`** — the distilled-step LoRA that pairs
  with the nvfp4 checkpoint to reduce the required number of sampling steps.
  **Must be v1.1** — v1.0 was trained against an older model revision and is
  incompatible with the v1.1 upscaler.
- **`ltx-2.3-spatial-upscaler-x2-1.1`** — a 2× latent spatial upscaler. Wired
  into the opt-in `--upscale` pass (an `LTXVLatentUpsampler` spliced before the
  VAE decode — temporally coherent, see the README). Loaded by
  `LatentUpscaleModelLoader`. **Use the x2-1.1 file** — version must match the
  distilled LoRA.
- **`gemma_3_12B_it_fp4_mixed`** — LTX-2.3's text encoder (Gemma-3 12B). Load
  via **`LTXAVTextEncoderLoader`** (in-graph, local). **Never use the node pack's
  cloud `GemmaAPITextEncode` node** — that sends text to an external endpoint.

## Required node pack

| | |
|---|---|
| **Repo** | `https://github.com/Lightricks/ComfyUI-LTXVideo` |
| **Audited commit** | `15d09ab` — **pinned** (never `@latest`); re-scan before advancing the pin |
| **Install** | Clone into `ComfyUI/custom_nodes/`, then `git checkout 15d09ab`, then `pip install -r requirements.txt` |
| **Setup.py** | None — cloning the repo runs no code; only `pip install` executes the pack's Python |
| **Security** | Scan before adoption and on every update (same standard as the MCP bridge). Verdict for the reviewed revision (`15d09ab`, re-audited `3b9c5cd → 15d09ab`: LTX-2.5 example workflows, self-contained legacy RoPE helpers in a new pure-math `rope_utils.py`, Gemma-loader dir-resolution + left-padding fixes; no new nodes/deps/network): safe for local use — **with the two exclusions below** |

### Excluded nodes (do not use)
- **`GemmaAPITextEncode`** — sends prompts to a Lightricks cloud endpoint. Use
  `LTXAVTextEncoderLoader` (local Gemma) instead.
- **Prompt-enhancer node** — sets `trust_remote_code=True` when loading the
  enhancer model. Avoid unless you have independently audited that model.

## Caveats

- **LTX-2 LoRA incompatibility:** LoRAs trained on LTX-2 (19B) do **not** work
  with LTX-2.3 (22B). Source or retrain LTX-2.3-native LoRAs.
- **Wan 2.5 / 2.6 / 2.7 are API-only** — disqualified for local use; use Wan 2.2
  if you want the Wan family.
- **Post-Jan-2026 models:** LTX-2.3, the distilled LoRA, and the spatial upscaler
  are all recent releases. Smoke-test before pinning to a version, and re-scan the
  node pack before advancing its pin.
- **LoRA version matching:** the distilled LoRA and the spatial upscaler are
  version-paired — always use the same suffix (`-1.1` with `-1.1`).

## Faster / lighter variants (optional)

- **Wan 2.2 (default):** no lighter Wan model is wired into Chimera yet. GGUF quants of the 14B experts
  (via `ComfyUI-GGUF`) need that pack's own loader node, which Chimera's graph doesn't use, and the 5B TI2V
  model isn't wired in either. Below 24 GB, ComfyUI offloads part of each expert to system RAM, so the
  default still runs, only slower (not measured here; plenty of system RAM helps). `--quality fast` and a
  smaller `--width`/`--height` keep activation memory down.
- **Full distilled checkpoint** (`ltx-2.3-22b-distilled-1.1.safetensors`,
  `checkpoints/`, ~46 GB) — fewer sampling steps at full fp16 weight; only
  practical with 32+ GB VRAM and if you need maximum output quality without
  the nvfp4 quantization. See `Lightricks/LTX-2.3` on Hugging Face.
- **GGUF quantized** — community GGUF variants need `ComfyUI-GGUF`'s own loader
  node, and Chimera's LTX graph loads a checkpoint (`CheckpointLoaderSimple`), so
  they need a hand-edited graph; audio quality may also degrade under heavy
  quantization.
