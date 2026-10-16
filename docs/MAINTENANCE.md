# Maintenance

How Chimera stays current without surprise breakage: what runs by itself every week, what to do once a month
and once a quarter, and what can't wait. Moving a pinned component always follows the
[`UPDATING.md`](UPDATING.md) runbook (re-audit first); this page says when. The versions it all refers to are
in [`STACK.md`](STACK.md) (pins in §3–§4, host apps in §7).

## Weekly (automated)

| What runs | Where | What to do with it |
|---|---|---|
| **CI**, Mondays 06:00 UTC as well as on every push and PR: the two required Python 3.12 checks (Linux, Windows), Python 3.13 and 3.14 on Linux, ruff, pip-audit | [`ci.yml`](../.github/workflows/ci.yml) | A red scheduled run in a week with no commits means an upstream release broke something: fix it, or pin around it and say so in the CHANGELOG. A red 3.13 or 3.14 job doesn't block merges; it's work for the next Python upgrade. |
| **CodeQL** (GitHub's default setup) on every push and PR | repository settings | Triage any alert it raises. |
| **Dependabot**: pip bumps (one PR each), GitHub Actions and pre-commit hooks (one grouped PR each) | [`dependabot.yml`](../.github/dependabot.yml) | Merge when CI is green, then bring the version column of [`STACK.md`](STACK.md) §6 in line for an Actions bump. Keep ruff on the same minor in the `[dev]` extra, `requirements-dev.txt` and `.pre-commit-config.yaml` (raise all three together). |
| **The update report**, Mondays 14:00 UTC, refreshed in one "🔄 Weekly update report" issue | [`update-check.yml`](../.github/workflows/update-check.yml), [`update_report.py`](../scripts/update_report.py) | ⚠️ under *Security advisories*: see [Event-driven](#event-driven). ⚠️ pins behind upstream, ℹ️ newer host-app releases and a release line past its end of life: the next monthly window. |
| **The comfyui-mcp security gate**, Mondays 13:00 UTC: a Claude routine on the maintainer's claude.ai account that deep-scans a new comfyui-mcp release before it can be adopted, opens a bump PR only after a clean scan, and keeps the HOLD issue current, commenting only when something about the hold changes | claude.ai routine | Read its PR, or its comment on the HOLD issue, when one appears. |

The report never moves a pin. A pin held on purpose (`GIT_HOLDS` and `NPM_HOLDS` in the script) shows as held,
with the reason, and warns again once upstream moves past the commit it was re-audited up to. It flags a
security advisory when its version range covers the version we run,
or, when it gives no range the script can read, when it was published after the pinned commit (or in the
last five weeks, for a host app). comfyui-mcp shows as *held by policy* while it stays below npm's latest on
purpose.

## Monthly: the update window (about 1–2 hours)

[`maintenance.yml`](../.github/workflows/maintenance.yml) opens a checklist issue on the 1st (from
[`.github/maintenance/monthly.md`](../.github/maintenance/monthly.md)). In short:

1. Read the latest update report; advisories first. Merge the green Dependabot PRs.
2. Update the local stack, after saving a ComfyUI snapshot and never in the middle of a project: ComfyUI
   Desktop and core (through the app, then `chimera update-check` and `chimera doctor`), Ollama, Blender (the
   latest LTS patch), FreeCAD, Node.js LTS, the Python patch, uv, and the NVIDIA driver when a new one matters.
   Record anything you moved in `STACK.md` §7 and in `HOST_APPS` in `scripts/update_report.py`.
3. Re-audit and move the pins the report shows behind (UPDATING.md), with their docs and the report's tables.
4. Smoke-test: `python -m pytest`, `ruff check .`, one render per modality (image, video, audio, 3D), `render`
   and `cad`, and one self-correction loop.
5. If the repo changed, cut a patch release.

## Quarterly: the review (about half a day)

On the 1st of January, April, July and October a second checklist opens (from
[`.github/maintenance/quarterly.md`](../.github/maintenance/quarterly.md)), on top of that month's window:

1. **Models**, the quality lever: has a better model shipped for any modality, or for the agent loop's judge and
   code-gen? Start from [`CATALOG.md`](CATALOG.md). Trial candidates against the current default on the same
   prompts and seeds, swap a default only when it's clearly better, keep the old model a flag away, and give
   every new default a smaller-card path. Re-run the judge benchmark if the judge model or the verdict parser
   changed.
2. **Code health and docs**: open bugs and issues, test gaps, and the docs against the code.
3. **Security**: re-audit the pins, review the approval gates in `.claude/settings.json`, and read any advisory
   in the report.
4. **This page**: what was noise, and what got missed? Adjust the cadence.
5. A minor release if defaults or features changed.

## Event-driven

Some things don't wait for the window:

- **A high or critical advisory** that affects a pin or a host app's reference version: patch within days, or
  mitigate and say how in the HOLD or tracking issue.
- **An app that pushes its own update** (ComfyUI Desktop, a driver): snapshot first, never in the middle of a
  project, and smoke-test after.
- **A failed smoke render or a red scheduled CI run**: find out which upstream change caused it before the next
  render job.
- **An upstream bug Chimera works around**: report it upstream with a repro (and a fix when there is one), and
  link the report where the workaround is documented, so the workaround can go when the fix ships.
