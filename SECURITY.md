# Security Policy

Chimera is **orchestration glue** for [ComfyUI](https://github.com/comfyanonymous/ComfyUI):
brand-aware Python (`scripts/`), sanitized workflow templates (`workflows/templates/`), and docs.
It ships **no model weights and runs no bundled binaries** — the security surface is the Python
CLI plus the third-party ComfyUI node packs and MCP bridges a user chooses to install.

## Supported versions

This is a single evolving project; security fixes land on the latest `main`. Pin a commit if you
need stability, and re-pull `main` for fixes.

## Reporting a vulnerability

Please report privately — **do not open a public issue for a security bug**:

- Use GitHub's **Security → "Report a vulnerability"** (private advisory) on this repository.
- For non-sensitive hardening suggestions, a normal issue or PR is welcome.

Please include repro steps and the affected file/command. There's no formal SLA (this is a
personal, open project), but reports are taken seriously and acknowledged.

## What this project does to stay safe

These are practices the repo already follows — they're the reason it's safe to fork and run:

- **Third-party node packs are scanned and pinned.** Any ComfyUI custom-node pack is
  security-reviewed before adoption **and on every update**, then pinned to an audited commit. The pin
  fixes the pack's own code; its dependencies still resolve when you install it. Per-pack verdicts,
  exclusions, and the pinned commits live in [`docs/CATALOG.md`](docs/CATALOG.md) and each module's
  `models.md` (e.g. [`modules/video/models.md`](modules/video/models.md)).
- **No pickle / `torch.load` RCE paths.** Audio (HunyuanVideo-Foley), 3D, and the VLM judge use
  **only registered ComfyUI nodes + `.safetensors` weights — never a pack's bundled CLI scripts**,
  which can deserialize arbitrary pickles (remote code execution). See
  [`modules/audio/`](modules/audio/).
- **Prompts stay local by default.** Text encoders run **in-graph and offline** (e.g. LTX-2.3's local Gemma
  encoder); cloud encoder nodes that exfiltrate prompts to an external endpoint
  (`GemmaAPITextEncode`) and `trust_remote_code` prompt-enhancers are **explicitly excluded** —
  see [`modules/video/models.md`](modules/video/models.md). Two opt-in paths do send data out: an LLM
  endpoint you configure for the agent loop (a cloud `--judge-*` / `--llm-*` base URL, `--rewrite-prompts`,
  or `--pipeline cad` codegen) receives your prompts, the brand's style and palette, and the renders it
  judges; and the approval-gated comfyui-mcp tool `generate_with_api_node` runs paid partner API nodes.
- **No secrets, no weights, no machine paths in tracked files.** Configuration goes in a gitignored
  `.env` (documented by [`.env.example`](.env.example)); model weights, outputs, and caches are
  gitignored and referenced by name + source URL only. GitHub secret scanning with push protection is on
  for the repository, and the optional pre-commit hooks include `detect-private-key`.
- **Reproducibility provenance.** Each render writes a sidecar recording the resolved model, seed,
  prompts, ComfyUI version, and the pipeline's git commit — so a generated asset traces back to the
  exact code and graph that produced it.

## Your responsibilities when running it

- **Vet models and node packs you install.** Chimera names models and their sources; downloading and
  running them is at your discretion. Treat any new custom-node pack as untrusted until you've
  reviewed it (the same standard this repo applies).
- **Keep ComfyUI and your node packs updated**, and re-scan packs when you bump their pins.
