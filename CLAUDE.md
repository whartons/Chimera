# CLAUDE.md — Chimera

Project brief for Claude Code. Read this first, then follow it for every change.

## What this is
Chimera is a modular, multimodal generative-media pipeline built on **ComfyUI**.
One repo, many beasts: **image, video, 3D, audio**, plus an **LLM/agent
orchestration layer**. The repo is **public and reusable**; personal and
brand-specific workflows stay **private (gitignored)**.

## Who it serves (drives examples only — keep tracked content generic)
- **Twitch content creation:** thumbnails, channel art, scene overlays, animated
  stingers/transitions, alert graphics, intro/outro music, short clips,
  talking-head / avatar segments.
- **Critter's Crafty Creations (personal craft projects):** product mockups,
  social posts, listing imagery, craft video, 3D relief/sign assets, and
  LoRA-driven generation.

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
├── CLAUDE.md            # this file
├── README.md
├── .gitignore
├── .env.example
├── docs/
│   ├── CATALOG.md       # best free models/templates per modality (+ licenses)
│   └── SETUP.md         # install + RTX 5090 / CUDA 12.8 notes
├── modules/             # one folder per modality (tracked, generic)
│   ├── image/
│   ├── video/
│   ├── audio/
│   ├── threed/
│   └── agent/           # LLM/VLM orchestration + MCP glue
├── workflows/
│   ├── templates/       # TRACKED: sanitized, reusable example workflows
│   └── personal/        # GITIGNORED: private / branded workflows
├── scripts/             # helper scripts (tracked)
└── outputs/             # GITIGNORED: generated media
```

## Module conventions
Every `modules/<name>/` folder contains:
- `README.md` — what it does, which models, VRAM needs, license notes.
- `workflow.template.json` — a sanitized, importable ComfyUI workflow.
- `models.md` — model name + Hugging Face / Civitai URL + license + where the
  file goes in `ComfyUI/models/...`. Never hardcode local absolute paths in
  tracked files.

## When asked to add a module or workflow
1. Create `modules/<name>/` with the three files above.
2. Add a sanitized template to `workflows/templates/`.
3. Update `docs/CATALOG.md` with the model(s) and their license.
4. Put any private/branded variant in `workflows/personal/` (gitignored) — never
   in a tracked path.

## Agent / MCP layer (`modules/agent/`)
This is where orchestration lives:
- an LLM expands and parameterizes prompts,
- a VLM critiques generated output in a self-correcting loop,
- an MCP server exposes pipeline actions so an assistant can drive ComfyUI.

Build on an **existing ComfyUI MCP server** (e.g. `artokun/comfyui-mcp` or
Comfy Pilot) rather than reinventing the transport. This repo's original surface
is the modules and orchestration logic, not the MCP bridge.

## Hardware
Baseline documented in `docs/SETUP.md`: RTX 5090 (32 GB VRAM), CUDA 12.8 /
`cu128` ComfyUI build (required for Blackwell). Do **not** assume others have a
5090 — always note per-module VRAM needs and quantized (GGUF / NVFP8) options.

## Guardrails
- Never commit secrets; use `.env` (gitignored) and keep `.env.example` current.
- Never commit anything under `workflows/personal/`, `outputs/`, or `models/`.
- Keep all tracked content brand-neutral and reusable.
