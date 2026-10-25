# `cad` — parametric CAD bridge

![A shrouded fan rotor with 18 twisted blades, built by a FreeCAD script and rendered in Blender](../../docs/images/chimera-sample-cad.png)

*Script-mode part: [`examples/turbofan.py`](examples/turbofan.py) (18 lofted blades twisting from 55° at the root to 25° at the tip, fused to a hub, spinner and shroud) run with `chimera cad --mode script` → STEP/STL, rendered headless in Blender. Brand-neutral sample.*

This module is the glue that lets an AI assistant **drive a live FreeCAD session**:
create and edit parametric solids, run FEM simulations, export STEP/STL/glTF, and
introspect the document model — all from an MCP tool call. The scope here is
**interactive only**: the assistant connects to a running FreeCAD GUI instance over a
loopback XML-RPC bridge, reads and edits the document, and fires exports into a folder
you choose. For unattended geometry authoring there is a **second, headless path** —
**`generate.py cad`** (see [below](#headless-generatepy-cad-shipped)) — that drives
`FreeCADCmd` as a normal CLI subprocess, and a **FreeCAD-driven self-correction loop**
(`cad → render → judge → revise`, both assistant-authored and fully autonomous via an LLM).

## The MCP bridge

| | |
|---|---|
| **Server** | `neka-nat/freecad-mcp` (GitHub) |
| **Pinned** | commit `78bf023` (v0.1.27) — server + addon share the commit |
| **License** | MIT · runs 100% locally (loopback XML-RPC `127.0.0.1:9875`) |
| **Transport** | stdio (Claude launches it) → XML-RPC → FreeCAD addon |
| **Tools** | 17: parametric object ops, FEM, doc/view introspection, dispatch health, async-job status, code-exec (GUI + headless) |

> **Security floor: v0.1.25.** Earlier versions (≤ 0.1.24) are affected by
> [GHSA-v4pw-r6h3-v75q](https://github.com/neka-nat/freecad-mcp/security/advisories/GHSA-v4pw-r6h3-v75q)
> (HIGH): while the RPC server runs, any web page open in a local browser can make FreeCAD run
> arbitrary Python. v0.1.25+ refuses browser-originated requests. Update **both halves** (the
> `uvx` pin and the addon in FreeCAD's `Mod/`), and run **FreeCAD 1.1.4+**: earlier releases have
> HIGH advisories triggered by opening a crafted `.FCStd` file
> ([FreeCAD advisories](https://github.com/FreeCAD/FreeCAD/security/advisories)).

> **Why `neka-nat/freecad-mcp` and not the alternatives?** It is the de-facto
> community standard: actively maintained, MIT, no telemetry, and ~17 tools
> including FEM via CalculiX. Rejected alternatives in brief:
> `contextform/freecad-mcp` has the best install UX and a guard-railed 45-tool
> surface, but code has been quiet for approximately 10 months; `jango-blockchained/mcp-freecad`
> is the only fork with a Mock backend for CI and a headless launcher, but
> `execute_script`/`ide_integration` are unsandboxed RCE, and it has a single quiet
> maintainer with no releases; `bonninr/freecad_mcp` is effectively unmaintained
> for approximately 15 months.

## Activate it

Prerequisites: **[Astral `uv`](https://docs.astral.sh/uv/)** installed and on your
`PATH`; **FreeCAD 1.1.4 or newer** (it bundles Python 3.11; older releases have open security advisories).

1. **Install the FreeCAD addon.** Copy the **whole** `addon/FreeCADMCP/` directory from the
   pinned commit `78bf023` into FreeCAD's user `Mod/` directory (`package.xml` is required: the
   addon reads its version from it at import). **FreeCAD 1.1 uses a versioned data dir** — on
   Windows that is `%APPDATA%\FreeCAD\v1-1\Mod\FreeCADMCP\` (1.0 omits the `v1-1`). If unsure,
   use **Tools → Open user data directory** in FreeCAD and copy into the `Mod/` there. When
   replacing an older copy, keep any backup **outside** `Mod/` (FreeCAD imports every folder in
   it, and a second copy breaks the workbench). Fully restart FreeCAD.

2. **Start the RPC server.** In FreeCAD, select the **"MCP Addon" workbench** from
   the workbench drop-down. Click the **"Start RPC Server"** toolbar button — this
   binds the loopback listener at `127.0.0.1:9875`. Auto-start is opt-in and
   **default OFF**; the server is only exposed when you click this button.

3. **Register the MCP server.** The server entry lives in
   [`../../.mcp.json`](../../.mcp.json) and is launched by Claude Code as:
   ```
   uvx --from git+https://github.com/neka-nat/freecad-mcp@78bf0230a03324b56c9a0b7f55150fb5be2a0d42 freecad-mcp --host 127.0.0.1
   ```
   Optional hardening (v0.1.25+): set a shared secret with the addon's **"Set Auth Token"**
   command and pass the same value to the server through the `FREECAD_MCP_TOKEN` environment
   variable (or `--auth-token`). Off by default.

4. **Approve and confirm.** In Claude Code run **`/mcp`** and approve the `freecad`
   server (project-scoped servers require a one-time approval). Confirm: `/mcp`
   should show `freecad` **Connected** with 17 tools. Smoke-test by calling
   `get_objects` or `list_documents` (Tier 3, read-only) — either should return the
   active FreeCAD document's contents, proving the bridge reached the addon.

## Headless `generate.py cad` (shipped)

The MCP bridge is GUI-only (all work is marshaled onto FreeCAD's Qt thread; the RPC
server starts from a toolbar button). For **unattended geometry authoring**, use the
headless `cad` subcommand instead — it shells `FreeCADCmd <template.py>` as a normal CLI
subprocess (no per-call approval), handing the params-JSON path via the
`$CHIMERA_CAD_PARAMS` env var (FreeCAD 1.1.x opens a trailing file argument as a
document, so params never ride argv), exactly as `generate.py render` does for Blender. Runner: [`../../scripts/brandkit/freecad.py`](../../scripts/brandkit/freecad.py);
templates: [`../../workflows/templates/freecad/`](../../workflows/templates/freecad/).

```bash
# author a parametric solid -> STEP (BREP) + STL
python scripts/generate.py cad --shape tube --radius 12 --inner-radius 8 --height 30 --formats step,stl

# box / cylinder / cone / sphere are the other shapes (mm dimensions, sane defaults)
python scripts/generate.py cad --shape cone --radius 20 --radius2 0 --height 40

# convert an existing CAD/mesh file between formats
python scripts/generate.py cad --mode convert --from part.step --formats stl,obj

# run an agent/user-authored parametric script (generative CAD)
python scripts/generate.py cad --mode script --script mug.py --formats step,stl
```

- **Shapes:** `box` (`--length/--width/--height`), `cylinder` (`--radius/--height`),
  `cone` (`--radius/--radius2/--height`; `radius2 0` = sharp tip), `sphere` (`--radius`),
  `tube` (`--radius/--inner-radius/--height`; bore must be `< radius`).
- **Formats** (`--formats`, default `step,stl`): any subset of **`step`, `stl`, `obj`**.
  `FreeCADCmd` emits **geometry only**; STEP is the BREP/parametric format Blender can't
  read, so `cad` is how you produce it. **glTF is GUI-only in FreeCAD** — export STL and
  hand it to `render --mode mesh` for a Cycles render/turntable, or `render --mode finish`
  for a print-ready figurine (the STL keeps its mm unless you resize it with `--scale-mm`). That STL → Blender hop is also the render-for-judge route the
  CAD self-correction loop uses (see `--mode script` below).
- **Binary:** resolved from `--freecad-bin`, `$FREECAD_BIN`, `FreeCADCmd`/`freecadcmd` on
  PATH, then the default Windows install (`C:\Program Files\FreeCAD *\bin\FreeCADCmd.exe`).
- Outputs route to `brands/<brand>/outputs/3d/` (or `outputs/3d/` brandless) with a
  `kind:"cad"` reproducibility sidecar (template, resolved dims/formats, params signature,
  FreeCAD version, pipeline git sha). All of one job's files (the STEP and the STL, say) share one name,
  picked free in every folder they go to; a later job with the same seed keeps the earlier one and takes
  `<name>_2`, then `_3`, ….

### `--mode script` — generative CAD self-correction

`--mode script --script <file.py>` runs an **agent/user-authored FreeCAD Python script** headless and
exports what it builds. The script runs with `App`/`FreeCAD`, `Part`, `Mesh`, and an active `doc` in
scope; it builds geometry as objects in `doc` (or sets `RESULT = [objs]`), and the runner owns
export/emit. Without `RESULT` the runner exports only the finished objects, not the inputs of a boolean (a Cut's base
and tool) or sketches; set `RESULT` to export anything else (a part and its mirrored copy, say). STEP export needs **Part (BREP)** objects — a `Mesh::Feature` exports to `stl`/`obj` only
(the runner rejects mesh→STEP with a clear message). The sidecar records the script name + a content
hash, so the `params_signature` varies across in-place revisions.

This is the lever for a **CAD self-correction loop**: a brief → a parametric script → `cad --mode script`
→ `render --mode mesh` → a VLM judges the form/printability → FIX feedback → **revise the script** →
repeat. It runs two ways:

- **Assistant-authored** — when an agent (e.g. Claude Code) is present it writes/revises the script by
  hand. Live-validated by authoring a parametric mug, executing it headless, rendering + judging it, then
  revising (roomier handle + a BREP rim fillet) and re-running — a real author→exec→render→judge→revise
  iteration.
- **Fully autonomous** — **`auto_generate.py --pipeline cad --subject "..."`**: a **provider-agnostic
  LLM** (`scripts/agent/llm.py` — any OpenAI-compatible endpoint: **Gemini / OpenAI / Anthropic /
  OpenRouter / local Ollama**, configurable via `CHIMERA_LLM_*`) writes + revises the script across
  iterations. It runs with **no configuration**: code-gen is **Qwen 3.8 27B** on a local Ollama in every GPU
  tier, and the judge is `--backend api`, the default, on the tier's local model (Qwen 3.8 27B on 32 GB+ cards, a
  Qwen3-VL 8B or 4B on smaller ones; `--llm-tier` to choose). `--backend local` uses the optional ComfyUI
  Qwen3-VL judge node instead. With `--backend api` it's a pure LLM+FreeCAD+Blender loop (no ComfyUI). See
  [`../agent/self-correction.md`](../agent/self-correction.md#local-models-by-gpu-tier) for the tiers and
  the code-gen measurements, and
  [its provider table](../agent/self-correction.md#bring-your-own-llm---backend-api----pipeline-cad).
  (Built + **live-validated** against a local Ollama endpoint.)

**Per-role endpoints (autonomous runs only; an interactive AI agent needs none of this).** Codegen
(`--codegen-*` / `CHIMERA_CODEGEN_*`) and the judge (`--judge-*` / `CHIMERA_JUDGE_*`) each take their own
OpenAI-compatible endpoint, falling back to the shared `--llm-*` / `CHIMERA_LLM_*`, then to the GPU tier's
local model. Model & hardware setups:

| Setup | Codegen | Judge | GPU |
|-------|---------|-------|-----|
| Interactive (IDE agent) | the agent | the agent | none (FreeCAD/Blender local) |
| No GPU, hosted API | `--llm-base-url <host> --llm-model <model>`: a hosted multimodal model (Gemini free tier / GPT-4o / Claude) | same model | none |
| Mixed | `--codegen-base-url <host> --codegen-model <coder>` strong hosted coder | `--backend api` the tier's local judge (4.4–16.5 GB) | judge GPU only |
| Fully local (the default, nothing to set) | Qwen 3.8 27B on Ollama, in every tier (partly on the CPU below 24 GB) | `--backend api` the tier's local judge, or `--backend local` ComfyUI Qwen3-VL node | per tier |

Codegen quality drives success. The first live run (2026-06) found a 7B *coder* gets a mounting bracket to a
pass where a 7B *vision* model does not; on the 2026-10 six-part test, Qwen 3.8 27B built 5, a 27B coding
model 4, and a 9B none of the 3 it tried. The loop self-corrects from the FreeCAD error it feeds back, so a
strong coder recovers in a couple of iterations.

**What code-gen is told when it revises.** After a failed judgement, code-gen gets the subject plus the
judge's feedback: the expander's FIX directives, an `Avoid: …` line with the judge's "avoid" terms, and a
`The judge found: …` list of its NOT-MET reasons (so "hook arm 2 mm thick, fragile. FIX: avoid thin hook arm"
arrives as both). When the previous script failed in FreeCAD, its error follows (`The previous script
failed: …`), and it stays until code-gen has actually seen it, so a code-gen failure (an LLM error) in
between doesn't lose it.

> ⚠️ **`--mode script` `exec()`s the script unsandboxed** in the `FreeCADCmd` process (no network,
> isolated process, but full Python — same trust as running a FreeCAD macro you wrote). **Run only
> scripts you authored or audited.** The **autonomous** `--pipeline cad` path runs LLM-authored scripts
> with a host-side denylist (which also rejects dunder-attribute walks such as `.__globals__`,
> `.__class__`, `__subclasses__` and frame objects) **plus** restricted builtins + an import allowlist
> (`script_exec.py restrict=True`). Every `cad` job's `FreeCADCmd` also starts without credential-named
> environment variables (any name containing `KEY`, `TOKEN`, `SECRET`, `PASS`, `CREDENTIAL` or `AUTH`, plus
> proxies, webhooks and `*_URL` / `*_URI` connection strings), so a script can't read your API keys, and only
> files in the job's own folder are taken as its output. It is a best-effort speed bump, still **not** a sandbox (Python object
> internals can reach `os`, and FreeCAD's own file I/O is reachable), so point it only at a code-gen model
> you trust. This is a first-party CLI capability, *not* an MCP tool, so the per-tool gates below don't
> apply; the gated MCP `execute_code` is the separate GUI path.

**Still roadmap:** sketch/constraint modeling, FEM headless, and assemblies. Keep a FreeCAD window open
with the addon active for live MCP-assisted editing.

## Security audit (commit `78bf023`) & per-tool gates

**Verdict:** safe-with-precautions — `neka-nat/freecad-mcp` @ `78bf023` (v0.1.27, MIT) has a
clean minimal dep set (`mcp[cli]>=1.28.1,<3`, `validators`) with **no telemetry/Supabase/pickle/torch**
and no outbound network; the sole transport is loopback XML-RPC to FreeCAD on
hardcoded `:9875`, a default `127.0.0.1` bind that flips to `0.0.0.0` only on
explicit user opt-in and is still IP-allowlist-filtered (default `127.0.0.1`) via
`verify_request`. Since v0.1.25 the RPC server also **refuses browser-originated requests**
(any `Origin` header → 403, non-XML content types → 415, and, when bound to loopback, any `Host`
other than localhost → 403, which stops DNS rebinding) — the fix for
[GHSA-v4pw-r6h3-v75q](https://github.com/neka-nat/freecad-mcp/security/advisories/GHSA-v4pw-r6h3-v75q).
The RPC server only starts from a deliberate "Start RPC Server" toolbar button (auto-start
opt-in, default OFF), so nothing is exposed until the user acts. An optional shared-secret
token ("Set Auth Token" + `FREECAD_MCP_TOKEN`) is available and off by default.
`execute_code`/`execute_code_async` run arbitrary Python in FreeCAD (now in a dedicated namespace
rather than the module globals) and stay Tier 1; **`execute_code_headless`** (new) runs
model-supplied Python in a `freecadcmd` subprocess found on PATH, needing neither the GUI nor the
RPC server, so it is Tier 1 as well; `create_object`/`edit_object`/`delete_object` do not eval
property values but present an unbounded `setattr` + `addObject` surface the source can't prove
inert (Tier 1, conservative); `insert_part_from_library` now constrains paths to the library
root (upstream path-traversal fix) and stays Tier 2. Not executed during audit — bind, IP
filter, and browser-request refusal asserted from source.

### Per-tool permission gates

| Tier | Policy | Tools |
|---|---|---|
| **1 — always per-call approval (RCE / unbounded mutation)** | require explicit approval on every call | `execute_code`, `execute_code_async`, `execute_code_headless`, `create_object`, `edit_object`, `delete_object` |
| **2 — approval + path/host allowlist** | require approval; path/host must be explicitly vetted | `insert_part_from_library`, `run_fem_analysis`, `reload_document` (closes and reopens the document, discarding unsaved edits) |
| **3 — auto-allow (read-only)** | frictionless; no side-effects | `create_document`, `get_view`, `get_objects`, `get_object`, `get_parts_list`, `list_documents`, `get_rpc_status`, `get_async_status` |

Gates are enforced in [`../../.claude/settings.json`](../../.claude/settings.json).

### Hard rules

- **Loopback-only binding.** Never enable "Remote Connections" in the FreeCAD MCP
  Addon settings — doing so flips the bind to `0.0.0.0` with IP-filter-only access,
  no auth unless you set a token, and no DNS-rebinding check. Keep **Allowed IPs** = `127.0.0.1`.
- **Approve `insert_part_from_library` paths.** Upstream now confines library paths, but the
  tool still writes into your document; check the path before approving any call.
- **Pin from commit, never floating tag.** Always launch from the pinned git ref
  `78bf023` so the server's own code can't change under you (its Python dependencies, `mcp[cli]` and
  `validators`, still resolve within their ranges when `uvx` installs it). If the addon reports a
  version mismatch and suggests `uvx freecad-mcp@latest`, **don't**: bump the pin (and re-audit) instead.
- **Re-audit on every pin bump.** When the pin is advanced, re-run the full audit
  against the diff before committing. Runbook:
  [`../../docs/UPDATING.md`](../../docs/UPDATING.md).
  Last re-audit: `3745ff9 → 78bf023` (v0.1.22 → v0.1.27, 83 upstream commits) — **bump with
  changes**: the GHSA-v4pw-r6h3-v75q fix, the `insert_part_from_library` path fix, `execute_code`
  namespace isolation, the optional auth token, a server↔addon version handshake, threaded RPC
  and GUI-dispatch timeouts, and two **new tools** (`execute_code_headless`, Tier 1, gated;
  `get_async_status`, read-only). No new network egress; no build hooks. The addon now ships a
  `package.xml` that it reads at import, so **re-copy the whole `addon/FreeCADMCP/` directory
  into FreeCAD's `Mod/` and restart FreeCAD** — the `uvx` pin only refreshes the server half.
  (Prior re-audits: `4c3f2ef → 3745ff9`, `1697aff → 4c3f2ef`, `63acb30 → 1697aff`: clean.)

## Tool surface (highlights)

The server exposes exactly **17 tools**, grouped as:

- **Parametric ops (Tier 1 — mutation):** `create_object`, `edit_object`,
  `delete_object`
- **Documents / introspect (Tier 3 — read-only):** `create_document`,
  `list_documents`, `get_objects`, `get_object`, `get_view`,
  `get_parts_list`, `get_rpc_status`, `get_async_status`
- **Library / FEM / reload (Tier 2 — approval):** `insert_part_from_library`,
  `run_fem_analysis`, `reload_document` (closes and reopens the document, so unsaved edits are lost)
- **Code-exec (Tier 1 — RCE):** `execute_code`, `execute_code_async`,
  `execute_code_headless` (headless `freecadcmd` subprocess; Chimera's own unattended path
  is `generate.py cad --mode script`)
