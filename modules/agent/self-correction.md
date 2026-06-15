# Self-correction loop — generate → judge → refine

The self-correction loop turns Chimera from "**generate once**" into "**iterate to a
passing result**": render a candidate, judge it against a brand/brief rubric, feed the
unmet criteria back into the prompt, regenerate — until a candidate passes or a
max-iteration cap is hit. It is the orchestration layer that sits on top of Brand Kits
generation, distinct from the [MCP bridge](README.md) (which is the assistant→ComfyUI
transport).

## The shared core — `scripts/agent/`

A small, **model-free, judge-agnostic** core (unit-tested with no GPU/ComfyUI). It
reuses the existing `scripts/generate.py` filler/route path. Only the **winning**
render is recorded — with an *agent-run* sidecar (`kind: agent-run`) summarizing the
run (subject, iterations, pass/score, winning seed/prompt). That sidecar is a run
summary, **not** a replayable render sidecar: `generate.py replay` refuses it on the
`kind` discriminator. Per-iteration renders are routed into the brand folder but are
not individually sidecar'd, so the loop is **not** per-iteration replayable.

| Module | Responsibility |
|---|---|
| `rubric.py` | `Rubric` + `build_rubric(manifest, subject)` — composes a scorable checklist from the brand (subject, style, palette, negative). `rubric.as_prompt()` renders the numbered **MET / NOT-MET → PASS/FAIL → `score: 0-1`** instructions a judge follows. |
| `expander.py` | `PromptExpander` ABC + `TemplatedExpander` — wraps `build_prompt(manifest, subject)` for the on-brand `(positive, negative)`; given `prior_issues`, appends `". Emphasize and correct: <issues>"` so the next render corrects them. |
| `judge.py` | `Verdict(passed, score, issues)` + `Judge` ABC (`judge(image_path, rubric) -> Verdict`) + `parse_verdict(text)` — a robust free-text → `Verdict` parser (word-boundaried PASS/FAIL, clamped score, NOT-MET lines → issues; never raises). |
| `loop.py` | `run_loop(*, expander, judge, generate, manifest, subject, rubric=None, max_iters=4, seeds=None) -> LoopResult` — the heart. Judge-agnostic: `generate` and `judge` are **injected callables**. Threads prior issues forward; returns early on PASS, else the best-scoring candidate after the cap, with full per-iteration history. |

The judge's **PASS/FAIL verdict is authoritative** for stopping the loop — a single
PASS returns immediately. The `score` is *not* a threshold gate; it is used only to
**rank candidates** when the iteration cap is reached and the loop returns the
highest-scoring one. A mid-iteration render/judge failure is caught and recorded as a
failed candidate (score `0.0`, no image), so one bad iteration never aborts the run and
a failed candidate can never win.

The two pluggable seams are the **`Judge`** interface (how a candidate is scored) and
the **`PromptExpander`** interface (how a subject + prior issues become a prompt).
Everything else — the rubric, the loop, the generate path — is shared by both backends
below. `TemplatedExpander` is the V1 expander; an LLM-driven expander is a documented
future extension, not built.

## The three judge backends

All drive the *same* core; they differ only in **who plays the `Judge`**.

| | **Local standalone** | **API (provider-agnostic)** | **Assistant Workflow** |
|---|---|---|---|
| Judge | A single **Qwen2.5-VL-7B** node | **Any OpenAI-compatible LLM** (`LLMJudge`, N-pass consensus via `--judge-passes`) | The assistant's own vision — M passes, majority-PASS consensus |
| Driver | `auto_generate.py --backend local` (default) | `auto_generate.py --backend api` (+ `CHIMERA_LLM_*` / `--llm-*`) | Claude Code Workflow tooling (assistant in the loop) |
| Cost / deps | ~15 GB VRAM VLM, **offline/unattended** | API or **local** endpoint (Gemini/OpenAI/Anthropic/Ollama) — no SDK | No API key, no extra model |
| Status | **Built + validated** (full loop ran live) | **Built + mock-tested** (live endpoint validation pending) | **Built + proven** (live fail→pass below) |
| Recipe | `scripts/agent/auto_generate.py` | §[Bring your own LLM](#bring-your-own-llm---backend-api----pipeline-cad) | [`../../workflows/agent/README.md`](../../workflows/agent/README.md) |

**When to use which:**

- **Assistant Workflow** — highest-quality, subtle-correctness briefs (anatomy,
  layout, counts, "no X"), when you can keep the assistant in the loop. The multi-judge
  consensus is the strongest available filter. Recipe + the proven chimera-anatomy
  precedent: [`../../workflows/agent/README.md`](../../workflows/agent/README.md).
- **Local standalone** — unattended batches, scheduled jobs, or fully **offline** runs
  with no assistant present. Trades a touch of judging quality for autonomy.

### Multi-judge consensus — `ConsensusJudge`

The majority-vote consensus above is now a concrete, judge-agnostic `Judge`:
[`scripts/agent/judge.py`](../../scripts/agent/judge.py)'s `ConsensusJudge` wraps **N sub-judges**
and combines them — `passed` = a strict majority passed, `score` = the mean, `issues` = the
de-duplicated union of every sub-judge's unmet criteria (so the expander addresses *all* raised
concerns on the next iteration). A sub-judge that raises counts as a fail rather than crashing the
panel. The diversity comes from the judges you pass in (different VLMs/prompts, or an assistant
panel) — all behind the same `Judge` seam, so it drops straight into `run_loop`. Unit-tested in
[`tests/test_consensus.py`](../../tests/test_consensus.py).

### Local backend

> **Status: built + live-validated.** The full generate → judge → refine loop has run
> end-to-end: a Z-Image render judged by Qwen2.5-VL-7B against the auto-built brand
> rubric, returning `passed=True score=0.97`.

The local backend runs the **same** `run_loop` with a `Qwen2.5-VL` judge node in place
of the assistant's vision — see `scripts/agent/auto_generate.py`. The judge is
**Qwen2.5-VL-7B-Instruct** run **as a ComfyUI graph** (the same queue/`ComfyClient`
path every Chimera modality uses): `LoadImage → Qwen2.5-VL(prompt = rubric.as_prompt())
→ text`, then `parse_verdict()` turns that text into a `Verdict`. The expander is the
same deterministic `TemplatedExpander`, so a local run is brand-aware without any
assistant or API key.

**Invocation:**

```
python scripts/agent/auto_generate.py [--brand <brand>] --subject "<subject>" \
    --comfy-output-dir <ComfyUI output dir> [--max-iters N] [--seeds a,b,c]
```

`--brand` is **optional** — the same machinery does branded *and* general self-correction:

- **With `--brand`** — `build_rubric` adds the brand's style/palette/negative criteria, so the
  loop enforces brand conformance and the winner routes into `brands/<brand>/outputs/`.
- **Brandless** (omit `--brand`) — the manifest is the neutral `default_manifest()`, so the rubric
  collapses to just *"clearly depicts {subject}"* + *"high quality (sharp, well-composed, no
  artifacts)."* That's a general QA gate — reject blurry / wrong-subject / artifact-ridden renders —
  and the winner routes into the global `outputs/`. The judge, expander and loop are brand-agnostic;
  only the rubric's optional criteria differ.

`--comfy-output-dir` does double duty: it's both where finished renders route (into the brand
folder, or the global `outputs/` when brandless) **and** where the judge graph drops (and the judge
reads back) its verdict `.txt`.

### The judge & correction in action (real local-backend output)

The strict judge **enforces the brand** — it passes an on-brand render and rejects an off-brand one
(both judged live by Qwen2.5-VL-7B against the `example-brand` rubric):

| Judge **PASSED** — 0.95 | Judge **REJECTED** — 0.70 |
|:---:|:---:|
| ![on-brand tactical MERCURY-7 rover the judge passed](../../docs/images/agent-judge-pass.png) | ![off-brand orange toy rover the judge rejected](../../docs/images/agent-judge-reject.png) |
| dark tactical hull, legible "MERCURY-7", brand palette | *"playful, childlike… toy-like rather than rugged tactical-industrial"* |

The rubric is **strict** (overall PASS only if *every* criterion is MET) and asks the judge to attach
a structured fix to each miss — `FIX: add <…>; avoid <…>`. The expander consumes that directly:
`add` terms are emphasized in the next positive prompt; `avoid` terms are **stripped from the subject**
in the positive (Z-Image zeroes the text negative, so the positive is the real lever) and also pushed
to the negative for models that honor it (FLUX.2). See `scripts/agent/expander.py`.

**The judge evaluates every criterion and emits an actionable fix.** Verbatim from Qwen2.5-VL-7B on an
`example-brand` rover render:

```
1. MET — six wheels arranged in two rows of three, providing stability typical of military vehicles…
2. MET — robustly built with sharp angles consistent with industrial designs…
3. NOT-MET  FIX: add subtle highlights reflecting light off metallic surfaces;
            avoid overly smooth textures that might suggest plastic models rather than real metal
4. MET — dominant colors match those specified (#1c1f22, #2e3338)…
5. MET — clear details, no blurring…
```

That `FIX: add … ; avoid …` is exactly what the expander turns into the next prompt.

**It enforces the brand.** Given a deliberately off-brand *"glossy orange plastic toy rover,"* the
strict judge rejects it (and explains why), where the old lenient pass-bar would have rubber-stamped it:

```
NOT-MET — a playful, childlike appearance that aligns more closely with "toy-like" than with
          rugged tactical-industrial / precise engineering themes.
NOT-MET — lacks the specified palette colors like #1c1f22 …
Overall: FAIL   score: 0.7
```

…versus an on-brand render the same judge passes at **0.95–0.97**.

### A real fail→pass — the assistant consensus backend *correcting* an off-brand render

Enforcement is half the loop; the other half is **correction**. Below the loop is driven by the
**assistant consensus backend** — the agent's own vision, **M = 3 independent passes** combined by
[`consensus_verdict`](../../scripts/agent/judge.py) — against the `example-brand` rubric for subject
*"a six-wheeled exploration rover"*. **Same subject, same seed (7), same real pipeline; only the brand
correction changes** — one rover, taken from a glossy toy finish to on-brand tactical armor:

| iter 0 — consensus **FAIL · 0.38** (3/3 FAIL) | iter 1 — consensus **PASS · 0.92** (3/3 PASS) |
|:---:|:---:|
| ![off-brand candy-colored glossy toy rover the consensus judge failed](../../docs/images/agent-correct-before.png) | ![the same six-wheeled rover in on-brand gunmetal tactical armor the consensus judge passed](../../docs/images/agent-correct-after.png) |
| a six-wheeled rover in **glossy candy-red/yellow toy** finish — fails *style*, *palette*, *avoids toy-like* | the **same six-wheeled rover** in gunmetal + matte-black tactical armor, rust accent — **every criterion MET** |

The first prompt was deliberately off-brand (*"a six-wheeled exploration rover vehicle, bright glossy
candy-red and sunny-yellow plastic bodywork, smooth rounded cartoonish toy styling, … pastel colors"*).
Each of the three vision passes marked it FAIL with a structured fix; `consensus_verdict` unioned their
issues, and the **real `TemplatedExpander`** turned them into the iter-1 prompt — stripping `glossy,
candy-red, sunny-yellow, toy, rounded cartoonish, pastel` from the subject and leading with *"Correct
the previous attempt — render strictly in the rugged tactical-industrial style…"* plus the emphasized
`add` terms (matte gunmetal, hard angular faceted panels, weathered, photoreal). Re-rendered at the
**same seed**, the consensus judge passed it 3/3. **The subject never changed — it is a six-wheeled
rover in both frames — so what you see corrected is the *brand*, not the object.** That is the loop
doing what it is for: **turning a genuine miss into an on-brand pass**, not merely rejecting.

One of the three passes for each frame, **verbatim** (the texts `consensus_verdict` parsed and combined
— same format the local 7B section above quotes, except here the judge is the agent's own vision, so
read the score as the agent's self-assessment, not a third-party metric):

```
# iter 0 — one of three FAIL passes
1. avoids toy-like/cartoonish: NOT-MET - unmistakably a glossy plastic kids toy.
   FIX: add rugged matte tactical hardware; avoid toy-like, glossy plastic, cheerful, rounded cartoonish
2. high quality (sharp, well-composed): MET - sharp and clean.
Overall: FAIL   score: 0.4

# iter 1 — one of three PASS passes
1. clearly depicts a six-wheeled exploration rover: MET - a six-wheeled armored rover, three wheels per side.
2. style matches rugged tactical-industrial, gunmetal, matte black, hard edges, photoreal: MET -
   angular faceted armored hull, photoreal hardware render.
Overall: PASS   score: 0.94
```

The headline **0.38 / 0.92** are the **mean of each frame's three self-assessed passes**
(`consensus_verdict` averages them); the per-pass scores above are the individual votes.

**Honest note on convergence — and which backend earns it.** Z-Image's base quality plus brand prompt
injection are strong enough that a *satisfiable* subject often passes on the **first** iteration, so a
dramatic fail→pass appears only when a render genuinely misses the brand (as above, where the first
prompt was deliberately off-brand). Reliability scales with the judge. The **assistant consensus
backend** earns that fail→pass cleanly — three independent vision passes yield a strict verdict and
precise, format-following fixes. The **autonomous local 7B** follows the structured-fix format only
*intermittently*, so it enforces the brand reliably but converges less consistently — the trade for
running unattended. Choose the tier per job: `--backend local` for hands-off batches, the opt-in
`--backend assistant` (agent in the loop) when you want the strongest correction.

### …and it works **without a brand**, too — correcting *content*, not style

Drop `--brand` and the **same loop runs brandless**: `default_manifest()` collapses the rubric to
*"clearly depicts {subject}"* + *"high quality"* (no style/palette criteria), and the expander's
correction carries **no brand lead** — just `"Correct the previous attempt. {subject}. Ensure these
are present: …"`. Here the subject is a **chimera** — *a lion's body, a goat's head rising from its
back, and a serpent-headed tail* — and the miss is **content**, not brand:

| iter 0 — consensus **FAIL · 0.59** (3/3 FAIL) | iter 1 — consensus **PASS · 0.91** (3/3 PASS) |
|:---:|:---:|
| ![brandless chimera missing the serpent-headed tail](../../docs/images/agent-correct-unbranded-before.png) | ![the same brandless chimera with the serpent-headed tail added](../../docs/images/agent-correct-unbranded-after.png) |
| lion body ✓ + goat head from the back ✓, but the **tail is an ordinary lion tail** — *"clearly depicts {subject}"* NOT-MET | the loop grew the **serpent-headed tail** — all three parts present, both criteria MET |

The judge's verbatim miss and fix (same `consensus_verdict`, brandless rubric):

```
1. clearly depicts the full chimera (lion body, goat head from the back, serpent-headed tail):
   NOT-MET - the tail is a plain tufted lion's tail, not serpent-headed.
   FIX: add a serpent's head at the tip of the tail, a scaled snake-headed tail; avoid plain lion tail
Overall: FAIL   score: 0.6
```

The expander folded that into `"…Ensure these are present: a serpent's head … at the tip of the
tail"` and the re-render grew the serpent tail. Note the **contrast with the branded demo above**: the
branded rubric corrected *style* (toy → tactical) because a brand *defines* a style; the brandless
rubric has no style criterion, so it corrected *content* (the missing tail) and left the rendering
style free (here it drifted photoreal → illustration — correct brandless behavior). Same machinery,
two jobs: **enforce a brand, or just make the render actually depict what you asked for.** Run it with
`python scripts/agent/auto_generate.py --subject "…" --comfy-output-dir …` (no `--brand`).

**How the verdict is captured:** the judge graph
(`workflows/templates/agent-vlm-judge.json`) runs Qwen2.5-VL via the
`AILab_QwenVL_Advanced` node and writes its text output to disk with the **core**
ComfyUI node `SaveImageTextDataSetToFolder` (`comfy_extras.nodes_dataset`), which lands
`agent_verdicts/<prefix>_00000.txt`; `LocalVLMJudge` reads that file (run-unique prefix,
brief retry for the FS flush) and feeds it to `parse_verdict()`. That save node is
`experimental` and ships in core ComfyUI — it is **not** a separate node pack — so it
requires **ComfyUI ≥ 0.24.x** (the QwenVL node pack remains the only third-party
dependency).

- **Model:** `Qwen2.5-VL-7B-Instruct` — FP16 ≈ **15 GB VRAM**, placed in
  `models/LLM/Qwen-VL/` (catalogued in [`../../docs/CATALOG.md`](../../docs/CATALOG.md)).
- **Node pack:** [`1038lab/ComfyUI-QwenVL`](https://github.com/1038lab/ComfyUI-QwenVL),
  installed and **security-audited this session** — verdict **SAFE-WITH-PRECAUTIONS**,
  **pinned at commit `fcd1ada`**. Re-scan before advancing the pin.

**VRAM / perf:** the 7B judge at FP16 fits a 32 GB card alongside an image model with
room to spare, but judging adds a VLM load + inference per candidate, so a multi-seed
batch is meaningfully slower than a plain generate. For lighter cards, a smaller VL
variant is the natural fallback (judging quality drops accordingly).

**Security posture:** weights come from the **official Qwen repo**
(`Qwen/Qwen2.5-VL-7B-Instruct`) only; the node pack is **pinned** (no `@latest`) at the
audited commit, consistent with the rest of Chimera's third-party-code policy (same
standard applied to the [MCP bridge](README.md) and the foley pack). Re-audit before
any pin bump.

## 3D self-correction (Phase 3) — `--pipeline mesh3d`

The same loop now corrects **3D meshes**. `auto_generate.py --pipeline mesh3d` runs:

```
subject ─► txt2img concept ─► Hunyuan3D mesh ─► Blender mesh_eval (4 orbit stills + geometry probe)
        ─► contact-sheet PNG ─► VLM form judge (+ geometry checks) ─► FIX ─► refine ─► repeat
```

It reuses the **model-free core unchanged** — `run_loop`, `parse_verdict`, `TemplatedExpander`,
`ConsensusJudge`. Only three pieces are new:

| Piece | What |
|---|---|
| `scripts/agent/render_generate.py` | `make_render_generate(...)` — the `generate(pos, neg, seed)` closure: txt2img concept (or `--from-image`) → upload → Hunyuan3D mesh (routed to `outputs/3d`) → headless `mesh_eval.py` render+probe → host-side contact-sheet montage → returns the **contact-sheet PNG** the judge consumes. |
| `workflows/templates/blender/mesh_eval.py` | bpy template: import mesh → 4 orbit Cycles stills → **bmesh geometry checks** (non-manifold / open-edge / loose-part / tri-count / bounds) → emits both in its manifest. |
| `scripts/agent/judge.py` `GeometryAwareJudge` | wraps any `Judge`; reads the `<stem>.checks.json` the generator writes and **forces FAIL + unions structural NOT-MET issues** on any geometry defect (things a VLM can't see from a render). |

**Form, not color.** Hunyuan3D output is **untextured grey clay**, so `build_rubric(manifest, subject,
modality="3d")` scores *form* — recognizability, proportions/silhouette, completeness (no missing/
broken/fused parts), clean surface — and **drops the color/palette criteria**. (Texturing is Phase 4.)

**The lever is the concept image.** Hunyuan3D is image-conditioned (no text prompt steers the mesh
graph), so the expander's `FIX` directives steer the **concept** prompt, and a fresh mesh is lifted from
it each iteration. Two failure modes self-route: an *actionable* visual miss (wrong proportions, a
missing part) folds into the next concept prompt; a *lift-lottery* defect (a melted back, a hole)
usually yields no steerable FIX, so the concept holds steady while the loop's advancing seed **rerolls
the mesh**. `--from-image` fixes the concept outright and makes the loop a pure mesh-reroll (the
"character image → 3D model" path).

**What the judge sees.** A single **contact sheet** of 4 orbit views (montaged host-side via
`scripts/brandkit/montage.py`), so the VLM catches back/side defects a single hero view would hide.
`mesh_eval` also computes geometry facts (non-manifold/open edges, loose parts, tri-count, bounds) and
records them in a `.checks.json` sidecar. `structural_issues` injects only the **gross, VLM-invisible**
ones as pre-judged NOT-MET issues — an **empty/degenerate mesh** or one that **fragmented into many
islands** can never PASS, however good the contact sheet looks. It deliberately does **not** fail on
non-manifold or open edges: a live run showed raw Hunyuan3D output is inherently ~34% non-manifold (even
at zero weld) with some boundary edges — baseline for surface-net extraction, not a defect — so gating on
them rejected every real mesh. They stay in the sidecar for provenance (`DEFAULT_MAX_LOOSE_PARTS`, the
fragmentation threshold, is tunable).

**Backends.** Same `--backend` as the image loop: `local` (autonomous Qwen2.5-VL over the contact
sheet, default) or the gated `assistant` consensus (the agent judges the contact sheet with M vision
passes — see [`../../workflows/agent/README.md`](../../workflows/agent/README.md)).

**Cost.** A mesh3d iteration runs two ComfyUI graphs + a Blender render, so `--max-iters` defaults to
**3** (vs 4 for image); `--blender-timeout` budgets the render independently of the ComfyUI `--timeout`.

**Invocation:**

```
python scripts/agent/auto_generate.py --pipeline mesh3d --subject "an armored knight on horseback" \
    --comfy-output-dir <ComfyUI output dir> [--brand <brand>] [--from-image concept.png] \
    [--octree 256] [--samples 48] [--res 640 640] [--max-iters 3] [--backend local|api|assistant]
```

The winner's mesh lands in `outputs/3d/` (or `brands/<brand>/outputs/3d/`); the judged contact sheet
and the `agent-run` sidecar (`modality:"3d"`, `winning_seed`) land in the images folder beside it.

> **Status: built, GPU-free CI tested, and live-validated end-to-end (2026-06-14, Blender 5.1.2 /
> RTX 5090).** The full **autonomous** loop ran concept (Z-Image) → Hunyuan3D mesh → `mesh_eval`
> contact sheet → **real Qwen2.5-VL judge** + geometry gate → accept, returning **PASS score 0.95**
> on a clean armored-rover mesh; the Phase-4a `--texture` path was validated on a knight helmet
> (front-faithful red/gold albedo, palette back). That first live run is what surfaced the over-strict
> geometry gate (raw Hunyuan3D is inherently non-manifold, so the old non-manifold/open-edge fail
> rejected every mesh) — now recalibrated to fail only on empty/degenerate/fragmented meshes. The
> earlier `mesh_eval` smoke had already caught + fixed a glTF vertex-split bug (watertight meshes read
> as thousands of loose parts).

### Phase 4a — front-projected albedo texturing (`--texture`)

`--pipeline mesh3d --texture` restores color to the loop via a **headless Blender bake** (pure
bpy/Cycles — it never touches the blocked `custom_rasterizer` path). Per iteration, before the orbit
renders, `_common.bake_albedo()`:

1. `smart_project`-unwraps the mesh into an albedo atlas (Hunyuan3D output is UV-less, so always unwrap);
2. projects the **concept image** (the same one that conditioned Hunyuan3D) from a dead-front camera —
   computed with `world_to_camera_view` per loop, because `bpy.ops.uv.project_from_view` needs a VIEW_3D
   region that doesn't exist under `--background`;
3. shader-masks **front-facing faces → concept** vs un-projected faces → a flat **`--back-fill`**
   (`palette` = `manifest.palette[0]`, the default; `mirror` = a back-projected flipped concept, for
   symmetric crest/relief subjects);
4. **EMIT-bakes** a `--texture-res` (default 1024) atlas, rewires it as Principled Base Color, and
   `mesh_eval` exports a self-contained **textured GLB**.

The stills are then colored, so the contact-sheet judge sees color. `build_rubric(..., textured=True)`
re-adds the color/palette criteria with **thrash-safe** wording — *"a plain or palette-filled back is
acceptable"* — so a genuinely wrong **front** color folds a `FIX` into the next concept prompt (color
self-correction, through the existing channel) while the loop never chases back texture a single front
image can't produce. A `<stem>.texture.json` sidecar records the textured status + GLB name.

**v1 honesty:** front-faithful, back palette-filled (or mirrored); the EMIT bake captures the concept's
lighting (lit-looking albedo, not delit). **Live-validated on Blender 5.1.2 / RTX 5090** (the smoke
caught and fixed the headless `project_from_view` bug); the full `--texture` loop end-to-end is pending
a ComfyUI run.

### Phase 4b — all-around texture: multi-view bake engine + auto-repaint (both shipped)

Phase 4a's back is approximate because one front image has no back data. **Phase 4b** finalizes the
**winning** mesh once (not per iteration) with real all-around color. It splits into a shipped engine and
a deferred view-generator:

**Shipped — the multi-view bake engine.** `generate.py finalize-texture --from <glb> --views
front,right,back,left` runs the `mesh_finalize.py` template, which calls **`_common.bake_multiview()`** —
a generalization of `bake_albedo` from 1 → N views: a ring camera per view, a per-view
`world_to_camera_view` projection UV, a per-view front-facing weight `max(0,dot(N,-dir))²`, a normalized
weighted blend `Σ(w·c)/max(Σw,ε)`, and a flat `--back-fill` for faces no view sees → EMIT-baked atlas →
textured GLB + orbit verification stills, routed to `outputs/` with a `mode:"finalize-texture"` sidecar.
Pure bpy/Cycles. **Live-validated on Blender 5.1.2 / RTX 5090** (a 4-distinct-colour-view bake of a sphere
put all four colours in the atlas — R 13 / G 14 / B 12 / Y 22 %). Today the N corrected views are
**supplied** (an artist's paints, or any source); this alone is a usable finalize step for the winning
mesh (its name is in the loop's `<sheet>.texture.json` sidecar).

**Shipped — the ComfyUI auto-repaint that generates the views.** `finalize-texture --auto-repaint
--concept <img> --subject "..."` finalizes without hand-painted views: `render_views.py` renders a per-view
**depth map** for the winning mesh → for each view an **SDXL depth-ControlNet** (lock geometry to that
depth) + **IPAdapter** (carry the concept's identity) graph (`scripts/brandkit/repaint.py`,
`repaint.generate_views`) paints a corrected view → the N views feed the shipped `bake_multiview`.
`--cn-strength`/`--ip-weight`/`--views-count` are tunable; the sidecar records the auto-repaint provenance.
Pure inference, **not** wheel-blocked (unlike in-ComfyUI Hunyuan3D-Paint, still stuck on the
cu130/torch2.10/sm_120 `custom_rasterizer` wheel — see [`../threed/README.md`](../threed/README.md)).
Models (all pinned/audited — see [`../../docs/CATALOG.md`](../../docs/CATALOG.md)): cubiq
`ComfyUI_IPAdapter_plus` @ `a0f451a` + `ip-adapter-plus_sdxl_vit-h` + `CLIP-ViT-H-14` +
`xinsir/controlnet-depth-sdxl-1.0`. **Live-validated on the RTX 5090:** an armored rover textured green/tan
all the way around. **Polish (shipped):** each repainted view is masked to its depth silhouette before
baking (the concept's background no longer bleeds onto edges), and views after the first add a second
IPAdapter pass on the previous painted view (`prev_weight`, default 0.4) for **cross-view consistency**.
A busy concept background still helps less than a plain one — lower `--ip-weight` if identity over-imposes.
**Roadmap:** an autonomous **in-loop finalize** (auto-run `--auto-repaint` on the mesh3d loop's winning
mesh, reusing its concept) — today, run `finalize-texture --auto-repaint` on the winning GLB manually.

## CAD self-correction (FreeCAD, agent-authored script)

The same generate→judge→refine loop applies to **parametric CAD**, but the lever differs. Image→3D
varies the concept image + seed; CAD geometry is **deterministic**, so the lever is the **script itself**.

The loop: a brief → an **agent-authored FreeCAD Python script** → `generate.py cad --mode script
--script <file>` executes it headless into a BREP solid + STL → `generate.py render --mode mesh` renders
it → a VLM judges form/printability → the FIX feedback drives the **agent to revise the script** (e.g.
"handle too thin" → bump wall thickness) → re-execute, repeat. No geometry gate is needed (FreeCAD BREP
output is clean/manifold, unlike Hunyuan3D); `cad` already validates dims host-side.

**Two ways to drive the generator.** *Assistant-authored* (`cad --mode script`, the agent in Claude Code
writes/revises the script by hand) **or fully autonomous** via **`auto_generate.py --pipeline cad
--subject "..."`**, where a provider-agnostic LLM (below) writes + revises the FreeCAD script from the
loop's FIX feedback — `LLM script → cad --mode script → Blender contact sheet → judge → revise`, reusing
`run_loop`. `--pipeline cad --backend api` is a pure LLM+FreeCAD+Blender loop (no ComfyUI); with
`--backend local` the Qwen judge is used (and ComfyUI runs only for judging).

> ⚠️ The autonomous loop **`exec`s LLM-authored scripts**. They run with a host-side denylist + restricted
> builtins + an import allowlist (`script_exec.py restrict=True`), which closes the python-level escapes —
> but it is **not a true sandbox** (FreeCAD's own `Part.export`/`doc.saveAs` can still write files). Point
> `--pipeline cad` only at an LLM you trust, on a machine you accept it touching.

### Bring your own LLM (`--backend api` / `--pipeline cad`)

Both the AI judge (`--backend api`) and the CAD code-gen are **provider-agnostic** — `scripts/agent/llm.py`
speaks the OpenAI-compatible `/v1/chat/completions` shape over stdlib HTTP (no vendor SDK), so any compatible
endpoint works. Configure via env (or `--llm-base-url`/`--llm-model`):

| Provider | `CHIMERA_LLM_BASE_URL` | `CHIMERA_LLM_MODEL` | key |
|---|---|---|---|
| **Google Gemini** (OpenAI-compat) | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.5-pro` | `CHIMERA_LLM_API_KEY` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` | `CHIMERA_LLM_API_KEY` / `OPENAI_API_KEY` |
| Anthropic (OpenAI-compat) | `https://api.anthropic.com/v1` | `claude-opus-4-8` | `CHIMERA_LLM_API_KEY` / `ANTHROPIC_API_KEY` |
| OpenRouter | `https://openrouter.ai/api/v1` | e.g. `google/gemini-2.5-pro` | `CHIMERA_LLM_API_KEY` |
| Local (Ollama / LM Studio / vLLM) | `http://localhost:11434/v1` | a local model | (omit) |

Any OpenAI-compatible endpoint works — Gemini, OpenAI, Anthropic, OpenRouter, Groq, Together, or a local
server — because `LLMClient` only speaks `/v1/chat/completions`. For the vision **judge** the model must be
multimodal (Gemini, GPT-4o, Claude, a local llava/Qwen-VL); for CAD **code-gen** any chat model works.

```
python scripts/agent/auto_generate.py --pipeline cad --subject "a coffee mug" --backend api \
    --llm-base-url https://api.anthropic.com/v1 --llm-model claude-opus-4-8   # + CHIMERA_LLM_API_KEY in env
```

`--backend api` also works on `--pipeline image`/`mesh3d`; `--judge-passes N` runs N LLM vision passes and
majority-consensuses them (default 1). Config can come from env (`CHIMERA_LLM_BASE_URL`/`_MODEL`/`_API_KEY`,
e.g. via `.env`) instead of the flags.

> **Status (2026-06-14):** the assistant-authored path is shipped + live-validated (a parametric mug,
> author→exec→render→judge→revise with a BREP rim fillet). The **autonomous LLM path** (`--pipeline cad`,
> `--backend api`) is **built + GPU/network-free mock-tested**; live validation is pending an LLM endpoint
> (the Qwen judge it can pair with is already available). See
> [`../cad/README.md`](../cad/README.md#--mode-script--generative-cad-self-correction).
