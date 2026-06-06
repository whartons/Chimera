# Chimera Catalog — Best Templates & Models (2026)

Curated, locally-runnable models per modality, chosen on **quality and fitness for
the task** — licensing is not a selection factor here (use is personal). The License
column stays as neutral reference for anyone who forks; flags (✅ commercial-OK ·
⚠️ restricted · ❓ verify) describe terms, they don't gate choices.

> **Start here:** ComfyUI ships a built-in **Templates Library** (sidebar →
> categories) with one-click reference workflows for most of these. Use those as
> your starting point, then move customized copies into `workflows/personal/`.

---

## 🖼️ Image (text-to-image)
| Model | Strengths | VRAM (quantized) | License |
|-------|-----------|------------------|---------|
| **FLUX.2 (Klein)** | Newest FLUX, strong quality | ~12–24 GB | ❓ verify |
| **FLUX.1 [dev]** | Excellent quality & text | 7–8 GB (FP8) / 24 GB | ⚠️ **non-commercial** |
| **FLUX.1 [schnell]** | Fast, 1–4 step | ~8 GB | ✅ Apache-2.0 |
| **Qwen-Image (2512)** | Best multilingual text, editing, fast 8-step LoRA | ~12–16 GB | ✅ commercial-friendly |
| **SDXL / Juggernaut XL** | Mature ecosystem, tons of LoRAs | 6–8 GB | ✅ OpenRAIL |
| **SD 3.5** | Solid all-rounder | ~8–12 GB | ❓ check community license |
| **Z-Image Turbo** | Very fast turbo gen | low | ❓ verify |
| **Kolors (Kwai)** | Photoreal, bilingual | ~8 GB (INT8) | ✅ Apache-2.0 |

**Best image quality:** **FLUX.2** and **FLUX.1 [dev]** lead on fidelity & text;
**Qwen-Image** is strongest for multilingual text/editing and fast 8-step runs. Pick
by the result you want — there's no licensing trade-off to weigh.

## ✂️ Image editing / control
- **Qwen-Image-Edit** — object insert/remove, style transfer, inpainting. ✅
- **ControlNet** (pose / depth / canny / normal) — structural control.
- **IP-Adapter** — reference a style or subject image.
- **Inpaint / Outpaint** nodes — fix or extend.
- **Upscale:** Real-ESRGAN, 4x-UltraSharp, **SUPIR** (heavy, gorgeous).

## 🎬 Video (text-to-video / image-to-video)
| Model | Strengths | Notes | License |
|-------|-----------|-------|---------|
| **WAN 2.2** | Current open video leader; super fast with Lightning LoRAs | t2v + i2v | ❓ verify |
| **LTX-2** | **Audio-video** (synced sound), up to 4K/50fps/20s, RTX-optimized NVFP8 | great on a 5090 | open weights |
| **HunyuanVideo 1.5** | High-fidelity motion | t2v / i2v | ❓ verify |
| **FramePack F1** | Long video on modest VRAM | efficient | open |
| **AnimateDiff** | Legacy but flexible | stylized loops | open |

**For Twitch stingers/transitions:** LTX-2 (because it does synced audio) or
WAN 2.2 with Lightning LoRAs for speed.

## 🗣️ Talking head / avatar
- **LongCat 1.5 Avatar** — talking-head from audio + image.
- **LTX-2** — audio-video can carry lip-sync.
- (Useful for Twitch intros, animated mascot/host segments.)

## 🧊 3D (image-to-3D)
| Model | Strengths | VRAM | License |
|-------|-----------|------|---------|
| **Hunyuan3D 2.1** | Local, free, full PBR textures, 4K | ~12 GB (shape+texture) | ⚠️ Tencent community license — check commercial terms |
| **TripoSG** | Clean geometry from a single image | moderate | ❓ verify |
| **UltraShape 1.0** | Refines coarse meshes, sharp edges | 8–32 GB by res | ❓ verify |

> Hunyuan3D **3.0** is API/cloud only (paid "Partner Nodes") — **not** the free
> local path. Use **2.1** for free local generation.

## 🎵 Audio / music
| Model | Strengths | License |
|-------|-----------|---------|
| **ACE-Step** | ~4 min of music in ~20s; lyrics, voice cloning, remix | ❓ verify |
| **HeartMula** | Offline songs from lyrics + style tags, multilingual | open (Jan 2026) |
| **Stable Audio 3.0** | SFX + music, native ComfyUI support | ⚠️ check Stability license |

**For streaming:** great for intro/outro stings and background beds — just pick the
model that sounds best for the cue (licensing isn't a constraint for personal use).

## 🧠 LLM / agent layer
- **Local (via Ollama):** Qwen 3.6, Gemma, Llama, GLM — for prompt expansion,
  JSON workflow parameterization, and VLM critique loops.
- **API node:** Gemini (e.g. 3.1 Flash-Lite) is supported by the built-in LLM node.
- **Quantized loading:** `ComfyUI-GGUF` to fit large models in VRAM.

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
