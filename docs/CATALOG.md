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

**Recommended default (mid-2026): Z-Image — Brand Kits pipeline default**

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

**Upscaler — Brand Kits image `--upscale` default**

| File | HuggingFace repo | Destination (`ComfyUI/models/…`) | License |
|------|-----------------|----------------------------------|---------|
| `4x-UltraSharp.pth` | `lokCX/4x-Ultrasharp` | `upscale_models/` | ❓ verify (repo lists it; neutral reference) |

- **4x-UltraSharp (ESRGAN)** — the default 4× upscaler for `generate.py image
  --upscale`. Spliced before `SaveImage` via `ImageUpscaleWithModel`; ESRGAN
  auto-tiles, so 1024²→4096² fits a 32 GB card. Override with `--upscale-model`
  or `defaults.upscale_model`. SUPIR (below) is the heavier, higher-fidelity
  alternative when a single image warrants it.

## ✂️ Image editing / control
- **Qwen-Image-Edit** — object insert/remove, style transfer, inpainting. ✅
- **ControlNet** (pose / depth / canny / normal) — structural control.
- **IP-Adapter** — reference a style or subject image.
- **Inpaint / Outpaint** nodes — fix or extend.
- **Upscale:** Real-ESRGAN, 4x-UltraSharp, **SUPIR** (heavy, gorgeous).

---

## 🎬 Video (text-to-video / image-to-video)

**Recommended default (mid-2026): LTX-2.3 22B**

Node pack: `https://github.com/Lightricks/ComfyUI-LTXVideo` — **pinned at audited
commit `229437c`** (re-scan before advancing the pin). Provides MultimodalGuider,
normalizing sampler, 2-stage spatial upscaler nodes, and IC-LoRA support — install
via ComfyUI-Manager, then `git checkout 229437c`, before using the models below.

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
| **Wan 2.2 14B** | Strong motion realism, Apache-2.0 | t2v + i2v | ✅ Apache-2.0 |
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

**Recommended default (mid-2026): ACE-Step 1.5 XL Turbo**

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
| **Stable Audio 3.0** | SFX + music, native ComfyUI support | ⚠️ check Stability license |

**For streaming:** great for intro/outro stings and background beds — pick the model
that sounds best for the cue (licensing isn't a constraint for personal use).

---

## 🧊 3D (image-to-3D)

**Recommended default (mid-2026): Hunyuan3D 2.1 — Brand Kits pipeline default**

Hunyuan3D 2.1 is **ComfyUI 0.22.3 core-native** — no custom node pack, no
gated model dependencies. One `.safetensors` checkpoint bundles the DiT shape
model, a DINOv2 CLIP-Vision encoder (ungated), and the 3D VAE. Takes a single
image and produces a high-detail geometry mesh (~421 K verts / ~1.1 M tris at
`octree_resolution 256`, valid glTF-v2 GLB). **Shape-only in the native path**
— the output has no PBR textures/materials (geometry only; downstream texturing
in Blender etc. works normally). In-pipeline PBR texturing (Hunyuan3D-Paint) is
**deferred on the Blackwell / cu130 / torch 2.10 stack**: it needs a compiled
`custom_rasterizer`, and every prebuilt wheel targets cu126/torch2.6 (or cu129/
torch2.8), none ABI-compatible with torch 2.10 — and no CUDA Toolkit (`nvcc`) is
present to compile `sm_120` from source. See [`modules/threed/README.md`](../modules/threed/README.md#why-in-pipeline-pbr-texturing-is-deferred-on-this-stack)
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

**Secondary: TRELLIS.2 4B — higher ceiling but wheel-bound**

TRELLIS.2 produces high-quality PBR-textured meshes from a single image and is
the stronger output when texturing matters. Currently listed as secondary
because its prebuilt Windows CUDA wheels target **Python 3.11 / PyTorch 2.7–2.8
/ CUDA 12.8** — incompatible with the reference setup (py3.12 / torch2.10 /
cu130). Building from source requires a separate CUDA 12.8 toolchain. Also has a
**gated dependency** (`facebook/dinov3-vitl16-pretrain-lvd1689m`) that requires
HF license acceptance + `hf auth login`. Upgrade path when wheel compatibility
catches up.

- HuggingFace repo: `microsoft/TRELLIS.2-4B` (whole repo, ~16 GB)
- Destination: `models/trellis2/` (preserving `ckpts/`, `pipeline.json`,
  `texturing_pipeline.json` sub-structure)
- Node pack: `https://github.com/visualbruno/ComfyUI-Trellis2`
- Gated dep: `facebook/dinov3-vitl16-pretrain-lvd1689m` — HF license accept +
  `hf auth login` required; model download returns 401 otherwise
- VRAM: ~16 GB (whole repo loaded)
- License: ❓ verify — conflicting sources; do not rely on any single claim

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

**Agent / VLM judge (self-correction loop): Qwen2.5-VL-7B-Instruct**

The vision judge for the **local standalone** self-correction backend (generate →
judge → refine). Run as a ComfyUI graph via the
[`1038lab/ComfyUI-QwenVL`](https://github.com/1038lab/ComfyUI-QwenVL) node pack —
security-scanned, **pinned at commit `fcd1ada`** (SAFE-WITH-PRECAUTIONS; re-scan before
advancing the pin). Weights from the **official Qwen repo only**. See
[`../modules/agent/self-correction.md`](../modules/agent/self-correction.md).

The judge graph also writes the verdict text to disk with the **core** ComfyUI node
`SaveImageTextDataSetToFolder` (`comfy_extras.nodes_dataset`, `experimental`) — this is
**core, not an extra pack** (unlike the third-party QwenVL pack above), so it needs
**ComfyUI ≥ 0.24.x** rather than an install. The QwenVL pack remains the only
third-party dependency for this backend.

| File / repo | HuggingFace repo | Destination (`ComfyUI/models/…`) | Size | License |
|------|-----------------|----------------------------------|------|---------|
| Qwen2.5-VL-7B-Instruct | `Qwen/Qwen2.5-VL-7B-Instruct` | `LLM/Qwen-VL/` | ~15 GB (FP16) | ✅ Apache-2.0 (verify) |

- FP16 ≈ **15 GB VRAM** — fits a 32 GB card alongside an image model. A smaller VL
  variant is the natural fallback on lighter cards (judging quality drops accordingly).
- The **assistant Workflow** backend needs no model — it judges with the assistant's
  own vision (multi-judge consensus); this VLM is only for the unattended local path.

---

## 🛠️ DCC / CAD bridges (MCP)

Peer tools to ComfyUI under the agent layer — driven by an assistant over **pinned,
audited, loopback-only** MCP servers (same standard as the `comfyui-mcp` bridge).
Interactive in Phase 1; headless automation backends are roadmap (Phase 2–3).

| Tool | Server | Pin | License | Socket |
|------|--------|-----|---------|--------|
| **Blender** | official `lab/blender_mcp` (Blender Foundation, Gitea) | `v1.0.0` = `03004fd` | GPL-3.0-or-later | `127.0.0.1:9876` |
| **FreeCAD** | `neka-nat/freecad-mcp` (GitHub) | commit `63acb30` (= v0.1.18) | MIT | `127.0.0.1:9875` |

- **Blender** chosen over the high-profile `ahujasid/blender-mcp` on security grounds
  (first-party, zero telemetry, headless-capable; the community server is GUI-only,
  ships opt-out Supabase telemetry, and had a live file-read bug). See
  [`../modules/blender/README.md`](../modules/blender/README.md).
  - The **interactive bridge** (GUI) is Phase 1. The **headless `generate.py render`
    backend** (`--mode mesh` / `comfy-scene` / `finish`, Blender Cycles, live-validated
    on Blender 5.1) is also shipped — it runs as a normal CLI subprocess, not through
    the MCP bridge (no per-call approval). Templates in `workflows/templates/blender/`.
- **FreeCAD** — de-facto community standard, MIT, no telemetry, 14 tools incl. FEM via
  CalculiX. See [`../modules/cad/README.md`](../modules/cad/README.md).
- FreeCAD remains **GUI-only**; headless `FreeCADCmd` automation is roadmap.
- Phase 3 (VLM self-correction over renders) is **shipped for Blender**
  (`auto_generate.py --pipeline mesh3d` — concept → Hunyuan3D mesh → contact-sheet render → form
  judge + geometry checks); the FreeCAD equivalent and 3D **texturing** (Phase 4) remain roadmap.

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
