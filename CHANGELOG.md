# Changelog

All notable changes to Chimera are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-06-09

### Added
- **Reliable update process** — a weekly scheduled job (`.github/workflows/update-check.yml` +
  `scripts/update_report.py`) opens a "🔄 Weekly update report" issue flagging when a pinned node
  pack / the MCP server falls behind upstream (**report-only** — never auto-bumps a pin), plus
  `docs/UPDATING.md`, the safe per-layer update runbook (with a quarterly model-review cadence).
  Makes the previously-aspirational "scheduled re-scan" doc claim real.

## [0.1.2] - 2026-06-09

### Added
- **`docs/STACK.md`** — a consolidated dependency / stack inventory (Python packages, ComfyUI core,
  pinned third-party node packs + audit status, MCP bridge, model defaults, CI actions, host stack)
  with a layer diagram. Linked from the README.
- **Animated self-correction demo** (`docs/images/agent-correct.gif`) as the README hero, plus a
  data-flow **mermaid diagram** ("How it works").
- **Brandless self-correction demo** — a chimera with a missing serpent-headed tail, corrected by the
  same loop against a *subject + quality* rubric (no brand), shown alongside the branded *style*
  correction in `modules/agent/self-correction.md`. Locked in with a brandless-correction unit test.
- Project hygiene: this `CHANGELOG.md`, a `.pre-commit-config.yaml`, and a (non-blocking) `pip-audit`
  CI step for dependency advisories.
- `CLAUDE.md`: a **"keep docs in sync"** convention (every behavior/dep/test-count change updates the
  matching docs) plus a Structure-tree refresh (`STACK.md`, `CHANGELOG.md`), so the living docs stay
  current as the project evolves.

### Changed
- The self-correction showcase now uses a **same-subject** fail→pass — a six-wheeled rover corrected
  from a glossy candy/toy finish to on-brand gunmetal tactical armor (same seed). The *brand* is what
  visibly gets corrected, not the subject, so the loop reads clearly.
- Expanded the `ruff` lint set from `F` to `F, B, UP` (correctness + likely-bug + modern-syntax rules;
  the stylistic `E`/`I` rules stay off by design — the codebase uses compact one-liners and a
  `sys.path` shim).

### Fixed
- `modules/image/brand-kits.md` "modes → templates" table corrected to the **Z-Image** defaults
  (`brand-zimage-*.json`); FLUX.2 is documented as the secondary fallback.
- LTX-2.3 node pack now **pinned to audited commit `229437c`** in `docs/CATALOG.md` and
  `modules/video/models.md` (it was previously unpinned, unlike the other two packs).
- `pyproject.toml` package version bumped to `0.1.2` (it was stale at `0.1.0` — behind even the
  released v0.1.1).

## [0.1.1] - 2026-06-09
### Added
- **Brandless self-correction** — `auto_generate.py --brand` is optional; the brandless rubric is
  subject + quality and winners route to the global `outputs/`.
- **Optional, agent-gated assistant-consensus judge** — `consensus_verdict()` + a `CallableJudge`
  seam; `--backend assistant` is offered but refused in a headless run (no assistant vision present).
- A real fail→pass artifact with verbatim judge traces.

### Changed
- README reframed agent-first / brand-optional. Codecov `patch` status made informational. Test count
  badge/claim corrected to 314.

### Fixed
- Strict rubric + structured `FIX: add…; avoid…` directives; the expander strips off-brand terms from
  the positive prompt (Z-Image zeroes the text negative).

## [0.1.0] - 2026-06-09
### Added
- Initial public release: brand-aware multimodal ComfyUI pipeline (image / video / audio / 3D), the
  agent self-correction loop (local Qwen2.5-VL judge), reproducible replay + provenance sidecars,
  `new-brand` / `lint` / `doctor` / `update-check`, the hardened MCP bridge, a GPU-free test suite,
  cross-platform CI, and `pip`-installable packaging.

[Unreleased]: https://github.com/whartons/ComfyUI-Chimera/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/whartons/ComfyUI-Chimera/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/whartons/ComfyUI-Chimera/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/whartons/ComfyUI-Chimera/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/whartons/ComfyUI-Chimera/releases/tag/v0.1.0
