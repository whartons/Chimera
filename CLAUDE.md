# CLAUDE.md — Chimera

Project brief for Claude Code. Read this first, then follow it for every change.

> **Human reader (e.g. reviewing the repo)?** This file is the contributor brief for the AI
> coding assistant. For what Chimera *is* and how to use it, start with [README.md](README.md)
> and the per-module docs under [`modules/`](modules/).

## What this is
Chimera is a modular, multimodal generative-media pipeline built on **ComfyUI**.
One repo, many beasts: **image, video, 3D, audio**, plus an **LLM/agent
orchestration layer**. The repo is **public and reusable**; personal and
brand-specific workflows stay **private (gitignored)**.

## Who it serves (drives examples only — keep tracked content generic)
- **Live-streaming / content creation:** thumbnails, channel art, scene overlays,
  animated stingers/transitions, alert graphics, intro/outro music, short clips,
  talking-head / avatar segments.
- **Small craft / maker projects:** product mockups, social posts, listing
  imagery, craft video, 3D relief/sign assets, and LoRA-driven generation.

Use these to motivate examples, but everything committed must be brand-neutral
so anyone can fork and reuse it.

## Repo philosophy — respect this on every commit
- **Public + reusable.** Anything tracked must be generic and shareable. No
  secrets, no brand assets, no personal workflow JSON in tracked paths.
- **Personal workflows are gitignored.** `workflows/personal/**` and any
  `*.local.json` file (anywhere) are private. Sanitized, shareable templates
  live in `workflows/templates/`.
- **Modular.** Each modality is a self-contained module under `modules/<name>/`.
  Adding or changing one modality must not require touching another.
- **No large binaries.** Model weights, outputs, and caches are gitignored.
  Reference models by name + source URL in the catalog; never commit weights.
- **Best model for the job — licensing is not a selection constraint.** Use is
  personal, so always pick the highest-quality, best-fit model or template for the
  task regardless of license terms (FLUX.1-dev, Hunyuan3D, etc. are all fair game).
  `docs/CATALOG.md` still records each model's license as neutral reference for
  anyone who forks, but it never gates choices here.

## Structure
```
chimera/
├── CLAUDE.md            # this file (AI-contributor brief)
├── README.md            # human-facing overview + quickstart
├── .gitignore  .env.example  LICENSE
├── docs/
│   ├── CATALOG.md       # best models/templates per modality (+ licenses)
│   ├── SETUP.md         # install notes
│   └── BLACKWELL-TUNING.md  # RTX 50-series / cu130 tuning guide (measured numbers)
├── modules/             # one folder per modality (tracked, generic): image, video, audio, threed, agent
├── scripts/
│   ├── generate.py      # unified brand-aware CLI: image/video/audio/3d + replay/new-brand/lint
│   ├── brandkit/        # shared core: manifest, prompt, fillers, watermark, outputs, sidecar, mesh, comfy
│   └── agent/           # self-correction loop: rubric, expander, judge, loop, auto_generate
├── brands/              # Brand Kits — pattern public, brand DATA gitignored
│   ├── _template/  example-brand/   # tracked starter + public showcase brand (incl. its outputs/)
│   └── <your-brand>/    # GITIGNORED: private brands
├── workflows/templates/ # TRACKED: sanitized, reusable workflows  (workflows/personal/ is gitignored)
├── tests/               # GPU-free pytest suite (mocked ComfyUI client)
└── outputs/             # GITIGNORED: scratch (brand outputs route to brands/<brand>/outputs/)
```

## Module conventions
Every `modules/<name>/` folder contains at least:
- `README.md` — what it does, which models, VRAM needs, license notes.
- one or more sanitized, importable ComfyUI workflow templates (the canonical copies
  live in `workflows/templates/`; a module may carry several, e.g. image has Z-Image +
  FLUX.2 variants).
- `models.md` — model name + Hugging Face / Civitai URL + license + where the file goes
  in `ComfyUI/models/...`. Never hardcode local absolute paths in tracked files.

## When asked to add a module or workflow
1. Create `modules/<name>/` with the three files above.
2. Add a sanitized template to `workflows/templates/`.
3. Update `docs/CATALOG.md` with the model(s) and their license.
4. Put any private/branded variant in `workflows/personal/` (gitignored) — never
   in a tracked path.

## Agent / MCP layer (`modules/agent/` + `scripts/agent/`)
Two things live here (both built — see `modules/agent/self-correction.md`):
- **A self-correction loop** (`scripts/agent/`): build a rubric (brand-specific, or a general
  subject + quality bar when brandless) → generate → a VLM judges the output against the rubric →
  unmet criteria are fed back into the prompt → regenerate until it passes or hits an iteration cap.
  The core (`rubric`/`expander`/`judge`/`loop`) is judge-agnostic and model-free (unit-tested, no
  GPU); two backends slot in — a headless local **Qwen2.5-VL** judge and an assistant
  multi-judge-consensus pass. `--brand` is optional on `auto_generate.py` (brandless → `outputs/`).
- **An MCP bridge**: a pinned, security-audited ComfyUI MCP server exposes pipeline actions
  so an assistant can drive ComfyUI. Build on an **existing** server (e.g. `comfyui-mcp`)
  rather than reinventing the transport; the repo's original surface is the modules +
  orchestration logic, not the MCP bridge.

## Hardware
Baseline documented in `docs/SETUP.md` + `docs/BLACKWELL-TUNING.md`: RTX 5090 (32 GB VRAM).
CUDA 12.8+ is the minimum to drive Blackwell at all; the **reference build is cu130 / torch
2.10**, which unlocks comfy-kitchen's FP4 path (the headline ~2.7× win). Do **not** assume
others have a 5090 — always note per-module VRAM needs and quantized (GGUF / NVFP4 / fp8) options.

## Guardrails
- Never commit secrets; use `.env` (gitignored) and keep `.env.example` current.
- Never commit anything under `workflows/personal/`, `outputs/`, or `models/`.
- Keep all tracked content brand-neutral and reusable.
