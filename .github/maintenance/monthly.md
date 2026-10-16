The monthly update window, about 1–2 hours. [`docs/MAINTENANCE.md`](https://github.com/{{repo}}/blob/main/docs/MAINTENANCE.md) explains each step, and [`docs/UPDATING.md`](https://github.com/{{repo}}/blob/main/docs/UPDATING.md) is the runbook for moving a pin. Close this issue when you're done, with a note on anything you skipped.

**First**
- [ ] Read the latest [weekly update report](https://github.com/{{repo}}/issues?q=is%3Aissue+is%3Aopen+label%3Aupdate-report). Anything ⚠️ under security advisories comes first.
- [ ] Merge the green Dependabot PRs (pip, GitHub Actions, pre-commit hooks).

**The local stack** (save a ComfyUI snapshot first, and never update in the middle of a project)
- [ ] ComfyUI Desktop and core, through the app; then `chimera update-check` and `chimera doctor`.
- [ ] Ollama, Blender (latest LTS patch), FreeCAD, Node.js LTS, Python patch, uv, and the NVIDIA driver if a new one matters.
- [ ] Update the reference versions in `docs/STACK.md` §7 and `HOST_APPS` in `scripts/update_report.py` for anything you moved.

**Pins** (re-audit before any bump)
- [ ] For each node pack or MCP server the report shows behind: re-audit the diff, then move the pin in its `models.md`, `docs/STACK.md`, `docs/CATALOG.md`, the tables in `scripts/update_report.py`, and `.mcp.json` for an MCP server.

**Smoke test**
- [ ] `python -m pytest` and `ruff check .`
- [ ] One render per modality (image, video, audio, 3D), `render` and `cad`, and one self-correction loop.

**Release**
- [ ] If the repo changed: a patch release (move CHANGELOG `[Unreleased]` into the new version, bump `pyproject.toml`, tag and publish the GitHub release).
