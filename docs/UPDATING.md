# Updating Chimera — staying current, safely

Chimera is built to keep producing the **best-quality outputs over time**, which means keeping the
stack current *without* letting an unreviewed upgrade silently break a graph or smuggle in untrusted
code. Two pieces make that reliable:

- **The nudge** — a weekly scheduled job ([`.github/workflows/update-check.yml`](../.github/workflows/update-check.yml))
  opens/refreshes a single **"🔄 Weekly update report"** issue: is any pinned node pack / the MCP
  server behind upstream, and the standing manual reviews (models, ComfyUI). It is **report-only** —
  it never bumps a pin. Run it on demand from the **Actions tab** any time.
- **The lever** — this runbook: the safe, gated process to actually apply each kind of update.

> **The three gates — run them after *any* update before you trust it:**
> 1. `python -m pytest -q` is green, 2. `chimera doctor` (and `chimera doctor --brand <b>`) is clean,
> 3. a **smoke render** of the affected modality looks right. If any gate fails, roll back.

The dependency inventory those updates touch lives in [`docs/STACK.md`](STACK.md); models in
[`docs/CATALOG.md`](CATALOG.md). Per the [docs-sync rule](../CLAUDE.md#keep-the-docs-in-sync-every-change),
**every update updates the matching docs in the same change.**

---

## 1 · Python deps & GitHub Actions — *automated (Dependabot)*
Dependabot opens weekly PRs (`pip` + `github-actions`). Nothing to remember:
1. Review the PR diff + linked changelog.
2. Wait for CI green (the two pytest matrix jobs are the required checks).
3. Merge (squash). Done.

If you want to pull deps locally: `pip install -U -e ".[dev]"`, then run the gates.

## 2 · ComfyUI (Desktop) — *manual, low-risk*
ComfyUI Desktop versions independently of the `comfyanonymous/ComfyUI` core repo's GitHub releases,
so the weekly report only *points* at the core release — the authoritative check is local:
1. `chimera update-check` (against your running instance) tells you if you're behind.
2. Update via the **ComfyUI Desktop app**.
3. Run the gates — especially **`chimera doctor`** (confirms node packs + models still resolve) and a
   smoke render of **each modality** (a ComfyUI bump can change node schemas).
4. If the reference build moved, update the `0.24.1` references in `docs/STACK.md` / `docs/SETUP.md`
   and `COMFY_REF` in [`scripts/update_report.py`](../scripts/update_report.py).

## 3 · Pinned node packs & the MCP server — *manual, audit-gated*
LTXVideo, HunyuanVideo-Foley, QwenVL and `freecad-mcp` (GitHub git-pinned commits), `comfyui-mcp`
(npm-pinned version), and `blender_mcp` (Gitea git-pinned commit) are **pinned and security-audited**
— Dependabot can't see them, which is exactly why the weekly report checks them (`freecad-mcp` rides
the GitHub `check_git_pack`; `blender_mcp` uses the Gitea compare API since it is **not** on GitHub).
**Never bump to `@latest` blind.** When the report flags one behind:
1. **Re-audit the diff** between the current pin and the new commit/version — same standard as the
   original scan (look for new network calls, `eval`/`exec`, `torch.load(weights_only=False)`,
   `trust_remote_code`, new cloud nodes; for the **DCC bridges** also: **new tools** — re-classify
   Tier 1/2/3 and update **both** [`.claude/settings.json`](../.claude/settings.json) and
   [`tests/test_mcp_gates.py`](../tests/test_mcp_gates.py) together — plus new telemetry/egress and,
   for Blender, any `-t http`/transport change). See the per-pack audit notes in
   [`docs/CATALOG.md`](CATALOG.md), the module `models.md` / `requirements.md`, and the bridge READMEs.
2. Only if clean: bump the pin in **(a)** that module's `models.md` *(or `requirements.md` for the
   DCC/CAD bridges)* (`git checkout <sha>` / version), **(b)** [`docs/STACK.md`](STACK.md), **(c)** the
   audit-commit note in [`docs/CATALOG.md`](CATALOG.md), **(d)** the `GIT_PACKS` / `GITEA_PACKS` /
   `NPM_PACKS` table in [`scripts/update_report.py`](../scripts/update_report.py), and **(e)** for the
   MCP servers the pinned `@<sha>` ref in [`.mcp.json`](../.mcp.json) (`blender_mcp` / `freecad-mcp`).
3. Run the gates, with a smoke render of that pack's modality.
4. Commit (`chore(deps): bump <pack> to <sha> after re-audit`) + `CHANGELOG` entry.

## 4 · Models — *the quality lever; quarterly review*
Models are what most affect output quality, and there's no API for "is there a better one" — so the
weekly report carries a **quarterly** reminder to review [`docs/CATALOG.md`](CATALOG.md):
1. For each modality (image / video / audio / 3D / the VLM judge), has a clearly better model shipped?
   (Watch Comfy-Org, the model orgs, and ComfyUI release notes.)
2. If so: download it (per CATALOG's destination), **smoke-test it head-to-head** against the current
   default on a few representative prompts.
3. Swap the default **only if it's clearly better** (quality / VRAM / speed). Licensing isn't a
   selection constraint here (personal use) — pick the best fit.
4. Update `docs/CATALOG.md` (the new entry + why), `docs/STACK.md` (the default), and the relevant
   `modules/<name>/models.md` / `brand.yaml` defaults. Weights are never committed.

---

### Why report-only (no auto-bumping pins)
Auto-bumping a node-pack pin would defeat the pin-and-audit policy: a pinned commit is a promise that
*that exact code was read and cleared*. The job's role is to **tell you when to look**, not to pull
unreviewed third-party code into the graph. Convenience never outranks that for code that executes
inside ComfyUI with your privileges.
