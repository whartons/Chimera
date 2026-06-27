# Changelog

All notable changes to Chimera are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Docs
- **Field-tested technique notes from production use** (brand-neutral; technique only, no brand data):
  a creator-assets recipe doc [`modules/image/recipes.md`](modules/image/recipes.md) (platform
  emotes/stickers — GIF-not-APNG, background-cutout + dark-outline for light/dark legibility,
  matched-seed keyframes for real animation; tiered badge sets); an image-to-video **motion-realism**
  caveat in [`modules/video/README.md`](modules/video/README.md) (i2v reliably animates *energy/
  ambient* motion over a rigid subject, not mechanical/articulated motion); a **3D-print/casting**
  prep note in [`modules/threed/README.md`](modules/threed/README.md) (prefer one watertight solid
  over a kit-of-parts; clean Hunyuan's stray background plane); and a **FLUX.2 relight** technique in
  [`modules/image/README.md`](modules/image/README.md) (native `ReferenceLatent` edit preserves
  composition where img2img drifts it — `ReferenceLatent` confirmed present on 0.26.2).
- **`--texture` (mesh3d Phase 4a) live-validated end-to-end** on the upgraded stack (concept →
  Hunyuan3D → front albedo bake → judge → refine; self-corrected 0.42 → 0.65, front-faithful with a
  grey back by design — `--finalize` adds all-around colour). `modules/agent/self-correction.md`
  updated from "pending a ComfyUI run" to validated.

## [0.3.0] - 2026-06-27

The agent layer moves to **Qwen3** (Ollama-unified) and the reference stack to **ComfyUI 0.26.2** /
**FreeCAD 1.1.1** — and the **CAD self-correction loop now runs end-to-end** (three masked bugs fixed,
live-validated PASS at score 1.0). All four generative modalities re-smoked on the new stack.

### Changed
- **Agent layer upgraded to Qwen3 (Ollama-unified).** The self-correction judge is now
  **Qwen3-VL-8B-Instruct** served by **Ollama** over the OpenAI-compatible `--backend api` path
  (recommended; `qwen3-vl:8b-instruct` — the **non-thinking** Instruct tag, swappable to
  `:32b-instruct` by env/flag — `CHIMERA_JUDGE_MODEL`);
  the CAD codegen + prompt-rewriter text roles target **Qwen3.6-27B** on the same endpoint. The
  `1038lab/ComfyUI-QwenVL` node is demoted to an **optional** judge path (re-pointed to Qwen3-VL) and
  dropped from the auto-checked pin table. Cloud (OpenAI/Anthropic/Gemini/OpenRouter) stays a drop-in
  via the same config; `.env.example` documents the per-role + lesser-GPU/cloud knobs. `--backend local`
  remains the default and now drives the optional ComfyUI Qwen3-VL node. (Old Qwen2.5 models retired.)
- **ComfyUI reference build → 0.26.2** (was 0.24.1). Full per-modality smoke on the new Desktop build:
  `chimera doctor` clean (all workflow-template node types resolve), **image** + **CAD** self-correction
  loops **PASS** (score 1.0), **video** (LTXVideo i2v → `.mp4`) and **audio** (ACE-Step music → `.mp3`)
  generate, torch 2.10+cu130 intact. `≥0.24.x` floor unchanged. Synced `docs/STACK.md` +
  `scripts/update_report.py` `COMFY_REF`.

### Fixed
- **CAD self-correction loop now passes end-to-end** (`auto_generate.py --pipeline cad --backend api`).
  Three independent bugs each blocked the loop on the upgraded stack; live-validated PASS (score **1.0**,
  iter 0) on “a single solid cylinder 40mm diameter and 60mm tall” after all three:
  1. **Render was near-black.** The Blender studio rig (`workflows/templates/blender/_common.py`) had a
     fixed light/floor scale tuned for ~2-unit Hunyuan meshes; CAD STLs import at mm magnitude (40–60
     Blender units), so inverse-square falloff left the render almost black and the judge correctly scored
     it 0.0. `studio()`/`floor()`/`frame_object` now scale the rig to the object's radius, and `mesh_eval`
     gives material-less imports a neutral clay so Cycles doesn't render them flat.
  2. **Judge miscounted the contact sheet.** The 3D/CAD judge sees a 2×2 montage of 4 orbit (turntable)
     views; nothing told the VLM that, so it read “four cylinders” and failed *“a single …”* on every
     criterion. A count-agnostic `CONTACT_SHEET_PREAMBLE` is now prepended to the 3D rubric (2D image path
     unchanged).
  3. **Judge model was a *thinking* tag.** `qwen3-vl:8b` (thinking) spends the whole `max_tokens` budget on
     its `reasoning` field and returns **empty content** → the judge silently scored every render 0.0. The
     default judge tag is now the documented **non-thinking** `qwen3-vl:8b-instruct`, and `LLMClient.chat`
     now raises a clear error on empty content (names the thinking-model cause + the `-instruct` fix)
     instead of failing silently.
- **FreeCAD 1.1.x cad-job compatibility.** The headless `cad` runner passed the params file as a trailing
  CLI argument; FreeCAD 1.1.x now opens any trailing file as a *document* (a `.json` routes to the FEM
  YAML/JSON mesh importer and throws `AttributeError`), polluting stderr + the CAD loop's revise feedback.
  The runner now hands the params path via the **`$CHIMERA_CAD_PARAMS` env var** (templates read it; sys.argv
  fallback retained). Verified on FreeCAD 1.1.1: `script_exec.py` exports + emits its manifest, no import
  crash. (Full live test on the upgraded stack: ComfyUI 0.26.2 image loop PASS + CAD loop PASS, both with
  the Ollama Qwen3-VL-8B-Instruct judge.)

## [0.2.2] - 2026-06-25

### Changed
- **Dependency pins — weekly re-audit (2026-06).** Merged Dependabot **#33** (`actions/checkout`
  v6→v7, CI green). Bumped, after re-auditing each diff per [`docs/UPDATING.md`](docs/UPDATING.md):
  **ComfyUI-LTXVideo** `229437c → 4f45fd6` (additive — LTX-2.3 example workflows + a benign
  audio-only node + a one-line param max); **comfyui-mcp** `0.9.4 → 0.18.0` (not malicious — the new
  Comfy Cloud / Civitai-MCP / auth-header / Claude-Agent-SDK capabilities are all opt-in, env-gated
  or `optionalDependencies` omitted via `NPM_CONFIG_OMIT=optional`; `postinstall` only copies a
  settings template; existing per-tool gates re-verified, no new high-risk tool); **blender_mcp**
  `03004fd → 98b0e49d` (a docs-only commit past `v1.0.0`). Synced `docs/STACK.md`, `docs/CATALOG.md`,
  the module `models.md`/`requirements.md`/READMEs, `.mcp.json`, and `scripts/update_report.py`.

### Docs
- **README restructured** for a public audience: merged the two duplicate quickstarts into one, replaced
  the 10-bullet "What's here today" wall with a single **Capabilities** table, added a one-row "every
  modality" sample strip (image/video/3D/Blender/CAD), moved the per-role codegen/judge/rewriter endpoint
  reference out to `modules/agent/self-correction.md` (a one-line pointer remains), de-duplicated
  reproducibility (previously stated 3×), and trimmed editorial hype — ~342 → ~236 lines, no facts dropped.
- **README polish + licensing clarity** (post-v0.2.1 public-launch pass): separated each showcase image
  from its caption so captions render *below* the image instead of inline to its lower-right;
  de-duplicated the "runs standalone" claim; fixed a malformed bold span in the agent bullet; and added
  the missing `--subject` to the per-role-endpoint example. The **License** section now scopes MIT to
  Chimera's own code and points to the driven apps'/bridges'/models' own licenses; `docs/STACK.md`
  records ComfyUI's **GPL-3.0**; `docs/CATALOG.md` clarifies the MCP **"Bridge license"** column is the
  server's, not the host application's (FreeCAD itself is **LGPL-2.1**).
- **Doc-accuracy fixes:** `modules/image/models.md` now notes the Z-Image base checkpoint is published
  upstream as `z_image_turbo_bf16.safetensors` and must be **renamed** to `z_image_bf16.safetensors` (the
  name the `base`/`product` graphs load); dropped the incorrect "(Klein)" from the FLUX.2 **[dev]**
  heading; corrected the CI test count to **503 local / 496 in CI / 7 `[images]`-gated** in
  `docs/STACK.md` and `CLAUDE.md`.

## [0.2.1] - 2026-06-15

A maintenance release: fixes the 3D auto-repaint texture bake (it produced an empty atlas on real,
GLB-imported meshes) and illustrates the v0.2.0 DCC/CAD features with brand-neutral sample renders
across the module docs.

### Fixed
- **3D auto-repaint texture bake produced a near-empty (black) atlas on real meshes.** `bake_multiview`
  and `bake_albedo` ran `smart_project` on the mesh exactly as imported from GLB — but glTF/GLB import
  splits a vertex per face-corner, so the surface had no shared edges and the unwrap made every face its
  own sub-pixel island, baking to ~nothing. They now **weld coincident verts + recompute normals before
  unwrapping** (`_common._weld_for_bake`), restoring real, packable islands (a textured robot mesh went
  from ~0% to ~44% atlas coverage). The bake engine had only ever been validated on a clean primitive
  sphere (already-shared verts), which never exercised the split-mesh path.

### Docs
- Added brand-neutral **sample renders to every modality README** (image, 3D, Blender turntable, CAD,
  video) plus a "concept → 3D mesh → auto-repaint texture" showcase in the main README — the DCC/CAD
  features that shipped in v0.2.0 were previously unillustrated.
- Corrected four post-v0.2.0 staleness spots that still described shipped features as roadmap/unbuilt:
  `modules/cad/README.md` dropped **in-loop finalize** from "Still roadmap" (it ships as `--finalize`);
  `modules/agent/self-correction.md` now states the **LLM-driven expander** (`LLMExpander`,
  `--rewrite-prompts`) ships alongside `TemplatedExpander` and that the Phase-4b auto-repaint
  view-generator is shipped (not deferred); `modules/threed/README.md` scopes "not part of this module"
  to **in-ComfyUI** Hunyuan3D-Paint and points to the shipped Blender multi-view bake.

## [0.2.0] - 2026-06-15

The **DCC/CAD hub** release: Chimera grows from a ComfyUI-only pipeline into an agentic generative +
Digital Content Creation / CAD hub — ComfyUI, Blender, and FreeCAD under one self-correcting, MCP-driven
agent layer — plus a provider-agnostic, per-role LLM backend. Repo renamed `ComfyUI-Chimera` → `Chimera`.

### Added
- **Per-role LLM endpoints + LLM prompt rewriter** — the self-correction loop's three roles (codegen /
  judge / rewriter) can each use their own OpenAI-compatible endpoint/model, falling back to the shared
  `--llm-*` / `CHIMERA_LLM_*`. New flags `--codegen-*`, `--judge-*`, `--rewriter-*`, `--rewrite-prompts`
  (+ `CHIMERA_CODEGEN_*` / `_JUDGE_*` / `_REWRITER_*`), resolved **specific-wins** by `client_for_role`.
  New `LLMExpander` rewrites prompts from the judge's FIX feedback (seeded by, and falling back to, the
  templated expander — non-fatal). Lets a strong code-specialist pair with a separate vision judge (no
  single multimodal model required; no GPU needed if hosted). **An AI agent driving interactively
  supersedes all of this** — these endpoint settings only affect unattended runs (see the README
  "How the AI roles work" section).
- **Phase 4b in-loop finalize — `auto_generate.py --pipeline mesh3d --finalize`** — the
  self-correction loop now textures its *winning* mesh automatically: after `run_loop` picks the winner,
  it runs the multi-view **auto-repaint bake** (`scripts/agent/finalize.py:finalize_winner`), re-judges
  the textured result against `build_rubric(textured=True)` (**informational, non-gating** — the shape
  already passed), emits a textured GLB + sidecar, and prints a copy-paste retry command (you decide
  whether to re-roll the texture with a fresh seed). Brand-optional; **mutually exclusive** with
  `--texture` (per-iteration front-albedo). New shared engine `scripts/brandkit/finalize.py`
  (`finalize_params`, `repaint_views`) is used by **both** the `finalize-texture` CLI and the loop;
  `render_generate.py` now **always** writes the winner `.texture.json` (absolute GLB + concept paths
  + seed; the concept is recorded in place, never moved) so the tail can recover the winner. Non-fatal: a texturing/judge hiccup never loses the
  already-good shape. GPU/network-free tests (mocked). Completes the Phase-4b roadmap.
- **Provider-agnostic LLM backend — autonomous AI judge + generative CAD loop** — a vendor-neutral
  `scripts/agent/llm.py` (`LLMClient`) talks the **OpenAI-compatible `/v1/chat/completions`** shape over
  pure stdlib HTTP (no SDK), so it works with **OpenAI, Anthropic's OpenAI-compat endpoint, OpenRouter, or
  a local Ollama/vLLM server** — configured by env (`CHIMERA_LLM_BASE_URL` / `_API_KEY` / `_MODEL`) or
  `--llm-base-url`/`--llm-model`, no hardcoded vendor. Two new autonomous capabilities on `auto_generate.py`:
  - **`--backend api`** — `LLMJudge` judges a render/contact-sheet against the rubric via the LLM (N-pass
    consensus reusing `parse_verdict`/`consensus_verdict`), an alternative to the local Qwen judge for any
    pipeline.
  - **`--pipeline cad`** — fully autonomous **generative CAD**: an LLM writes/revises a FreeCAD script
    (`LLMCadGenerator`) → `cad --mode script` → Blender contact-sheet render → judge → fold FIX feedback
    back → revise, reusing the model-free `run_loop`. `--pipeline cad --backend api` needs no ComfyUI at
    all. The loop execs LLM-authored scripts, so they run with a **host-side denylist + restricted builtins
    + an import allowlist** (`script_exec.py restrict=True`) — a best-effort speed bump, **not** a security
    boundary (FreeCAD's own file I/O is still reachable; point it only at an LLM you trust). No new hard
    dependency (stdlib HTTP); CI stays GPU/network-free (mocked). **Live-validated 2026-06-15** against a
    local Ollama endpoint: `--backend local` + `qwen2.5-coder` drove a mounting-bracket loop FreeCAD STL →
    Blender render → Qwen-VL judge → fail → revise → PASS; the `LLMJudge` vision path was confirmed against
    `qwen2.5vl`. (Validation also surfaced + fixed five real CAD-loop bugs — see the CAD-loop fix entry.)
- **Phase 4b auto-repaint — all-around 3D texture, end to end** — `generate.py finalize-texture
  --auto-repaint --concept <img> --subject "..."` now *generates* the corrected views instead of needing
  them supplied: it renders a per-view **depth map** (`workflows/templates/blender/render_views.py` — an
  emission depth material, no compositor), then runs an **SDXL depth-ControlNet + IPAdapter** repaint per
  view (`scripts/brandkit/repaint.py`, `repaint.generate_views`) — the ControlNet locks each view's
  geometry to its depth while IPAdapter carries the concept's identity — and bakes the N corrected views
  into one atlas via the shipped `bake_multiview`. Uses the audited **cubiq `ComfyUI_IPAdapter_plus`
  @ `a0f451a`** + `ip-adapter-plus_sdxl_vit-h` + `CLIP-ViT-H-14` + `xinsir/controlnet-depth-sdxl-1.0`
  (all pinned; see CATALOG). Tunable `--cn-strength`/`--ip-weight`/`--views-count`; sidecar records the
  auto-repaint provenance. **Live-validated on the RTX 5090:** an armored-rover mesh textured green/tan
  **all the way around** (vs Phase-4a's flat palette back). This completes the Phase-4b roadmap item; the
  manual `--views` mode is unchanged. **Polish:** each repainted view is masked to its depth silhouette
  before baking (the concept's background no longer bleeds onto edges), and views after the first add a
  second IPAdapter pass on the previous painted view (`prev_weight`) for **cross-view consistency**.
- **Generative CAD self-correction — `cad --mode script`** — a third `cad` mode that runs an
  **agent/user-authored FreeCAD Python script** headless (`workflows/templates/freecad/script_exec.py`)
  and exports what it builds to STEP/STL/OBJ. The script runs with `App`/`FreeCAD`, `Part`, `Mesh`, and an
  active `doc` in scope; it builds geometry in `doc` (or sets `RESULT=[objs]`) and the runner owns
  export/emit (rejecting mesh→STEP up front; STEP needs Part/BREP). The `kind:"cad"` sidecar records the
  script name + a content hash so the params signature varies across in-place revisions. This is the lever
  for a **CAD self-correction loop**: brief → agent-authored parametric script → `cad --mode script` →
  `render --mode mesh` → VLM form/printability judge → FIX → agent revises the script → repeat. The
  agent is the script generator when present; a **fully autonomous** code-gen backend ships in the
  "Provider-agnostic LLM backend" entry above (`auto_generate.py --pipeline cad`). **Live-validated:**
  authored a parametric mug, executed it headless, rendered + judged it, then revised the script (roomier
  handle + a BREP rim fillet) and re-ran — a real author→exec→render→judge→revise iteration. The script is
  `exec()`'d unsandboxed in an isolated `FreeCADCmd` process (first-party CLI capability, no network, not
  an MCP tool — run only scripts you authored/audited).
- **All-around 3D texture — multi-view bake engine (Phase 4b)** — `generate.py finalize-texture --from
  <glb> --views front,right,back,left` bakes N corrected views into one albedo atlas so the back/sides
  carry real color (Phase 4a colored only from one front projection). New `_common.bake_multiview`
  generalizes `bake_albedo` from 1 → N views: a ring camera per view, a per-view `world_to_camera_view`
  projection UV (headless-safe), a per-view front-facing weight `max(0,dot(N,-dir))²`, a weighted blend
  `Σ(w·c)/max(Σw,ε)`, and a flat `--back-fill` (`palette`/`grey`) for faces no view sees; EMIT-baked to a
  `--texture-res` atlas, rewired as Base Color, exported as a textured GLB with orbit verification stills.
  New `mesh_finalize.py` template; CLI runs the existing Blender job runner, routes the GLB + a contact
  sheet to `outputs/`, writes a `kind:"render" mode:"finalize-texture"` sidecar (view basenames +
  azimuths). Pure bpy/Cycles — never touches the blocked `custom_rasterizer` path. **Live-validated on
  Blender 5.1.2 / RTX 5090**: a 4-distinct-colour-view bake of a sphere put all four colours in the baked
  atlas (R 13% · G 14% · B 12% · Y 22%), end-to-end CLI routed + sidecared, partial-view back-fill
  confirmed. Views can be supplied manually (artist) — and the **ComfyUI depth-ControlNet + IPAdapter
  auto-repaint** that *generates* the N views from the concept (+ its `render_views` per-view depth pass)
  **now ships**: see the "Phase 4b auto-repaint — all-around 3D texture, end to end" entry above.
- **Headless FreeCAD `cad` subcommand** — `generate.py cad` drives `FreeCADCmd` (GUI-less) as a normal
  CLI subprocess to author and convert CAD geometry, completing FreeCAD's headless path (the peer of the
  Phase-2 Blender render backend; the interactive MCP bridge stays Phase 1). Two modes:
  - `--mode primitive` *(default)*: build a parametric solid — `--shape box|cylinder|cone|sphere|tube`
    with mm dimensions (`--length/--width/--height/--radius/--radius2/--inner-radius`);
  - `--mode convert`: import a CAD/mesh file (`--from` step/stp/iges/igs/brep or stl/obj) and re-export.
  Exports any subset of **STEP / STL / OBJ** (`--formats`, default `step,stl`) — STEP is the BREP
  authoring Blender can't do; glTF is GUI-only in FreeCAD, so STL is the bridge into `render --mode mesh`.
  Job runner `scripts/brandkit/freecad.py` (params via a temp JSON file — `FreeCADCmd` has no `--`
  separator; mockable `_runner` seam for GPU-free CI), templates in `workflows/templates/freecad/`
  (`_common`/`primitive`/`convert`), `kind:"cad"` reproducibility sidecar (`sidecar.build_cad_meta`),
  friendly host-side validation (formats, positive dims, tube bore, cone tip, convert source allowlist,
  mesh→STEP refusal). STEP/IGES/BREP outputs route to `outputs/3d/`. **Live-validated on FreeCAD 1.1.1**
  (tube `solids:1` STEP+STL, STEP→STL convert, end-to-end CLI routing + sidecar). The autonomous FreeCAD
  self-correction loop (`cad → render → judge → revise`) ships as `auto_generate.py --pipeline cad` — see
  the "Provider-agnostic LLM backend" entry above.
- **3D albedo texturing (Phase 4a)** — `auto_generate.py --pipeline mesh3d --texture` restores color to
  the 3D self-correction loop via a headless Blender bake (pure bpy/Cycles — never touches the blocked
  `custom_rasterizer` path). `_common.bake_albedo()` smart-UV-unwraps the mesh, projects the concept
  image from a front camera (computed with `world_to_camera_view` — headless-safe, since
  `uv.project_from_view` needs a VIEW_3D region), shader-masks front faces vs a flat **`--back-fill`**
  (`palette` = brand color, default; `mirror` = back-projected flipped concept), and EMIT-bakes a
  `--texture-res` albedo atlas; `mesh_eval` assigns it as Base Color, renders colored stills, and
  exports a self-contained **textured GLB**. The 3D rubric regains color/palette criteria via a
  **thrash-safe** wording (`build_rubric(..., textured=True)` — "a plain or palette-filled back is
  acceptable", so the loop never chases back texture a single front image can't produce); a
  `<stem>.texture.json` sidecar records the textured status + GLB name. **Live-validated on Blender
  5.1.2 / RTX 5090** (front-faithful projection, palette + mirror back-fills, embedded GLB — the smoke
  caught and fixed the headless `project_from_view` bug); the full `--texture` loop end-to-end is
  pending a ComfyUI run. Generated all-around texture (Phase 4b — depth-ControlNet multi-view repaint on
  the winning mesh) **now ships** (see the Phase-4b entries above); in-ComfyUI Hunyuan3D-Paint stays
  wheel-blocked.
- **3D self-correction over Blender renders (Phase 3)** — `auto_generate.py --pipeline mesh3d`
  extends the self-correction loop to 3D: a brief becomes a concept image (txt2img, or `--from-image`
  to fix the concept and reroll only the mesh), the concept becomes a Hunyuan3D mesh, the mesh is
  rendered headlessly to a **4-view contact sheet** (new `workflows/templates/blender/mesh_eval.py`),
  and a **form** rubric (`build_rubric(..., modality="3d")`) is judged on the grey-clay render. A new
  `GeometryAwareJudge` folds **deterministic bmesh geometry checks** into the verdict: `mesh_eval`
  records non-manifold/open edges, loose parts, tri-count and bounds in a `.checks.json` sidecar, and
  `structural_issues` force-fails only the gross, VLM-invisible defects — an **empty/degenerate mesh**
  or one **fragmented into many islands** (`DEFAULT_MAX_LOOSE_PARTS`, tunable). It does **not** fail on
  non-manifold or open edges: raw Hunyuan3D output is inherently ~34% non-manifold (baseline for
  surface-net extraction), so gating on those rejected every real mesh. The model-free loop core,
  `parse_verdict`, the expander, and `ConsensusJudge` are reused unchanged; the loop's per-iteration
  seed advance gives an implicit mesh reroll. Host-side contact-sheet montage in
  `scripts/brandkit/montage.py` (Pillow, optional `[images]` extra). GPU-free CI (mocked ComfyUI
  client + Blender runner). **Live-validated end-to-end on Blender 5.1.2 / RTX 5090 (2026-06-14):** the
  full autonomous loop (Z-Image → Hunyuan3D → `mesh_eval` → real **Qwen2.5-VL** judge + geometry gate)
  returned **PASS 0.95** on an armored-rover mesh, and `--texture` produced a front-faithful red/gold
  knight helmet. That first live run is what exposed the over-strict geometry gate (recalibrated above);
  an earlier `mesh_eval` smoke had caught + fixed a glTF vertex-split topology bug.

  **Roadmap:** Texturing (now shipped as Phase 4a above; all-around generative texture is Phase 4b);
  and FreeCAD headless self-correction.
- **Headless Blender render backend (Phase 2)** — `generate.py render` shells to
  `blender --background --python` with parameterized `bpy` templates from
  `workflows/templates/blender/`, backed by a job runner in `scripts/brandkit/blender.py`.
  Three modes, all live-validated on Blender 5.1 / RTX 5090:
  - `--mode mesh` *(default)*: import a mesh (GLB/STL/OBJ) → studio look → Cycles → hero PNG
    (+ `--turntable` MP4);
  - `--mode comfy-scene`: ComfyUI image → emissive backdrop + reflective floor + focal object →
    Cycles render (the ComfyUI → Blender handoff);
  - `--mode finish`: AI mesh → clean → optional `--watertight` voxel remesh → decimate
    (`--target-tris`) → optional `--scale-mm` → material (or `--color project`) → export
    STL/GLB (+ hero render) — the figurine/character-finish pipeline for print-ready output.
  Brand-aware (routes to `brands/<brand>/outputs/` + `kind:"render"` sidecar). Runs as a normal
  CLI subprocess — **no per-call MCP approval** (unlike the interactive bridge's gated
  `execute_blender_code`). CI tests mock the subprocess; GPU-free. Requires Blender ≥ 5.1 on PATH
  or `$BLENDER_BIN`; Cycles GPU (OptiX/CUDA); MP4 via Blender's bundled FFmpeg. (Phase 3 — VLM
  self-correction over these renders — shipped; see above. **FreeCAD headless `cad`** is now shipped too
  — see above.)
- **DCC/CAD bridges (Phase 1)** — assistant-driven MCP bridges to **Blender** (official Blender
  Foundation `lab/blender_mcp` @ `03004fd`, GPL-3.0, loopback :9876) and **FreeCAD**
  (`neka-nat/freecad-mcp` @ `63acb30`, MIT, loopback :9875), repositioning Chimera as a generative +
  DCC/CAD orchestration hub. Both are **pinned, from-source audited, and per-tool gated** (Tier-1
  code-exec tools require per-call approval — guarded by `tests/test_mcp_gates.py`). New
  `modules/blender/` + `modules/cad/` docs; weekly pin checks extended to Blender's Gitea
  (`check_gitea_pack`) and FreeCAD's GitHub repo (existing `check_git_pack`) in
  `scripts/update_report.py`. **Interactive only** — headless automation + 3D/CAD self-correction
  are roadmap (Phase 2–3).

### Fixed
- **Autonomous CAD loop now works end-to-end with a real LLM** (`auto_generate.py --pipeline cad`). The
  first live runs (Ollama `qwen2.5-coder` / `qwen2.5vl`) surfaced five real defects the GPU/network-free
  mocked tests could not catch: (1) `script_exec.py` now wraps raw `Part.Shape`/`Mesh` entries from
  `RESULT` into doc objects (LLMs naturally write `RESULT = [shape]`), checking `isinstance(Part.Shape)`
  **before** `isDerivedFrom` (raw shapes also expose `isDerivedFrom`); (2) `_common.export_shapes`
  tessellates Part shapes via **`MeshPart`** for STL/OBJ — headless `Mesh.export` does not mesh a
  `Part::Feature`; (3) `freecad.run_template` surfaces **stderr** in the no-manifest error so the loop's
  revise step can self-correct (FreeCAD prints script errors to stderr while exiting 0); (4) `App` added
  to the restricted-exec import allowlist (FreeCAD's universal alias, which `script_exec` injects); (5) the
  codegen prompt now pins the FreeCAD API (`App.Vector`, never `Part.Vector`; `Part.makeBox`…). Validated
  live: `--backend local` + `qwen2.5-coder` drove a mounting-bracket loop FreeCAD STL → Blender render →
  Qwen-VL judge → **fail → revise → PASS**; the `--backend api` `LLMJudge` vision path was confirmed
  against `qwen2.5vl`.

### Changed
- **3D self-correction geometry gate recalibrated for real Hunyuan3D output.** The first end-to-end live
  run (Z-Image → Hunyuan3D → real Qwen2.5-VL judge, **PASS 0.95** on an armored rover) showed raw
  Hunyuan3D meshes are inherently ~34% non-manifold (confirmed at zero weld) — baseline for surface-net
  extraction, not a defect — so the old `structural_issues` (fail on any non-manifold/open edge)
  force-failed *every* real mesh, overriding even a 0.95 form score. It now fails only on
  **empty/degenerate** meshes or ones **fragmented into many islands** (`DEFAULT_MAX_LOOSE_PARTS`,
  tunable); non-manifold/open edges stay in the `.checks.json` sidecar for provenance. `--texture` was
  likewise validated live (front-faithful red/gold knight helmet).

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

[Unreleased]: https://github.com/whartons/Chimera/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/whartons/Chimera/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/whartons/Chimera/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/whartons/Chimera/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/whartons/Chimera/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/whartons/Chimera/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/whartons/Chimera/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/whartons/Chimera/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/whartons/Chimera/releases/tag/v0.1.0
