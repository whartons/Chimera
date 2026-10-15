# Chimera Catalog — Best Templates & Models (2026)

Curated, locally-runnable models per modality, chosen on **quality and fitness for
the task** — licensing is not a selection factor here (use is personal). The License
column stays as neutral reference for anyone who forks; flags (✅ commercial-OK ·
⚠️ restricted · ❓ verify) describe terms, they don't gate choices.

> **Start here:** ComfyUI ships a built-in **Templates Library** (sidebar →
> categories) with one-click reference workflows for most of these. Use those as
> your starting point, then move customized copies into `workflows/personal/`.

> **Mid-2026 freshness note:** Z-Image, LTX-2.3, ACE-Step 1.5 XL, TRELLIS.2, and
> HunyuanVideo-Foley are all post-Jan-2026 releases. Verify ComfyUI node/version
> compatibility (smoke-test) before pinning any of them. Speed and quality claims
> for these models are largely vendor-stated or single-source — treat as directional
> until independently confirmed. Third-party node packs must be security-scanned
> before adoption (same standard as the MCP bridge).

---

## 🖼️ Image (text-to-image)

**Recommended default (late 2026): Qwen-Image-2.1 — Brand Kits pipeline default**

Picked in the 2026-10 model review over Z-Image Turbo, FLUX.2 and Qwen-Image-2.1 Turbo:
- **Best adherence:** product hero shots, logo text layout, and three distinct subjects in one scene.
- **Speed:** about 6 s per 1024² image (25 steps, CFG 1) on an RTX 5090.
- **Product mode is a reference edit**, so the product keeps its exact look in a new scene.

It's core-native in ComfyUI 0.40 (no custom node pack). The `image` module dispatches names starting with
`qwen_image` to the Qwen-Image templates; brandless runs and brands that don't pin a model use it.

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `qwen_image_2.1_int8_convrot.safetensors` | `Comfy-Org/Qwen-Image-2.1` | `diffusion_models/` | ~6.8 GB | ⚠️ Qwen research license |
| `qwen3vl_8b_int8_convrot.safetensors` | `Comfy-Org/Qwen-Image-2.1` | `text_encoders/` | ~8.7 GB | ⚠️ Qwen research license |
| `qwen_image_2.1_vae_bf16.safetensors` | `Comfy-Org/Qwen-Image-2.1` | `vae/` | ~0.6 GB | ⚠️ Qwen research license |

**Fast alternative: Z-Image** (`--model z_image_turbo_nvfp4.safetensors`; Apache-2.0)

Z-Image is ComfyUI core-native (support added in 0.22.3 — **no custom node
pack**), uses a **Qwen-3-4B text encoder loaded via `CLIPLoader(type="lumina2")`
— not the CLIP/T5 stack** — and runs well under 16 GB VRAM. It produces
noticeably better faces than FLUX.2 at lower VRAM cost. The Brand Kits `image`
module dispatches to Z-Image templates when the active model name starts with
`z_image`; it falls back to the FLUX.2 templates for any `flux2*` model name.

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `z_image_turbo_nvfp4.safetensors` | `Comfy-Org/z_image_turbo` | `diffusion_models/` | ~4.5 GB | ✅ Apache-2.0 |
| `z_image_bf16.safetensors` | `Comfy-Org/z_image_turbo` | `diffusion_models/` | ~12.3 GB | ✅ Apache-2.0 |
| `qwen_3_4b.safetensors` *(shared)* | `Comfy-Org/z_image_turbo` | `text_encoders/` | ~8 GB | ✅ Apache-2.0 |
| `ae.safetensors` *(shared)* | `Comfy-Org/z_image_turbo` | `vae/` | ~0.3 GB | ✅ Apache-2.0 |

- **Z-Image turbo** (`z_image_turbo_nvfp4`) — 8-step / CFG 1.0 fast path.
  Default for `txt2img` and `logo` modes in Brand Kits.
- **Z-Image base** (`z_image_bf16`) — 25-step / CFG 4.0, full fidelity. Default
  for `product` img2img (always) and for `txt2img`/`logo` when `--variant base`
  is passed.
- **Variant pairing is strict** — the model file, step count, and CFG are
  co-determined; do not mix them.
- The Qwen-3-4B text encoder replaces the CLIP/T5 stack used by earlier models.
  Load via `CLIPLoader(type="lumina2")`.

**Secondary / Brand Kits fallback: FLUX.2 [dev]**

Pass `--model flux2_dev_fp8mixed.safetensors` (or set `defaults.model` to a
`flux2*` name in `brand.yaml`) to route the Brand Kits `image` subcommand
through the FLUX.2 templates instead.

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | License |
|------|-----------------|----------------------------------|---------|
| `flux2_dev_fp8mixed.safetensors` | `Comfy-Org/FLUX.2` | `diffusion_models/` | ❓ non-commercial — verify |
| `mistral_3_small_flux2_bf16.safetensors` | `Comfy-Org/FLUX.2` text encoders | `text_encoders/` | ✅ Mistral / Apache-2.0 |
| `flux2-vae.safetensors` | `Comfy-Org/FLUX.2` repo | `vae/` | ❓ verify |

> **FLUX.2 caveat:** community reports of "waxy faces" and the full fp16 model
> saturates a 32 GB card. Use Z-Image for portraits; reserve FLUX.2 for
> text-heavy or multi-reference work where its prompt adherence shines.

**Other secondary / fallback picks**

| Model | Strengths | VRAM (quantized) | License |
|-------|-----------|------------------|---------|
| **FLUX.1 [dev]** | Excellent quality & text; huge LoRA ecosystem | 7–8 GB (FP8) / 24 GB | ⚠️ non-commercial |
| **FLUX.1 [schnell]** | Fast, 1–4 step | ~8 GB | ✅ Apache-2.0 |
| **Qwen-Image (2512)** | Best multilingual text, editing, fast 8-step LoRA | ~12–16 GB | ✅ commercial-friendly |
| **SDXL / Juggernaut XL** | Mature ecosystem, tons of LoRAs | 6–8 GB | ✅ OpenRAIL |
| **SD 3.5** | Solid all-rounder | ~8–12 GB | ❓ check community license |
| **Kolors (Kwai)** | Photoreal, bilingual | ~8 GB (INT8) | ✅ Apache-2.0 |

**Upscaler — Brand Kits image `--upscale` default: SeedVR2 7B**

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `seedvr2_7b_int8_convrot.safetensors` | `Comfy-Org/SeedVR2` | `diffusion_models/` | ~7.8 GB | ✅ Apache-2.0 |
| `seedvr2_ema_vae_fp16.safetensors` | `Comfy-Org/SeedVR2` | `vae/` | ~0.5 GB | ✅ Apache-2.0 |
| `4x-UltraSharp.pth` *(ESRGAN option)* | `lokCX/4x-Ultrasharp` | `upscale_models/` | ~67 MB | ❓ verify (repo lists it; neutral reference) |

- **SeedVR2 7B** — the default 4× upscaler for `generate.py image --upscale` since the 2026-10 review:
  a one-step diffusion upscaler (core-native in ComfyUI 0.40, tiled VAE) that restores natural detail
  where ESRGAN invented it (a crosshatch on a speaker grille, speckles on skin). 1024² → 4096² takes
  about 10 s on an RTX 5090.
- **4x-UltraSharp (ESRGAN)** — `--upscale-model 4x-UltraSharp.pth` (or `defaults.upscale_model`) for
  the classic `ImageUpscaleWithModel` pass: a few seconds faster, but it sharpens by inventing texture.
  SUPIR (below) is the heavier alternative.

## ✂️ Image editing / control
- **Qwen-Image-Edit** — object insert/remove, style transfer, inpainting. ✅
- **ControlNet** (pose / depth / canny / normal) — structural control.
- **IP-Adapter** — reference a style or subject image.
- **Inpaint / Outpaint** nodes — fix or extend.
- **Upscale:** Real-ESRGAN, 4x-UltraSharp, **SUPIR** (heavy, gorgeous).

---

## 🎬 Video (text-to-video / image-to-video)

**Recommended default (late 2026): Wan 2.2 14B — core ComfyUI nodes, Apache-2.0**

Picked in the 2026-10 review, which measured camera drift with chained feature tracking on three shots.
The prompts asked for a locked camera:
- **LTX-2.3** pushed in 9% on a product, drove a "parked" car off with a 34% pan, and drifted a face's
  identity.
- **Wan 2.2 with the lightx2v 4-step LoRAs** held ≤ 0.8% zoom, kept identity, and ran ~30–55 s per 5 s
  clip.
- **Wan 2.2 Fun Camera "Static"** held ≤ 0.15%. Fun Camera gives `--camera` a locked shot or a controlled
  pan / zoom / rotation.

Wan clips are silent (add sound with the foley module), so LTX-2.3 stays as `--model ltx23` for synced
audio.

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` | `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` | `diffusion_models/` | ~13.3 GB | ✅ Apache-2.0 |
| `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` | `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` | `diffusion_models/` | ~13.3 GB | ✅ Apache-2.0 |
| `wan2.2_fun_camera_{high,low}_noise_14B_fp8_scaled.safetensors` *(`--camera`)* | `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` | `diffusion_models/` | ~14.3 GB each | ✅ Apache-2.0 |
| `wan2.2_i2v_lightx2v_4steps_lora_v1_{high,low}_noise.safetensors` | `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` | `loras/` | ~1.1 GB each | ✅ Apache-2.0 |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `Comfy-Org/Wan_2.1_ComfyUI_repackaged` | `text_encoders/` | ~6.3 GB | ✅ Apache-2.0 |
| `wan_2.1_vae.safetensors` | `Comfy-Org/Wan_2.1_ComfyUI_repackaged` | `vae/` | ~0.25 GB | ✅ Apache-2.0 |

(The repackaged repos nest files under `split_files/<type>/`; drop that folder level when placing them.)

**Synced-audio option (`--model ltx23`): LTX-2.3 22B**

Node pack: `https://github.com/Lightricks/ComfyUI-LTXVideo` — **pinned at audited
commit `15d09ab`** (re-scan before advancing the pin). Provides MultimodalGuider,
normalizing sampler, 2-stage spatial upscaler nodes, and IC-LoRA support — install
via ComfyUI-Manager, then `git checkout 15d09ab`, before using the models below.

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `ltx-2.3-22b-dev-nvfp4.safetensors` | `Lightricks/LTX-2.3-nvfp4` | `checkpoints/` | ~21.7 GB | open weights |
| `ltx-2.3-22b-distilled-1.1.safetensors` | `Lightricks/LTX-2.3` | `checkpoints/` | ~46 GB | open weights |
| `ltx-2.3-22b-distilled-lora-384-1.1.safetensors` | `Lightricks/LTX-2.3` | `loras/` | ~7.6 GB | open weights |
| `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` | `Lightricks/LTX-2.3` | `latent_upscale_models/` | ~1 GB | open weights |
| `gemma_3_12B_it_fp4_mixed.safetensors` *(LTX-2.3 text encoder)* | fetched with the LTX-2.3 setup / the `ComfyUI-LTXVideo` pack | `text_encoders/` | ~7 GB | ❓ verify |

- **Dev nvfp4** (`ltx-2.3-22b-dev-nvfp4`) — quantized for 32 GB cards; primary
  daily-driver path.
- **Distilled** (`ltx-2.3-22b-distilled-1.1`) — fewer steps, higher throughput at
  full weight; only practical on 32+ GB.
- **Distilled LoRA** — **must be v1.1** to match the v1.1 spatial upscaler; v1.0
  LoRAs are incompatible.
- **Spatial upscaler** (`ltx-2.3-spatial-upscaler-x2-1.1`) — the 2× latent
  upscaler for `generate.py video --upscale`. Spliced before the VAE decode via
  `LTXVLatentUpsampler` (loaded by `LatentUpscaleModelLoader`), so it upscales in
  **latent space** — temporally coherent, unlike a per-frame ESRGAN pass.
  Override with `--upscale-model`. Use `x2-1.1`, not `x2-1.0`; version must match
  the LoRA.
- **Text encoder** — reuse the already-installed `gemma_3_12B_it_fp4_mixed`
  (`text_encoders/`). **Never use the node pack's cloud `GemmaAPITextEncode`**;
  always point to the local Gemma encoder.
- **LTX-2 LoRA incompatibility:** LoRAs trained on LTX-2 (19B) are **not**
  compatible with LTX-2.3; retrain or source LTX-2.3-native LoRAs.

**Secondary / fallback picks**

| Model | Strengths | Notes | License |
|-------|-----------|-------|---------|
| **LTX-2 19B dev-fp8** *(already validated)* | Audio-video (synced sound), up to 4K/50fps/20s, RTX-optimized | Solid fallback; existing LoRAs work here | open weights |
| **HunyuanVideo 1.5** | High-fidelity motion | t2v / i2v | ❓ verify |
| **FramePack F1** | Long video on modest VRAM | efficient | open |
| **AnimateDiff** | Legacy but flexible | stylized loops | open |

> **Wan 2.5 / 2.6 / 2.7 are API-only** — disqualified for local use. Use Wan 2.2
> if you want the Wan family for its motion realism.

**For live-stream stingers/transitions:** LTX-2.3 dev-nvfp4 (speed + quality) or
the already-validated LTX-2 path for synced audio-video. Wan 2.2 with Lightning
LoRAs is a strong second for pure-motion clips.

---

## 🗣️ Talking head / avatar
- **LongCat 1.5 Avatar** — talking-head from audio + image.
- **LTX-2 / LTX-2.3** — audio-video can carry lip-sync.
- (Useful for stream intros, animated mascot/host segments.)

---

## 🔊 Audio — synced foley (video → sound)

**Recommended default (mid-2026): HunyuanVideo-Foley**

Strong video-to-audio foley at 48 kHz, with a Synchformer dependency that
time-aligns the generated audio to on-screen motion. Security-scanned; node pack
pinned at audited commit `afd2960` (safe-with-precautions — Chimera's graph uses
only 3 of the pack's registered nodes, `HunyuanModelLoader` /
`HunyuanDependenciesLoader` / `HunyuanFoleySampler`; never run the bundled
`cli.py` / `infer.py` / `gradio_app.py` scripts, which carry a
`torch.load(weights_only=False)` pickle-RCE). Re-scan before advancing the pin.

Node pack: `https://github.com/phazei/ComfyUI-HunyuanVideo-Foley`

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `hunyuanvideo_foley_fp8_e4m3fn.safetensors` | `phazei/HunyuanVideo-Foley` | `foley/` | ~5.3 GB | ❓ verify |
| `synchformer_state_dict_fp16.safetensors` | `phazei/HunyuanVideo-Foley` | `foley/` | small | ❓ verify |
| `vae_128d_48k_fp16.safetensors` | `phazei/HunyuanVideo-Foley` | `foley/` | small | ❓ verify |

> **Auto-downloaded on first run (ungated, no HF token):** SigLIP2
> (`google/siglip2-base-patch16-512`) and CLAP (`laion/larger_clap_general`) are
> fetched automatically by `HunyuanDependenciesLoader` on first run and cached
> locally. An internet connection is required for that one-time pass; set
> `HF_HUB_OFFLINE=1` thereafter. The three `.safetensors` above must be placed
> manually in `models/foley/` before first use.

**Fallback:** LTX native AV (built into LTX-2 / LTX-2.3) — zero extra install,
works offline. **MMAudio is demoted to secondary fallback** (HunyuanVideo-Foley
benchmarks higher per the independent arXiv evaluation).

---

## 🎵 Audio — standalone music / stingers

**Recommended default (late 2026): Stable Audio 3 Medium (music + sound effects)**

It clearly won the 2026-10 listening comparison against ACE-Step 1.5 XL Turbo, using the same
three 30 s briefs and seeds (a synthwave intro, a lo-fi loop, an epic orchestral cue). It is also faster,
at ~4–10 s per clip. It runs core-native in ComfyUI 0.40 with the official graph's **Qwen3.5-2B prompt
enhancer**, and its sound-effects mode powers `audio --mode sfx`.

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `stable_audio_3_medium.safetensors` | `Comfy-Org/stable-audio-3` | `checkpoints/` | ~8.6 GB | ⚠️ Stability AI Community License |
| `t5gemma_b_b_ul2.safetensors` | `Comfy-Org/stable-audio-3` | `text_encoders/` | ~1.1 GB | ⚠️ Gemma terms |
| `qwen3.5_2b_bf16.safetensors` *(prompt enhancer)* | `Comfy-Org/Qwen3.5` | `text_encoders/` | ~4.2 GB | ✅ Apache-2.0 |

**Vocals / lyrics option (`--model acestep`): ACE-Step 1.5 XL Turbo**

ComfyUI core-native (no extra node pack); 8-step turbo, KSampler euler, cfg 1.0.
Generates instrumental stingers/loops from genre/style tags; supports lyrics, voice
cloning, and remix. Output: `.mp3` (SaveAudioMP3, V0).

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `split_files/diffusion_models/acestep_v1.5_xl_turbo_bf16.safetensors` | `Comfy-Org/ace_step_1.5_ComfyUI_files` | `diffusion_models/` | ~10 GB | ⚠️ see note |
| `split_files/text_encoders/qwen_0.6b_ace15.safetensors` | `Comfy-Org/ace_step_1.5_ComfyUI_files` | `text_encoders/` | small | ⚠️ see note |
| `split_files/text_encoders/qwen_4b_ace15.safetensors` | `Comfy-Org/ace_step_1.5_ComfyUI_files` | `text_encoders/` | ~8.4 GB | ⚠️ see note |
| `split_files/vae/ace_1.5_vae.safetensors` | `Comfy-Org/ace_step_1.5_ComfyUI_files` | `vae/` | small | ⚠️ see note |

> **Both Qwen text encoders are required.** `DualCLIPLoader` with `type: ace`
> expects both `qwen_0.6b_ace15` and `qwen_4b_ace15` — loading fails if either is
> missing.

> **License note:** ACE-Step base architecture is MIT. The XL weights distributed
> via `Comfy-Org/ace_step_1.5_ComfyUI_files` reportedly carry a StepFun proprietary
> license — this is **unverified as of 2026-06-06**; verify before any commercial
> distribution. Does not gate personal use here; recorded as neutral reference for
> anyone who forks.

**Secondary / fallback picks**

| Model | Strengths | License |
|-------|-----------|---------|
| **ACE-Step (base)** | Proven, MIT, ~4 min music | ✅ MIT |
| **HeartMula** | Offline songs from lyrics + style tags, multilingual | open (Jan 2026) |

**For streaming:** great for intro/outro stings and background beds — pick the model
that sounds best for the cue (licensing isn't a constraint for personal use).

---

## 🧊 3D (image-to-3D)

**Recommended default (late 2026): TRELLIS.2 — native in ComfyUI 0.40, textured**

Since ComfyUI 0.40, **TRELLIS.2** and **Pixal3D** (built on it) run on core nodes: no custom node pack,
no compiled wheels, and no gated download (the Comfy-Org packaging ships an ungated DINOv3 encoder). One
graph does all of it:
- cuts the subject out of its background (BiRefNet);
- generates structure → shape → texture;
- remeshes and UV-unwraps;
- **bakes PBR textures** (base color, metallic-roughness, normal, AO) into the GLB.

In the 2026-10 review on three photos, both beat Hunyuan3D 2.1. They came out textured, and they cut the
subject out of a cluttered photo, where Hunyuan3D rebuilt the desk and monitor with it. TRELLIS.2 was the
most faithful on two of three; Pixal3D, which matches the photo's camera via MoGe, was cleaner on the
third. Expect ~90–135 s per textured mesh on an RTX 5090 and ~12–15 GB of GPU memory; Hunyuan3D 2.1
takes ~25–35 s, shape only.

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `trellis_2_int8_convrot.safetensors` | `Comfy-Org/TRELLIS.2` | `diffusion_models/` | ~4.9 GB | ✅ MIT |
| `pixal3d_int8_convrot.safetensors` *(Pixal3D)* | `Comfy-Org/Pixal3D` | `diffusion_models/` | ~5.2 GB | ✅ MIT |
| `trellis_2_shape_vae_bf16.safetensors` | `Comfy-Org/Pixal3D` | `vae/` | ~1.0 GB | ✅ MIT |
| `trellis_2_texture_vae_bf16.safetensors` | `Comfy-Org/Pixal3D` | `vae/` | ~0.9 GB | ✅ MIT |
| `dino_v3_L_naf_fp32.safetensors` | `Comfy-Org/Pixal3D` | `clip_vision/` | ~1.1 GB | ⚠️ repo lists MIT; upstream DINOv3 is under Meta's DINOv3 license |
| `birefnet.safetensors` | `Comfy-Org/BiRefNet` | `background_removal/` | ~0.4 GB | ✅ MIT |
| `moge_2_vitl_normal_fp16.safetensors` *(Pixal3D)* | `Comfy-Org/MoGe` | `geometry_estimation/` | ~0.6 GB | ✅ MIT |

- Both models share one graph, but Chimera folds its model switch at build time, so each run needs only its
  own files: TRELLIS.2 the five rows without *(Pixal3D)*, Pixal3D the Pixal3D model + MoGe + the shared four.
- `chimera 3d --model trellis2|pixal3d|hunyuan21` (or a brand's `threed.model`); `--octree` is Hunyuan3D-only.
- The mesh3d agent loop judges the textured render. `--texture` / `--finalize` (Blender bakes for a
  shape-only mesh) need `--mesh-model hunyuan21`.

**Fast shape-only option: Hunyuan3D 2.1**

Hunyuan3D 2.1 is **ComfyUI 0.22.3 core-native** — no custom node pack, no
gated model dependencies. One `.safetensors` checkpoint bundles the DiT shape
model, a DINOv2 CLIP-Vision encoder (ungated), and the 3D VAE. Takes a single
image and produces a high-detail geometry mesh (~421 K verts / ~1.1 M tris at
`octree_resolution 256`, valid glTF-v2 GLB). **Shape-only in the native path**
— the output has no PBR textures/materials (geometry only; downstream texturing
in Blender etc. works normally). Painting a Hunyuan mesh inside ComfyUI (Hunyuan3D-Paint) is
**still deferred on the Blackwell / cu130 / torch 2.10 stack**: it needs a compiled
`custom_rasterizer`, and every prebuilt wheel targets cu126/torch2.6 (or cu129/
torch2.8), none ABI-compatible with torch 2.10 — and no CUDA Toolkit (`nvcc`) is
present to compile `sm_120` from source. See [`modules/threed/README.md`](../modules/threed/README.md#why-hunyuan3d-paint-in-comfyui-pbr-painting-for-hunyuan-meshes-is-still-deferred)
for the texturing routes (Blender/Substance, or a cu126 env) and the re-visit path.

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| `hunyuan_3d_v2.1.safetensors` | `Comfy-Org/hunyuan3D_2.1_repackaged` | `checkpoints/` | ~7.4 GB | ⚠️ Tencent community license — verify before commercial use |

- Bundles DiT + DINOv2 CLIP-Vision (ungated) + 3D VAE in a single file.
- `--octree` (default `256`) trades geometry detail vs file size:
  `256` ≈ ~1.1 M tris / ~18 MB GLB; `128` ≈ lighter preview mesh.
- `--free-before` defaults ON; peak fits a 32 GB card.

> **Hunyuan3D 3.0 reminder:** API/cloud only (paid "Partner Nodes") — **not**
> the free local path. Use **2.1** for free local generation.

**Other secondary picks**

| Model | Task | Strengths | License |
|-------|------|-----------|---------|
| **TripoSG** | image → 3D | Clean geometry from a single image | ❓ verify |
| **UltraShape 1.0** | mesh refine | Refines coarse meshes, sharp edges | ❓ verify |

---

## 🧠 LLM / agent layer
- **Local (via Ollama):** Qwen 3.6, Gemma, Llama, GLM — for prompt expansion,
  JSON workflow parameterization, and VLM critique loops.
- **API node:** Gemini (e.g. 3.1 Flash-Lite) is supported by the built-in LLM node.
- **Quantized loading:** `ComfyUI-GGUF` to fit large models in VRAM.

**Agent / VLM judge (self-correction loop): Qwen3-VL-8B-Instruct (via Ollama; cloud OpenAI-compatible also works)**

The vision judge for the self-correction backend (generate → judge → refine). **Default:** served by
**Ollama** over its OpenAI-compatible `/v1` endpoint (the `LLMJudge`, `--backend api`, `auto_generate.py`'s
default, which with nothing configured calls `http://127.0.0.1:11434/v1` or `$OLLAMA_HOST`) —
`ollama pull qwen3-vl:8b-instruct` (the **non-thinking** Instruct tag — a *thinking* tag like
`qwen3-vl:8b` spends its token budget on reasoning and returns empty content, silently scoring every
render 0.0; the loop now also errors loudly on empty judge output), no API key, zero Blackwell/torch coupling (Ollama runs its own bundled
runtime). The **same** `--backend api` path also targets any cloud OpenAI-compatible provider
(OpenAI/Anthropic/Gemini/OpenRouter), so a GPU-poor reuser can judge on the cloud. See
[`../modules/agent/self-correction.md`](../modules/agent/self-correction.md).

**Optional ComfyUI path (`--backend local`):** the judge can instead run as a ComfyUI graph via the
[`1038lab/ComfyUI-QwenVL`](https://github.com/1038lab/ComfyUI-QwenVL) node pack (re-pin to a
Qwen3-VL-capable commit ≥ v1.0.4 + re-scan before use; no longer a default/auto-checked pin). That graph
writes the verdict text with the **core** ComfyUI node `SaveImageTextDataSetToFolder`
(`comfy_extras.nodes_dataset`, `experimental`) — core, not an extra pack — needing **ComfyUI ≥ 0.24.x**.

| File / repo | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| Qwen3-VL-8B-Instruct | `Qwen/Qwen3-VL-8B-Instruct` (or `ollama pull qwen3-vl:8b-instruct`) | `LLM/Qwen-VL/` (ComfyUI path) | ~6–9 GB (Q4/q8) | ✅ Apache-2.0 |

- 8B ≈ **6–9 GB VRAM** (Ollama Q4/q8) — co-resides with an image model on a 32 GB card. Size ladder
  (pure config swap via `CHIMERA_JUDGE_MODEL` + `ollama pull`): **8B** (default) · **30B-A3B** MoE
  (≈32B capability at ≈3B speed) · **32B** (sharpest, slower, VRAM-tight) · **2B/4B** for small cards.
- The **assistant Workflow** backend needs no model — it judges with the assistant's
  own vision (multi-judge consensus); this VLM is for unattended `auto_generate.py` runs.

---

## 🛠️ DCC / CAD bridges (MCP)

Peer tools to ComfyUI under the agent layer — driven by an assistant over **pinned,
audited, loopback-only** MCP servers (same standard as the `comfyui-mcp` bridge).
The MCP bridges are interactive (Phase 1); Blender headless rendering (Phase 2), 3D
self-correction over Blender renders (Phase 3), headless FreeCAD geometry (`generate.py cad`),
and the **FreeCAD CAD self-correction loop** (`--mode script` + autonomous `auto_generate.py
--pipeline cad`) are all shipped.

| Tool | Server | Pin | Bridge license | Socket |
|------|--------|-----|----------------|--------|
| **Blender** | official `lab/blender_mcp` (Blender Foundation, Gitea) | `4309a396` (v1.0.0 +5) | GPL-3.0-or-later | `127.0.0.1:9876` |
| **FreeCAD** | `neka-nat/freecad-mcp` (GitHub) | commit `78bf023` (v0.1.27) | MIT | `127.0.0.1:9875` |

> The **Bridge license** column is the MCP server's own license, **not** the host application's. The host
> apps are licensed separately: **Blender** GPL-3.0-or-later, **FreeCAD** LGPL-2.1 (LGPL-2.0-or-later).

- **Blender** chosen over the high-profile `ahujasid/blender-mcp` on security grounds
  (first-party, zero telemetry, headless-capable; the community server is GUI-only,
  ships opt-out Supabase telemetry, and had a live file-read bug). See
  [`../modules/blender/README.md`](../modules/blender/README.md).
  - The **interactive bridge** (GUI) is Phase 1. The **headless `generate.py render`
    backend** (`--mode mesh` / `comfy-scene` / `finish`, Blender Cycles, live-validated
    on Blender 5.1) is also shipped — it runs as a normal CLI subprocess, not through
    the MCP bridge (no per-call approval). Templates in `workflows/templates/blender/`.
- **FreeCAD** — de-facto community standard; the `freecad-mcp` bridge is MIT (FreeCAD itself is LGPL-2.1), no telemetry, 17 tools incl. FEM via
  CalculiX. Needs v0.1.25+ (GHSA-v4pw-r6h3-v75q) and FreeCAD 1.1.4+. See [`../modules/cad/README.md`](../modules/cad/README.md).
- **FreeCAD headless `cad` is shipped** — `generate.py cad` drives `FreeCADCmd` to author
  parametric primitives (box/cylinder/cone/sphere/tube), convert CAD/mesh files, and **`--mode script`**
  run an agent-authored FreeCAD script (generative CAD) → STEP/STL/OBJ (templates in
  `workflows/templates/freecad/`, runner `scripts/brandkit/freecad.py`). STEP is the BREP authoring
  Blender lacks; glTF stays GUI-only (use STL → Blender). No model — deterministic geometry. The
  **CAD self-correction loop** (brief → script → `cad` → `render` → judge → revise) runs both
  assistant-driven (`--mode script`) and **fully autonomous** (`auto_generate.py --pipeline cad`, a
  provider-agnostic LLM writes the script — see the agent module). The interactive MCP bridge stays the
  route for live edits.
- Phase 3 (VLM self-correction over renders) is **shipped for Blender**
  (`auto_generate.py --pipeline mesh3d` — concept → image-to-3D mesh (TRELLIS.2 by default, textured;
  `--mesh-model`) → contact-sheet render → form judge + geometry checks). **Phase 4a** adds albedo
  texturing for a shape-only Hunyuan3D mesh (`--mesh-model hunyuan21 --texture`: front-projected bake,
  back palette-filled) restoring the color rubric. **Phase 4b** ships all-around texture: the **multi-view
  bake** (`generate.py finalize-texture` → `_common.bake_multiview`, no model, pure bpy/Cycles) **plus
  `--auto-repaint`** which *generates* the views — `render_views` depth + an **SDXL depth-ControlNet +
  IPAdapter** repaint (`scripts/brandkit/repaint.py`). Pinned/audited pieces for auto-repaint:
  | Piece | Source / pin | License |
  |---|---|---|
  | IPAdapter node pack | `cubiq/ComfyUI_IPAdapter_plus` @ `a0f451a` (audited safe-with-precautions) | MIT |
  | IPAdapter model | `h94/IP-Adapter` → `ip-adapter-plus_sdxl_vit-h.safetensors` → `models/ipadapter/` | Apache-2.0 |
  | CLIP-Vision (ViT-H) | `h94/IP-Adapter` image_encoder → `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` → `models/clip_vision/` | MIT |
  | Depth ControlNet | `xinsir/controlnet-depth-sdxl-1.0` → `models/controlnet/` | Apache-2.0 |
  | Base | `sd_xl_base_1.0.safetensors` (already present) | CreativeML-OpenRAIL++ |

  Auto-repaint masks each view to its depth silhouette + adds cross-view consistency (a 2nd IPAdapter pass
  on the previous painted view). The **autonomous CAD loop** uses the provider-agnostic LLM backend
  (`scripts/agent/llm.py` — OpenAI-compatible: Gemini / OpenAI / Anthropic / OpenRouter / local). The
  **in-loop finalize** on the mesh3d winner is now **shipped** (`auto_generate.py --pipeline mesh3d
  --finalize` — auto-runs the auto-repaint bake on the winner + re-judges, informational).

---

## Where to get everything
- **ComfyUI Templates Library** — sidebar, built in. First stop.
- **ComfyUI docs / workflow examples** — https://docs.comfy.org/tutorials
- **ComfyUI-Manager** — search + install models and community workflows in-app.
- **Hugging Face** — 90k+ models, filter by task/license/size.
- **Civitai** — checkpoints, LoRAs, community workflows.

## License column — reference only
The License column is informational, kept for anyone who forks this repo for their
own (possibly commercial) use. For this project's personal use it imposes no
constraints. Model terms change; the flags are a starting point, **not** legal advice.
