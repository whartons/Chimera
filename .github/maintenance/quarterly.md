The quarterly review, about half a day, on top of this month's update window. [`docs/MAINTENANCE.md`](https://github.com/{{repo}}/blob/main/docs/MAINTENANCE.md) explains each step. Close this issue when you're done, with a note on what changed.

**Models (the quality lever)**
- [ ] For each modality (image, upscale, video, music, sound effects, foley, 3D, and the agent loop's judge and code-gen): has a better model shipped? Start from [`docs/CATALOG.md`](https://github.com/{{repo}}/blob/main/docs/CATALOG.md) and ComfyUI's template list.
- [ ] Trial the candidates against the current default on the same prompts and seeds. Swap a default only when it's clearly better, keep the old model a flag away, and give every new default a smaller-card path (CLAUDE.md, Hardware).
- [ ] Re-run the judge benchmark if the judge model or the verdict parser changed.

**Code health and docs**
- [ ] A deep dive: open bugs and issues, test gaps, and the docs against the code (README, `modules/*`, STACK, CATALOG, SETUP).
- [ ] Security: re-audit the pins, review the approval gates in `.claude/settings.json`, and read any advisory in the weekly report.
- [ ] Revisit the cadence itself in `docs/MAINTENANCE.md`: what was noise, and what got missed.

**Release**
- [ ] A minor release if defaults or features changed.
