# Changelog

All notable changes to Chimera are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`render --mode finish --solid`: AI meshes become printable solids.** TRELLIS.2 and Pixal3D output a
  paper-thin, double-sided sheet with layers stacked inside (a shirt over the body), and `--watertight`
  sealed it into a hollow shell. `--solid` (needs `--scale-mm`) has Blender write the mesh as a raw STL in mm
  at the print size (new template `mesh_raw_mm.py`: seams welded, small holes capped), rebuilds it on the
  host as one solid (`scripts/brandkit/solidify.py`: closes leaks, picking the closing radius from the jump
  in solid volume when the body cavity seals; keeps only the outer skin; FFT Poisson reconstruction from its
  normals), then finishes it (largest piece kept, decimation pinches repaired). Tested on the 5090 box (CPU
  only, about 3 minutes for a 230 mm figure): a fresh TRELLIS.2 trophy went from HOLLOW, 44 cm³ in 30 pieces
  with 6,478 open edges, to one 481 cm³ solid; two leaky trophies picked 1.6 and 2.0 mm, as found by hand.
- **STL print check.** Every STL that `--mode finish` writes is checked: size in mm, closed and manifold,
  separate pieces, volume, and SOLID vs HOLLOW (rays through the model, `scripts/brandkit/printcheck.py`).
  The report prints in the console and goes into the sidecar (`print_check`); a HOLLOW result points to
  `--solid`.
- **`[print]` extra** (numpy, scipy, scikit-image) for both; `chimera doctor` reports whether it's installed. CI installs it on the Linux legs; Windows stays on
  `[dev]`, since scikit-image pulls in Pillow and the Windows leg is the one that proves the no-Pillow paths.

### Fixed
- **`--scale-mm` STLs loaded 1000× too small in slicers.** STL has no units and slicers read millimetres,
  but Blender's units are metres, so `--scale-mm 60` came out as 0.06 mm. STL is now written in mm: a GLB/FBX
  or any `--scale-mm` model goes out ×1000, and an unscaled STL/OBJ input (a FreeCAD part, already mm) keeps its
  numbers. GLB stays in metres, as glTF specifies.
- **A `--scale-mm` model floated above the floor in the hero render.** Scaling about the origin left a
  TRELLIS.2 GLB 0.39 m up (a dimmer render) and a mm-scale mesh 114 m up (a near-black one), away from the
  floor and the light rig. The model is now centred on the floor after scaling, so the STL also starts at
  z = 0.

## [0.6.1] - 2026-10-16

The upkeep release: a weekly / monthly / quarterly maintenance routine, then its first update window (Blender
5.2.2 LTS, Ollama 0.40.5, blender_mcp `dbbf836`).

### Added
- **A maintenance routine** ([`docs/MAINTENANCE.md`](docs/MAINTENANCE.md)): what runs by itself every week, the
  monthly update window, the quarterly review, and what can't wait. The freecad-mcp advisory went unnoticed for
  three weeks because the weekly report checked only commits; now:
  - the weekly update report lists the published GitHub security advisories that affect a pin, comfyui-mcp's
    pinned version, ComfyUI or a host app's reference version (read from each advisory's version range, or by
    date when it has none), and compares the host apps (Ollama, FreeCAD, Blender, Node.js, Python) with their
    latest releases and end-of-life dates. Its first run found a FreeCAD advisory that covers 1.1.4 on Windows
    and the Blender 5.1 line past its end of life. comfyui-mcp shows as held by policy instead of a weekly
    warning;
  - [`maintenance.yml`](.github/workflows/maintenance.yml) opens a checklist issue for the monthly update window
    on the 1st, and one for the quarterly review in January, April, July and October;
  - CI also runs weekly (Mondays), and on Python 3.13 and 3.14 on Linux (not required checks);
  - Dependabot also updates the pre-commit hooks, with Actions and hooks grouped into one PR each.

### Changed
- **blender_mcp → `dbbf836`** (v1.0.2 +3, re-audited): large responses such as screenshots and renders were cut off
  when the socket's send buffer filled; the bundled manual and API docs now cover Blender 5.2; the MCP SDK is
  locked below 2. Install the add-on from the same commit. Checked live on Blender 5.2.2 LTS: the add-on from
  this commit answers the bridge, and a full-window screenshot arrives in one piece.
- **Reference host apps:** Blender 5.2.2 LTS (the 5.1 line reached end of life on 2026-07-14) and Ollama 0.40.5.
  Re-checked live: the CAD loop (code-gen, FreeCAD, the Blender 5.2.2 render and the judge; PASS on the first
  try) and the image loop on Ollama 0.40.5.
- **ComfyUI-LTXVideo stays at `15d09ab`** until our STG fix lands upstream. `44c8a36` was re-audited and is clean,
  but it changes none of the three nodes Chimera uses and adds two dependencies; the weekly report shows the
  hold instead of a warning, until upstream moves past the re-audit.
- **ruff is pinned to one minor**, 0.17.x, in the `[dev]` extra, `requirements-dev.txt` and the pre-commit hook
  (which was on 0.15.16), so a new ruff can't break CI unannounced.
- The host apps' reference versions are listed in `docs/STACK.md` §7, and a test keeps the report's table in step.
- Dev tooling: pre-commit-hooks v6.0.0 (#71); the artifact actions v7.0.2 / v8.0.2 (#67, #68).
- The upstream bugs v0.6.0 works around are reported:
  [Lightricks/ComfyUI-LTXVideo#579](https://github.com/Lightricks/ComfyUI-LTXVideo/issues/579) (STG on ComfyUI
  0.40+, with the fix as [#580](https://github.com/Lightricks/ComfyUI-LTXVideo/pull/580)),
  [Comfy-Org/ComfyUI#16312](https://github.com/Comfy-Org/ComfyUI/issues/16312) (a `/free` with the card full stops
  the prompt worker) and [Comfy-Org/comfy-aimdo#61](https://github.com/Comfy-Org/comfy-aimdo/issues/61) (error 1450
  loading FLUX.2's text encoder).

## [0.6.0] - 2026-10-16

The model-refresh release. The 2026-10 quarterly review's winners are the new defaults: Qwen-Image-2.1
(image), SeedVR2 (upscale), Wan 2.2 (video, with camera moves), Stable Audio 3 (music, plus a new sound-effects
mode) and TRELLIS.2 (textured 3D), and the agent loops run on local Qwen models sized to the GPU. Replay now
protects old renders from those changes. Also: ComfyUI 0.40 and Ollama 0.40 compatibility, a GPU-memory hand-off
between them, a freecad-mcp security fix, and a security review that tightened API-key handling, replay, the CAD
loop's FreeCAD process and the MCP approval gates.

### Security
- **`freecad-mcp` `3745ff9 → 78bf023` (v0.1.22 → v0.1.27), fixing
  [GHSA-v4pw-r6h3-v75q](https://github.com/neka-nat/freecad-mcp/security/advisories/GHSA-v4pw-r6h3-v75q)**
  (HIGH): on ≤ 0.1.24, any web page open in a local browser could make FreeCAD run arbitrary Python
  while the addon's RPC server was running. v0.1.25+ refuses browser-originated requests (`Origin`
  header, non-XML content types, and non-localhost `Host` when bound to loopback). Re-audited
  (83 upstream commits): also confines `insert_part_from_library` to the parts library, runs
  `execute_code` in its own namespace, and adds an optional shared-secret token
  (`FREECAD_MCP_TOKEN`) and a server↔addon version handshake. No new network egress.
  **Update both halves:** the `uvx` pin in `.mcp.json` and the addon in FreeCAD's `Mod/` (copy the
  whole directory; its `package.xml` is now read at import).
- **New Tier-1 gate:** v0.1.25 added `execute_code_headless` (model-supplied Python in a
  `freecadcmd` subprocess). It now requires per-call approval in `.claude/settings.json`, and
  `tests/test_mcp_gates.py` enforces it. The other new tool, `get_async_status`, is read-only.
- **Docs now require FreeCAD 1.1.4+.** Earlier releases have HIGH advisories triggered by opening a
  crafted `.FCStd` file ([FreeCAD advisories](https://github.com/FreeCAD/FreeCAD/security/advisories)).
- **The agent loop's LLM keys only go where they belong.** With no `CHIMERA_*` key set, an `OPENAI_API_KEY`
  (often exported for other tools) went to any base URL: OpenRouter, Gemini, a LAN server, a mistyped host.
  Now `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` go only to `https://api.openai.com` / `https://api.anthropic.com`,
  `CHIMERA_LLM_API_KEY` only to the shared endpoint's host when one is set (`CHIMERA_LLM_BASE_URL` /
  `--llm-base-url`), and `CHIMERA_<ROLE>_API_KEY` only to its role. The `Authorization` header is no longer
  copied onto an HTTP redirect, and a key sent over plain `http://` to another machine prints a warning.
- **Replay no longer trusts the sidecar it replays.** Sidecars get shared (the example brand's are in this
  repo), and a crafted one could upload any local file to a URL of its choosing: replay rendered on the
  sidecar's `comfy_url`, and its file inputs could be absolute paths. Replay now renders on the local default
  ComfyUI unless `--comfy-url` is given, and refuses a brand that isn't a folder name or a file input that is
  absolute or climbs with `..`. File names ComfyUI reports for an output get the same check before anything is
  moved into `outputs/`.
- **Replay also checks the fields that name or upload a file** (a second review). A crafted sidecar's `mode`
  or seed went into the output file name, so `replay --comfy-output-dir` could write a render and its JSON into
  another folder, replacing a file of that name, and its inputs could name any file in the current folder
  (`.env`, say) for upload. Replay now accepts only a mode its modality has, a whole-number seed and media files
  as inputs, and every output name must be one plain file name (`.` and an empty name included).
- **Sidecars no longer record local paths.** An absolute `--from-image`, `--from-video` or `--asset` was
  stored as given, folder layout and user name included; sidecars now keep the file name.
- **The CAD loop's FreeCAD process gets no credentials.** The loop runs LLM-written scripts, and their
  restricted mode is not a sandbox: a probe walked Python object internals back to `os` and read all 104
  environment variables, API keys included. FreeCADCmd and headless Blender now start without
  credential-named variables (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASS*`, `*AUTH*`, `*SESSION*`, proxies,
  webhooks, `*_URL` / `*_URI` connection strings, `*_PROFILE`, …), a FreeCAD job's reported outputs must sit in its own
  folder (an LLM-written script could print a forged result naming any file to be moved into `outputs/`), and
  the pre-filter also rejects dunder-attribute walks (`.__globals__`,
  `.__subclasses__`, frame objects). Only point `--pipeline cad` at a codegen model you trust.
- **18 more comfyui-mcp tools need approval** (`.claude/settings.json`; `tests/test_mcp_gates.py` pins the
  set): ComfyUI-Manager's security settings (`configure_manager`), extra model paths, `scaffold_custom_node`
  (code ComfyUI runs at startup), model downloads, node-pack bisects, `generate_node_skill` (writes a skill
  file into any folder), paid partner API nodes (`generate_with_api_node`), issue reports, and the tools that
  save workflows, defaults and snapshots. FreeCAD's `reload_document` moved from read-only to Tier 2: it
  closes and reopens the document, discarding unsaved edits.
- **Pillow ≥ 12.3** for the `images` extra; older versions carry six PYSEC advisories.
- **`.gitignore` covers conventional secret files** (`.netrc`, `.npmrc`, `.pypirc`, `.envrc`, `*.pem`, `*.p12`,
  `id_rsa*`, `credentials.json`, `service-account*.json`, `secrets.yaml`), which push protection and the
  private-key hook don't catch.
- **CI hardening.** Actions are pinned by commit SHA, checkouts don't keep the token, only the Codecov upload
  job can mint an OIDC token (the jobs that install packages can't), and `pip-audit` runs in its own job.
  Pre-commit adds `detect-private-key`. `.gitignore` adds `coverage.xml` (it embeds the absolute source
  path) and restates the `.env` / `*.local.json` rules inside the example brand, whose re-include overrode
  them.

### Added
- **GPU-memory hand-off between ComfyUI and a local Ollama** (`scripts/brandkit/gpu.py`). The agent loops
  unload their own resident Ollama models before every ComfyUI render and when the run ends, even on failure
  (`LLMClient.release`, Ollama's `keep_alive: 0`; local Ollama only, opt out with `CHIMERA_KEEP_LLM_LOADED=1`).
  Without it, a finished CAD run left its 27B codegen model holding ~26 GB, and the next ComfyUI job ran out of
  CUDA memory inside ComfyUI's own `/free` and hung.
- **`chimera free`** unloads every Ollama model, then asks ComfyUI to free its VRAM (in that order).
  **`chimera doctor`** now reports both apps' GPU memory and warns when Ollama holds 8 GB or more.
- **Thinking control for local/hosted LLMs:** `--llm-` / `--codegen-` / `--judge-` / `--rewriter-reasoning-effort`
  and `CHIMERA_[ROLE]_REASONING_EFFORT` (see Fixed).
- **Qwen-Image-2.1 image backend** (`qwen_image*` models): txt2img, logo overlay, and product mockups as a
  **reference edit**: the product photo is a reference image to the Qwen3-VL-8B text encoder, so the product
  keeps its exact look in a new scene. Core nodes only (ComfyUI 0.40), fixed 25 steps / CFG 1, about 6 s per
  1024² image on an RTX 5090. Relight stays FLUX.2. Templates in `workflows/templates/brand-qwen-image-*.json`
  (module copies under `modules/image/`); `lint` recognizes the family.
- **Textured 3D: native TRELLIS.2 and Pixal3D** (`chimera 3d --model trellis2|pixal3d`). One ComfyUI 0.40
  core graph does all of it:
  - cuts the subject out of its background (BiRefNet);
  - generates structure → shape → texture;
  - remeshes and UV-unwraps;
  - **bakes PBR textures** (base color, metallic-roughness, normal, AO) into the GLB.

  No node pack, compiled wheel or gated download is needed, so the Blackwell texturing blocker no longer
  applies to new assets. Pixal3D adds a MoGe camera-FOV estimate so the mesh matches the photo's viewpoint.
  Template `workflows/templates/brand-3d-trellis2.json` is built from Comfy's official graph, with previews
  rewired out. Short names (`trellis2`, `pixal3d`, `hunyuan21`) work for `--model`, `--mesh-model` and a
  brand's `threed.model`, and resolve to file names in sidecars. **`auto_generate --mesh-model`** picks the
  mesh3d loop's 3D model.
- **Wan 2.2 video backend + camera moves** (`chimera video [--camera <move>] [--quality fast|full]`). Core
  ComfyUI nodes; Apache-2.0; high- and low-noise experts.
  - **`fast`** (lightx2v 4-step LoRAs, ~30–55 s) is the default for plain image-to-video; **`full`** runs
    20 steps.
  - **`--camera static|pan-*|zoom-*|rotate-*`** uses Wan 2.2 **Fun Camera**: a locked shot while the scene
    moves, or a controlled move. It defaults to `full`, because the 4-step mode cut scene motion to about a
    third.
  - Wan clips are silent; add sound with `audio --mode foley --from-video`.
  - Templates are `workflows/templates/brand-video-wan22-{i2v,camera}.json`. Sidecars record the
    camera/quality and Wan's resolved clip (81 frames at 16 fps), so replay reproduces it.
- **Stable Audio 3 Medium music + `audio --mode sfx` sound effects.** It uses Comfy's official graph,
  including its Qwen3.5-2B prompt enhancer: the enhancer's `Music` or `SFX` system prompt, seeded with the
  render seed so replays match.
  - **Timing:** a 12 s track takes ~10 s; a 4 s sound effect takes ~4 s.
  - **Briefs:** sound effects use the subject alone (no brand music tags). For music, an explicit
    `--bpm` / `--keyscale` joins the brief, since SA3 has no tempo or key inputs.
  - **Template:** `workflows/templates/brand-audio-sa3.json`.
- **`audio --model acestep --lyrics "..."`**: words for ACE-Step to sing, with `[Verse 1]` / `[Chorus]` tags.
  ACE-Step was kept as the vocals option, but Chimera sent it empty lyrics, so every render was instrumental.
  Lyrics need room: in tests (by ear and by transcription) ACE-Step never sang six lines in a 20 s clip and
  sang them in 40 s on most seeds (5–6 of 7), so a lyric render is at least 40 s unless `--duration` says
  otherwise (shorter prints a warning), and the CLI reminds you to try another `--seed` if a render comes out
  instrumental, since some seeds plan one regardless. Sidecars record the
  lyrics, so replay sings them again; `--lyrics` with Stable Audio 3 or a non-music mode is an error. The
  ACE-Step graph's sampler shift is now 3, as in Comfy's ACE-Step 1.5 templates (it was 1.73).
- **`chimera --version`**, read from `pyproject.toml` (`scripts.brandkit.__version__` had said 0.1.0 since the
  first release), and `chimera --help` now describes each modality command.
- **`replay --model <file>`** re-runs a recorded render on a different model with the same subject and seed,
  e.g. to run old brand work back on a newer model. Only the prompt is compared, and settings that belong to
  the old model family (Wan or LTX clip timing, a Z-Image variant, a Hunyuan3D octree) give way to the new
  family's defaults. **`replay --accept-drift`** renders even when the brand or a template changed since (see
  Fixed).

### Fixed
- **A self-correction run could freeze the PC** (2026-10-15, Windows). Neither app sees the other's GPU
  memory there: Ollama reported 30 GB free while ComfyUI held 15. After a day of renders ComfyUI held all but
  0.1 GB of a 32 GB card, the local judge loaded on top of it anyway, and the driver paged GPU memory to system
  RAM. The judge crawled past its 180 s timeout, `nvidia-smi` hung, and the machine went down. The loops now
  keep the two apps apart:
  - before a local Ollama model loads, ComfyUI (which does see its own memory) is asked how much of the card it
    leaves free. When that's less than the model needs (weights plus context cache, read from Ollama), ComfyUI
    unloads its models and the loop waits for the room, and if the room never comes the model is not loaded;
  - Ollama models the run didn't load are unloaded before its first render (the loops already unloaded their
    own before every render);
  - the CAD loop unloads its codegen model before Blender renders.

  Verified on the reference machine: ComfyUI frees 15 GB in about a second, a 2-iteration loop on the default
  judge kept it fully on the GPU, and a request for more than the card holds is refused without loading.
  `CHIMERA_KEEP_LLM_LOADED=1` turns the unloading off (only for a second GPU).
- **The judge's verdict could contradict its own checklist.** The rubric says PASS only if every criterion is
  MET, but the parser read only the final verdict line, and a small judge often wrote "NOT-MET: the head is
  completely absent" and then "Overall: PASS". That way the loop accepted a headless robot, a two-goat Chimera
  and a portrait missing the requested raincoat. A criterion marked NOT-MET now fails the verdict. On a new
  34-case judge benchmark (hard cases: wrong counts, misplaced elements, missing attributes, off-brand colors),
  this took the default judge from 27 to 30 correct. Two more reviews found forms the first fix missed. A status
  now counts when it is a table cell (`| 2 | … | NOT-MET |`), a count (`1 NOT-MET`), or the first status word
  on a criterion's line (`1. Subject — NOT-MET`, `**Palette**: NOT_MET`, `- Nothing floats free of the hub:
  NOT-MET`, `Status: NOT-MET`), written with hyphens or typographic dashes (`NOT‑MET`, as hosted models write
  it). A line that only says nothing is unmet keeps a PASS: `NOT MET: none`, `No NOT-MET criteria.`,
  `Criteria: 4 MET, 0 NOT-MET`, `0/3 NOT-MET`, a MET reason on its own line, or the instructions echoed back
  (each had failed correct renders and gone into the next prompt as a "Fix"). A final review caught that rule
  passing broken renders: a criterion label in the rubric's own negative phrasing (`3. No missing or broken
  parts - NOT-MET`, `a knight without a helmet`) read as a summary, and unnumbered lines counted only in a few
  layouts (`- ❌ Palette: NOT-MET`, `| Palette | NOT-MET - yellow |`, `1 - Palette: NOT MET` passed). Now a
  numbered criterion's status always counts, any other line's counts unless it reads as a summary, and
  `Partially MET`, `not fully met` and `**NOT** MET` fail too: on a 32,190-reply grid of layouts, labels and
  spellings there are no false PASSes or false FAILs left, where the v0.6 parser before this review had 4,544
  false PASSes. A third review rewrote 204 real judge replies 24,426 ways and found three more ways a broken
  render passed. A criterion whose reason says `overall … would not pass` was taken for the verdict line, so the
  27B's bare `FAIL` came back as a PASS. The summary escapes let a numbered criterion off (`2. NOT-MET: none (the
  top face is flat)`, `2. Holes drilled: 0/5 NOT-MET`). Softer wordings read as MET (`Mostly MET`, `Barely met`,
  `Not quite met`, `MET (partially)`, a full-width `NOT－MET`). Now a numbered criterion, or a line marking one
  NOT-MET, is never taken for the verdict, a numbered criterion's status always counts, and those wordings
  fail. So does a PASS that admits an unmet criterion (`PASS - criterion 2 NOT-MET is minor`) or is negated
  (`Does not pass`). The rubric's instructions echoed back are ignored: their `<comma-separated visual elements
  to include>` had reached the next prompt as a term to add. Errors on the 24,426 cases went from 3,914 to 0,
  all 204 real replies parse as before, and the grid stays clean. Scores on other scales read right too: `4 out of
  5` is 0.8, `7` is 0.7, `85` is 0.85 (each read as 1.0 before), and `Scores: 0.4` or a value on the line
  after `**Score:**` are read (they scored 0.0), as is a scale named first (`Score (0-1): 0.82`, `Score [0-5]: 4`
  and `score: 0,85` read 0.0).
- **The self-correction loop inverted its own fixes when a subject's styling fought the brand.** Found with
  the local Qwen3-VL-8B judge while regenerating the README demo. Under a gunmetal brand, a subject such as
  "a glossy candy-red toy rover" made the subject criterion demand the candy colors while the style, palette
  and avoid criteria forbade them. The judge's FIX lines then contradicted each other ("add cartoonish toy
  styling; avoid matte black"), and each pass pushed the render further off-brand. Now:
  - the subject criterion judges the object itself, and the brand wins any styling conflict;
  - a FIX may not contradict another criterion;
  - the FIX parser reads what small judges actually write: either order, `remove …`, `none needed`, `X and
    Y` lists, sentence breaks (`2.5 mm` stays whole), and a verb switch mid-clause; a verb carries on until
    the next one (`avoid X; Y; Z` avoids all three). It no longer caps all consensus passes together at 10
    terms, which had dropped later passes' avoid lists;
  - the expander drops `add` terms that contain an `avoid` term or one of the brand's negative traits, and
    `avoid` terms that would strip the brand's own style or palette, however long the brand's phrases.
    Palette hex codes now match too, and a hyphenated word counts as one word, so cutting `toy` no longer
    guts `toy-like` or `toyota`;
  - in branded runs, the loop removes the styling the judge flagged from the subject **and** the rubric
    before the next pass, keeping the object itself (a cut that would orphan its noun is skipped). The run
    sidecar records the corrected subject, and `--finalize` repaints with it;
  - the palette criterion names each color by hue and lightness (`near-black (#1c1f22)`, `red (#c8442e)`,
    tan, olive, navy, teal, off-white…; `#rgb` and `#rrggbbaa` codes too) and accepts a scheme built from a
    subset of them. The judge can't read hex codes, so it had failed a correct near-black and slate render
    as "monochromatic, not the brand palette";
  - a failed render no longer feeds its error text into the next prompt (the judge's last issues carry on);
    the CAD code-gen still gets its own last FreeCAD error, so it can fix the script.
- **CAD scripts that `import App` failed on FreeCAD 1.1.** FreeCAD 1.1 ships an unrelated top-level `App`
  package, so a script's own `import App` replaced the namespace's `App` alias with a module that has no
  `Vector`. Two of three iterations of a live CAD loop died on it. A script's `App` import now resolves to
  FreeCAD in both the restricted (LLM) and trusted modes. The codegen prompt now also documents rotation
  (`shape.rotate(center, axis, degrees)` on a copy), after the local codegen model called a nonexistent
  `Matrix.rotate` in all three iterations of a fan-rotor run.
- **Blender renders had a hard black band across the top.** The camera kept Blender's default 100-unit clip
  range, which cut the floor off behind a millimetre-scale CAD part. The studio floor also ended inside the
  frame behind upright objects. The clip range and floor now scale with the object, so the floor falls off
  into shadow. This affects `render`, turntables, and the mesh3d/CAD loop stills.
- **The CAD loop passed parts that came out in pieces.** It skipped the mesh3d geometry gate on the theory
  that BREP output is clean, but a script can still build disconnected bodies: the local judge passed a fan
  rotor whose 16 blades floated free of the hub (17 separate solids). The CAD loop now writes the geometry
  checks beside each contact sheet and judges through `GeometryAwareJudge` in strict mode: a scripted part
  must come out as one solid. (The 1%-of-vertices significance bar the mesh3d loop uses can't apply here:
  with fine tessellation the hub alone held enough vertices to hide the blades under it.)
- **Foley re-timed a 16 fps clip to 25 fps when PyAV wasn't installed** (it played about 1.6× too fast). The
  fps probe needs PyAV (an optional extra), so without it foley fell back to 25 fps, LTX's rate. Foley now
  reads a Chimera clip's exact fps, frame count and size from the clip's own sidecar first. Verified on a
  Wan clip: 81 frames at 16 fps with a 5.04 s audio track.
- **A filler's "can't render this combination" error printed a traceback.** `generate.py` now reports it
  as a normal CLI error (for example `--camera` with `--model ltx23`, or logo mode without a logo).
- **`auto_generate --pipeline mesh3d --model X` loaded X as the 3D checkpoint.** `--model` is the concept
  image's model, but it was also passed to the 3D build, so every iteration failed validation and the loop
  had no winner. The 3D model now comes from the new `--mesh-model` only.
- **Replay could silently render something different.** It re-resolved the model and settings from the
  *live* brand kit and Chimera's defaults, so after a brand pin or a default model changed, replaying an
  older asset used the new model. Replay now pins the model the render actually used, then compares the
  rebuilt prompt/negative, graph structure and settings with the sidecar and stops with a readable list
  of differences unless `--accept-drift`. Sidecars now also record a settings fingerprint
  (`provenance.graph_values`); older sidecars get the model, prompt and structure checks. Video and audio
  replays now pass the pinned model through to their fillers.
- **Local models on Ollama ≥ 0.40 returned nothing.** Ollama 0.40 serves hybrid-thinking models (Qwen3.x) with
  thinking on, so the CAD codegen model spent its whole token budget reasoning and returned empty content, and
  every `--pipeline cad` iteration failed. `LLMClient` now retries once with `reasoning_effort: "none"` when a
  reply is all reasoning, and keeps it for the run. It never sends the field unless configured or retrying.
- **`auto_generate.py` exits 1 when nothing passed** (it exited 0 even on a total failure).
- **FLUX.2 jobs failed mid-session on ComfyUI 0.40.** Its new disk-streaming memory manager (comfy-aimdo 0.5.6)
  fails with Windows error 1450 ("HostBuffer.read_file_slice failed") loading FLUX.2's 33 GB bf16 text encoder
  while other models are still staged. Image jobs that load FLUX.2 (relight, or a FLUX.2 model) now free
  ComfyUI's memory first by default; `--no-free-before` overrides.
- **Blender stills were mis-framed.** `import_mesh` dropped the mesh to the floor without refreshing
  `matrix_world`, so `frame_object` aimed at the pre-drop position (a Hunyuan robot framed from the knees
  down), and the fixed-distance camera cropped compact objects such as CAD boxes. The camera distance is now
  solved from the lens field of view so the whole bounding box fits, and imports centre the origin so
  turntables spin in place. Affects `render --mode mesh`, the mesh3d/CAD loop stills, and finalize renders.
- **A replay overwrote the render it reproduced.** It keeps the recorded seed, so with `--comfy-output-dir`
  it routed onto the original file and replaced its sidecar, which is permanent for gitignored brand
  outputs. A replay now takes the render's standard name only when it is free, else `<name>_replay` (then
  `_replay2`, …), so it never replaces a file.
- **`replay --model` across model families always stopped on drift.** Each family builds its own negative
  (Z-Image none, LTX and Wan their own lists), so every cross-family re-run reported "negative changed".
  With `--model`, only the prompt is compared now; an override naming the recorded model keeps every check
  (it had switched them all off). A cross-family video replay also carried the old family's clip settings:
  an LTX clip replayed on Wan rendered at 25 fps (about 1.56× too fast), and a Wan clip on LTX came out
  silent at 16 fps. The new family's defaults now apply; a Z-Image `--variant` or a Hunyuan3D octree is
  dropped the same way.
- **A replay stamped a watermark the original didn't have** when the brand had since turned
  `watermark.enabled_default` on. Replay keeps the recorded decision.
- **A replay that stopped on drift had already unloaded every ComfyUI model.** The GPU is now freed just
  before queueing, after the drift and flag checks.
- **Video lengths snap to what the model renders** (Wan 4k+1 frames, LTX 8k+1). Wan's Fun Camera crashed
  at run time on any other length, after loading the 14B models; plain Wan and LTX silently rendered fewer
  frames than the sidecar recorded, and foley sized its audio to the recorded length. A note says when
  `--length` changes.
- **Bad flag combinations are caught before the GPU is freed or the start frame uploaded**, and two more
  are errors: `--quality` with LTX-2.3 (it was ignored) and `--model wan22-camera` without `--camera` (it
  loaded the camera model into the plain graph). `audio --mode sfx` under 1 s (Stable Audio 3's minimum)
  and a music model on `--mode foley` are now clean errors instead of a ComfyUI traceback. `--variant` on a
  non-Z-Image model and `--octree` on TRELLIS.2/Pixal3D print a note and stay out of the sidecar; `--fps` on
  Wan notes that it only changes the playback speed.
- **ComfyUI rejecting a job printed a traceback.** A validation error (a model file it doesn't have, a value
  out of range) is now one line with a `chimera doctor` hint, and an HTTP error from ComfyUI is reported as
  that rather than as "can't reach ComfyUI".
- **Models in subfolders were sorted into the wrong family.** A Qwen-Image model in a `qwen/` subfolder ran
  in the FLUX.2 graph; family checks now read the file name.
- **A TRELLIS.2 run needed the Pixal3D and MoGe files installed** (about 6 GB it never loads), and failed
  with "Value not in list" without them, because ComfyUI validates both branches of the graph's model
  switch. The 3D graph is now folded to the chosen model before it is queued.
- **`render --mode finish` turned textured meshes to clay.** `--color auto` (the new default) keeps a
  textured mesh's own materials, such as a TRELLIS.2 PBR GLB, and exports them as JPEG textures: the example
  brand's 77 MB GLB came out at 9.6 MB. `--color material|project|keep` choose explicitly; `keep` with
  `--watertight` is refused, since the remesh drops the UVs.
- **`chimera doctor` reported installed models as missing** (ComfyUI 0.40's v3 nodes list their choices in a
  new shape, e.g. BiRefNet) and only checked models with `--brand`. It reads both shapes now, and checks
  every modality's default model files, read off the default graphs themselves.
- **One dropped connection ended a long render.** `wait()` gave up on the first failed poll; it now rides
  out brief drops (20 in a row) before reporting ComfyUI as unreachable, in one line.
- **Blender/FreeCAD jobs lost their result line on non-ASCII output** (Windows decoded it as cp1252). Job
  output is read as UTF-8, and a wrong `--blender-bin` / `--freecad-bin` is a one-line error.
- **Restricted CAD scripts couldn't define classes** (`__build_class__` was missing from their builtins).
- **Agent runs reused seeds `1000+i`**, so a second run replaced the first run's winner. Each run now draws
  a random base, printed so `--seeds` can repeat it.
- **Repeating an identical job failed with "cannot find the file".** ComfyUI serves a job identical to an
  earlier one (same seed, prompt and model) from its cache and reports the earlier output file, which Chimera
  had already moved into its own output folder. Each queued job's save node now gets a unique file-name
  suffix, so the cached render is written to a fresh file; a reported file that is still missing is a
  one-line error.
- **The GPU hand-off had gaps** (a second review of the freeze fix):
  - the room check failed open: an error after ComfyUI had shown a full card (its `/free` failing, a poll
    timing out) read as "ComfyUI isn't running", and the model loaded anyway. It now refuses;
  - it only trusts a local CUDA card. Apple's mps and the CPU report system RAM, which made every local judge
    refuse on a Mac, and DirectML reports a placeholder that let everything through;
  - a model bigger than the card now always empties ComfyUI first (capped to the card, it could "fit" beside
    ComfyUI's models), and on Windows the room asked for covers the models Ollama already holds, which ComfyUI
    can't see there;
  - unloading a model waits until Ollama has let go of it, and a loop won't render beside one that stays loaded;
  - the CAD loop unloads the judge and rewriter before its renders too (only code-gen was unloaded), and one
    failed check of a local Ollama (restarting, starting late) no longer turns the checks off for the run;
  - model names match the way Ollama resolves them (`Judge:8B`, `registry.ollama.ai/library/…`), and the
    context-cache estimate counts `OLLAMA_NUM_PARALLEL` and an f16 cache when flash attention is off;
  - `OLLAMA_HOST=0.0.0.0` (Ollama's own LAN setting) became `http://0.0.0.0` on port 80, which Windows can't
    connect to, and turned the checks off elsewhere. It now means this machine on port 11434, like Ollama;
  - an `nvidia-smi` error ("NVML library version: 560.35") read as a 0.5 GB card, which picked the small
    tier, and a remote ComfyUI's card picked the tier for the local Ollama.
- **A loop that repeated a seed (`--seeds 7,7,7`) reported a winner whose file held a later pass.** Each pass
  of a repeated seed now gets its own files (`agent_7`, `agent_7_2`, …); a shorter `--seeds` list is topped up
  with fresh seeds (it fell back to `1000+i`, which collided across runs).
- **FIX directives lost their meaning.** `avoid gaps between blades and hub` split into "gaps between blades"
  and "hub", so "hub" was cut from "a fan rotor with a central hub"; a list now splits at "and" / "or" except
  inside a pair ("between A and B", "both", "either"), so `avoid red paint and chrome trim` still avoids both.
  Cutting a flagged term from the subject keeps the object's noun. The brand guard now also keeps palette
  colors the judge asks to avoid by their rubric names ("avoid near-black" for `#1c1f22`), and the rubric names
  purple, magenta, orange, pink, coral and slate colors right (`#800080` read as "dark pink", `#FFA500` as
  "gold"; `#ff00ff` is magenta and `#ff6b6b` coral, not purple and pink).
- **The CAD loop rejected harmless scripts and misreported failures.** `socket_depth`, `sockets` or a
  `# ball-and-socket` comment failed the pre-filter, so a "hex socket organizer" brief failed every iteration;
  it now rejects only a line that imports one of those modules (a shape named `socket`, or `# dims from
  http://…`, is fine, and restricted scripts can't import them anyway). A rejected first script's reason now
  reaches the retry, an LLM, GPU or Blender error (a render timeout, a locked file) is no longer reported to
  code-gen as a script failure, and a code-gen model that won't unload stops the iteration before Blender renders
  beside it. The code-gen prompt now
  states what the loop checks: the part must be one connected solid, and a cut only removes material that is
  there. In a live run on that organizer brief, the model had cut its sockets into the tray's empty cavity
  (nothing removed, 0 of 4 iterations), then added rims floating in the cavity (7 pieces); with both rules
  stated, the first iteration came out right.
- **Replay refused brands that `new-brand` creates** (a space, `&`, accented letters); both now share one rule.
  On Windows, a replay whose brand was typed in a different case could also replace the render it reproduced;
  it no longer does.
- **Blender exports carried the startup file's Cube** as a second scene: the factory scene's selected Cube rode
  along with `use_selection`. Every Blender job now starts from an empty file, and the example brand's GLB was
  re-exported without it (still 9.6 MB, one scene).
- **`--format stl|obj` deleted the GLB**, which for TRELLIS.2 and Pixal3D held the only textured copy; it now
  stays beside the STL/OBJ. A GLB in several parts is refused rather than cut to its first part.
- **Mistakes that printed a traceback are one line:** an unknown brand or a bad `brand.yaml` value (an unknown
  `threed.format` is now caught when the brand loads, before the GPU render; `null` means the default),
  replaying a file that isn't a sidecar, ComfyUI timing out, and `finalize-texture --auto-repaint` with ComfyUI
  down or rejecting the graph.
- **Flags a mode ignored are errors:** `--upscale-model` without `--upscale`, and `--bpm` / `--keyscale` outside
  music; a `--watermark` logo is checked before anything uploads; `3d --format stl` without
  `--comfy-output-dir` says it stays a GLB; `render --mode finish --formats STL,GLB` exported nothing (case).
- **The agent loop checks its local models before it renders.** v0.6 made a local Ollama model the default
  judge, and with Ollama stopped or the model not pulled a run rendered every iteration (meshes and Blender
  stills included) and only then failed at each judging, ending with "winning image: None". It now stops first
  with the fix: start Ollama, or `ollama pull <model>`. A missing `--rewrite-prompts` model only warns, since
  the templated expander takes over. A v0.5 setup that relied on `OPENAI_API_KEY` for another host (OpenRouter,
  say) gets a note that the key isn't sent there, where it got HTTP 401 after every render.
- **Replay, a third review:**
  - it accepts the other image and video types ComfyUI reads (`.gif`, `.jfif`, `.avif`, `.heic` images; `.m4v`,
    `.mpg`, `.wmv` clips);
  - a hand-edited or damaged sidecar (`"schema": "2"`, a text duration, no subject, `format: fbx`) fails with
    the field named, where it crashed mid-render, or after a whole 3D render for `fbx`;
  - a sidecar from before v0.6.0 has no settings record, so replay says what it can't check, and an ACE-Step
    one reports the sampler shift change (1.73 → 3) as drift;
  - `replay --model sa3` of an ACE-Step render (and the reverse) no longer stops on the BPM and key that Stable
    Audio 3 writes into its brief;
  - foley sidecars record the timing and size the render used, so a replay without PyAV, or of a clip whose
    own sidecar is gone, renders the same graph (it stopped on drift at 25 fps / 5 s);
  - a relative input path is stored with `/`, so a sidecar made on Windows replays elsewhere, and a sidecar
    saved with a BOM (Windows PowerShell 5.1) reads.
- **Video and product renders can start from the brand's own renders** (`outputs/images/`), as 3D and relight
  already could. The README's image → video → 3D chain failed with "not found", and so did its replay.
- **Without Pillow, JPEG, WebP and GIF sizes are read from the file's header** (only PNG's were), so a
  watermarked or product render builds the same graph with or without the `images` extra, and a replay on the
  other kind of install reports no drift.
- **More one-line errors:** `finalize-texture` with neither `--views` nor `--auto-repaint` (an
  `AttributeError`); a Blender or FreeCAD job that lists a file it didn't write (reported as ComfyUI's, with a
  `--comfy-output-dir` hint); a missing Blender during `--auto-repaint` (labelled "ComfyUI"); `auto_generate
  --brand` with an unknown brand or a bad `brand.yaml`, and `--seeds 7,x`; and a brand or file name the
  Windows console can't encode, in a piped run (it crashed after queueing the job).
- **The GPU hand-off under-sized the medium and small tiers' judges.** With no `num_ctx` or
  `OLLAMA_CONTEXT_LENGTH` set, Ollama 0.40 sizes a model's context to the VRAM it sees, up to the model's full
  trained length. On a free 32 GB card the 8B and 4B judges loaded with a 256k context (16.3 and 14.2 GB), while
  the hand-off assumed 32k (9.1 and 6.1 GB), so beside a loaded ComfyUI they would have overcommitted the card:
  the PC-freeze path. The estimate now assumes the full trained context unless one is pinned, counts the cache
  only on a hybrid model's attention layers (Qwen 3.8 keeps one every 4th layer), and sizes a missing
  `value_length` from the key length: with a q4_0 cache, 17.9 GB for the 8B, 15.0 for the 4B, 24.5 for the 27B.
  Re-checked live on each tier (the 8B now asks ComfyUI to unload first, where before it would have loaded beside
  it); measured on the 27B, the cache grew 0.72 GB from a 32k to a 128k context, under the estimate's 1.8. With
  Ollama's default f16 cache the full-context figure can exceed the card, so the check also accepts once
  ComfyUI has emptied and the model fits at a 32k context (Ollama sizes the context to the room it sees):
  otherwise every judge load was refused whenever the desktop or a browser held 3 GB. After a load, the loop
  warns when Ollama took more than planned, since the check reads Ollama's settings from Chimera's own
  environment; SETUP.md says where to set them.
- **`chimera update-check` called a ComfyUI ahead of the latest release outdated** (0.41.1 against the v0.41.0
  release; ComfyUI tags versions before it publishes them as releases). It now compares version numbers (`0.41`
  equals `v0.41.0`, and a release candidate comes before its release), and both update checks query
  `Comfy-Org/ComfyUI` directly (the old path only answered through a redirect).
- **A brand name that isn't a folder name is refused before anything renders** (`generate.py` and
  `auto_generate.py`). It was refused only when routing the output, after the GPU work, leaving the file in
  ComfyUI's folder.
- **The GPU hand-off fits more setups:** `--finalize` is skipped with the command to run it later, rather than
  repainting beside a judge that won't unload; the models Ollama already holds count toward the room asked of
  ComfyUI on Windows only (Linux and macOS drivers already include them, so a second local model waited 30 s and
  fell back); and an image run on a ComfyUI at a non-loopback address, which the room check doesn't cover, warns
  about another app's model that won't unload instead of stopping.

### Changed
- **The agent loops run on local Ollama models sized to your GPU, with nothing to configure.**
  `auto_generate.py` judges with `--backend api` by default, and each role you haven't configured (judge,
  prompt rewriter, CAD code-gen) falls back to a local Ollama model from a tier picked by the GPU's memory:

  | Tier | GPU | Judge and rewriter | CAD code-gen |
  |---|---|---|---|
  | large | 32 GB+ | Qwen 3.8 27B | Qwen 3.8 27B |
  | medium | 12–24 GB | Qwen3-VL 8B Instruct | Qwen 3.8 27B, partly on the CPU |
  | small | under 12 GB | Qwen3-VL 4B Instruct | Qwen 3.8 27B, mostly on the CPU |

  The defaults were chosen on an RTX 5090, and smaller cards get lighter judges automatically. A 24 GB card
  gets the medium tier: beside ComfyUI's image model it has no room for the 27B judge (about 22 GB with its
  context), so every judgment would wait on ComfyUI emptying itself. `--llm-tier` /
  `CHIMERA_LLM_TIER` overrides the tier; per-role flags and `CHIMERA_*` variables still win; `chimera doctor`
  reports the tier and any `ollama pull` it needs. The CAD loop no longer refuses to start without a
  configured LLM endpoint. Measured on a new 34-case judge benchmark (3 runs each): Qwen 3.8 27B 31.0 correct
  (balanced accuracy 0.90, 1.5 s per judgment), Qwen3-VL 32B 30.0 (14.6 s), 8B 29.3, Qwen 3.6 27B-coding 29.3,
  4B 27.7, 30B-A3B 27.3. On a six-part CAD code-gen test Qwen 3.8 27B built 5 (3 on the first try), Qwen 3.6
  27B-coding 4, and Qwen 3.5 9B none of the three it tried, so every tier keeps the 27B for code-gen. The
  previous judge default, `--backend local`, needs the optional, unpinned ComfyUI-QwenVL pack; pass it to
  keep using it.
- **ComfyUI ≥ 0.40 is required for the new defaults.** Their nodes are core in 0.40, so no extra node packs are
  needed. On an older build (≥ 0.24), set `--model` or a brand pin to keep the earlier models, plus
  `--upscale-model 4x-UltraSharp.pth` for image upscaling and `--mesh-model hunyuan21` for the mesh3d loop;
  `audio --mode sfx` needs 0.40. `docs/SETUP.md` lists the default downloads (about 119 GB in all, no Hugging
  Face login).
- **Reference build: ComfyUI 0.40.0** (Comfy Desktop 1.1.7), smoke-validated 2026-10-14 with every output
  checked as created by the run: txt2img, relight, upscale, video, foley, music, 3D, finalize-texture, render,
  cad, and the image/mesh3d/cad agent loops on local Ollama models. Re-validated 2026-10-15 on the new
  defaults: Qwen-Image txt2img, product edit + SeedVR2 upscale, relight, Wan 2.2 image-to-video and a camera
  move, foley on a Wan clip, Stable Audio 3 music and sound effects, TRELLIS.2 3D + render, cad, the three agent
  loops, replay, and doctor. Re-checked on ComfyUI 0.41.1 after the GPU fix (doctor, image, product edit +
  SeedVR2, sfx, Wan 2.2, TRELLIS.2, each local-model tier on the image loop and the large tier on the CAD loop),
  after the second review (the image and CAD loops, image replay, ACE-Step with lyrics, TRELLIS.2 with
  `--format stl`, and a Blender finish export), and after the third (the image and CAD loops on the large
  tier, the endpoint check, replays of genuine v0.5.1 sidecars, a Wan clip started from a brand render with
  foley on it, that foley replayed without PyAV or the clip's sidecar, the video replay, and a Blender
  render).
- **LTX-2.3 on ComfyUI ≥ 0.40 needs the bundled LTXVideo patch** (Wan 2.2, the default, runs on core nodes)
  ([`modules/video/patches/ltxvideo-stg-comfyui-0.40.patch`](modules/video/patches/ltxvideo-stg-comfyui-0.40.patch)).
  ComfyUI 0.40 passes attention inputs as `AttentionTensorContainer`s, and the pack's STG guidance returned
  one where a tensor belongs, so every STG render failed. Not yet fixed upstream as of `44c8a36`.
- **Default image model → Qwen-Image-2.1:** from Z-Image Turbo for brandless runs, and from FLUX.2 for new
  brands (`brands/_template`) and brand kits that don't pin `defaults.model`.
  Brands that pin a model are unchanged. The public example-brand now uses Qwen-Image-2.1 too, and its whole showcase was regenerated on the new defaults. Old renders replay on their
  recorded model; `chimera replay <sidecar> --model qwen_image_2.1_int8_convrot.safetensors` re-runs one on
  the new model. Note for forks: Qwen-Image-2.1 is under the Qwen research license (Z-Image is Apache-2.0).
- **Default `image --upscale` model: 4x-UltraSharp (ESRGAN) → SeedVR2 7B**, a one-step diffusion upscaler
  (core-native in ComfyUI 0.40, Apache-2.0; tiled VAE). In the 2026-10 review UltraSharp invented texture (a
  crosshatch on a speaker grille, speckles on skin) where SeedVR2 restored natural detail; 1024² → 4096² adds
  about 10 s on an RTX 5090. `--upscale-model 4x-UltraSharp.pth` (or `defaults.upscale_model`) still selects
  the ESRGAN pass, and older upscaled renders replay on their recorded upscaler. Video `--upscale` is unchanged
  (the LTX latent upscaler).
- **Default music model: ACE-Step 1.5 XL Turbo → Stable Audio 3 Medium**, the clear winner of the 2026-10
  listening comparison (same three 30 s briefs and seeds). `--model acestep` (or `audio.music_model:
  acestep`) keeps ACE-Step, for example for songs with vocals. Older renders replay on ACE-Step, their
  recorded model.
- **Default video model: LTX-2.3 → Wan 2.2.**
  - **Why:** the 2026-10 review measured camera drift on three shots whose prompts asked for a locked
    camera. LTX-2.3 pushed in 9%, drove a "parked" car off with a 34% pan, and drifted a face's identity.
    Wan 2.2 held ≤ 0.8% zoom and kept identity.
  - **Brands:** they follow the default (none pin a video model). `video.model: ltx23` pins LTX for a brand,
    and `--model ltx23` keeps synced audio for one clip.
  - **Settings:** the brand `video:` block's `length`/`fps`/`audio` apply to LTX; Wan uses its native
    81 frames at 16 fps.
  - **Not supported on Wan:** `--upscale` (LTX's latent upscaler) and `--camera` with `--model ltx23` stop
    with a clear error.
  - **Replay:** old renders replay on LTX (their recorded model).
- **Default 3D model: Hunyuan3D 2.1 (shape only) → TRELLIS.2 (textured).**
  - **Why:** in the 2026-10 review on three photos, TRELLIS.2 and Pixal3D both beat Hunyuan3D 2.1. They
    produce textured meshes, and they cut the subject out of a cluttered photo where Hunyuan3D rebuilt the
    desk and monitor with it. TRELLIS.2 was the most faithful on two of three.
  - **Cost:** about 90–135 s per textured mesh vs about 25–35 s.
  - **Hunyuan3D 2.1 stays** as `--model hunyuan21`, the fast shape-only option, and is the path for the
    Blender color bakes.
  - **mesh3d loop:** it now judges the textured model, with the textured rubric. `--texture` / `--finalize`
    require `--mesh-model hunyuan21`; on a textured mesh they would overwrite its textures.
  - **Geometry gate:** the fragmentation check counts only significant parts (islands with at least 1% of the
    mesh). TRELLIS.2 models small details such as eyes and antenna tips as separate shells, so a clean toy
    robot the judge scored 1.0 failed on 12 raw parts (3 significant). Checks files from older runs fall back
    to the raw count. A mesh that shattered into many similar pieces, none holding half of it, fails too:
    150 equal shards each fell under the 1% bar, so the count read 0 and passed.

- **CAD STL/OBJ exports tessellate curves finer** (angular deflection 0.5 → 0.1 rad). At 0.5, a circle came
  out as about 13 visible flats in renders and prints. Round parts' STLs grow about 1.6×.
- **Tests can't reach the network or a developer's settings.** A socket-level guard refuses every connection
  (one test sent a GET to a running ComfyUI), `CHIMERA_*` and vendor key variables are cleared (VS Code loads
  `.env` into test runs), and git is faked for provenance. CI's Linux leg installs the `images` extra, so the
  contact sheet the judge scores is tested there; Windows CI stays on `[dev]` and proves the no-Pillow paths.

### Docs
- **All README media regenerated on the new defaults.**
  - A new hero: the classical fire-breathing Chimera on Qwen-Image-2.1 with a SeedVR2 detail pass.
  - The self-correction demo, re-run fully locally with the Ollama Qwen3-VL judge.
  - The image → video → 3D strip: one robot drawn by Qwen-Image, animated by Wan 2.2 and meshed by TRELLIS.2.
  - A textured Blender turntable and a new CAD part.
  - The whole example-brand showcase: images, fleet, video, foley, music and a textured TRELLIS.2 mesh.
- `docs/SETUP.md` lists what the defaults download and where Comfy-Org's `split_files/` files go.
- A docs pass against the code: the judge default, FreeCAD ≥ 1.1.4 everywhere, what `doctor` checks, the
  extra steps on ComfyUI 0.24–0.39, the example brand's model and how its GLB was made, FLUX.2's product
  denoise (0.65), the `--backend assistant` tier (interactive only), and what the MCP pins don't cover (their
  dependencies still float, and comfyui-mcp's optional `cloudflared` downloads its binary at install).
- The Brand Kits guide said a brand's `negative` shaped FLUX.2 images. No image recipe samples with it:
  Qwen-Image-2.1 and FLUX.2 run at CFG 1, where ComfyUI skips the negative pass, and Z-Image zeroes its
  negative. It only changes video sampled above CFG 1 (LTX-2.3, Wan 2.2 `--quality full`), and the
  self-correction loop judges renders against it. Word the positive to keep things out of an image.

### Erratum
- The **v0.5.0** notes overstated its validation ("smoke-validated live across image, video, 3D … and the full
  mesh3d self-correction loop"). That 2026-08-20 run routed stale files left in an old ComfyUI output folder for
  image, video and 3D; only render and cad were clean. The 2026-10-14 smoke above re-ran everything with
  fresh-output checks.

## [0.5.1] - 2026-08-20

Patch release: the blender_mcp bridge works again on fresh environments.

### Fixed
- **blender_mcp bridge dead on a fresh environment (`MCP error -32000: Connection closed`).**
  The pin bump to `4309a396` gave uvx a fresh env, which resolved the **unbounded** transitive
  `mcp[cli]` dependency to the new **MCP SDK 2.x** — upstream imports `mcp.server.fastmcp`
  (an SDK-1.x path that 2.x renamed), so the server died at import before ever reaching
  Blender's socket. `.mcp.json` now launches with `uvx --with "mcp[cli]~=1.12"` (≥ 1.12, < 2 — written `~=`
  because the args transit `cmd /c`, where a literal `<` is a redirection character), pinning the
  SDK at our layer until upstream ships a 2.x shim (freecad-mcp v0.1.22 already carries one; it is
  unaffected). The old pin only worked because its cached env predated SDK 2.x.

## [0.5.0] - 2026-08-20

The hardening release: a 53-finding adversarially-verified repo audit fixed end-to-end (21 bugs,
modularization tiers 1–2 — generate.py is now a 508-line parse+dispatch CLI over a shared brandkit
core), three re-audited dependency bumps, an extended comfyui-mcp security hold with
defense-in-depth opt-outs, a resilient weekly update checker, and the whole stack re-validated
live on ComfyUI Desktop 0.33.3. 566 GPU-free tests.

### Fixed
- **Weekly update-report resilience (from report #50's blind week).** All four GitHub pin checks
  degraded to an untriageable "could not check upstream (HTTPError)" — hiding two real
  behind-upstream warnings. Failure rows now carry the HTTP status (e.g. `HTTPError 403`), and the
  GitHub client retries a transient 5xx once (never a 4xx — a rate limit won't clear in seconds).
- **Watermark path repaired three ways** (from the 2026-08-03 deep-dive audit; all
  adversarially verified). Branded `--watermark` with `logo.default` unset now errors cleanly
  instead of crashing with a PermissionError on the scaffolded `logos/` directory; product/relight
  watermarks are placed against the **probed source-image size** (those graphs render at source
  size, not brand defaults); and `watermark.opacity < 1.0` finally works — the filler splices a
  `brand:watermark_blend` ImageBlend (blend factor = opacity) instead of silently ignoring the knob.
- **The brand.yaml `video:` block is honored through the CLI.** The video subparser's hard
  defaults (97 frames / 25 fps / 768×512 / audio on) always shadowed the documented per-brand
  block; flags now default to None so the manifest fallbacks run, `video.audio` is consumed, and
  the sidecar records the RESOLVED dims/audio so replay stays exact if the brand.yaml changes.
- **`parse_verdict` heuristics hardened** (same bug class as the earlier thinking-judge fix): the
  verdict comes from the trailing line STARTING with "overall" (a criterion reason like
  "overall composition passed" can no longer flip a FAIL to PASS), the score prefers the dedicated
  trailing `score:` line (prose like "scored 7 criteria" no longer clamps to 1.0), and a NOT-MET
  line phrased "overall proportions…" keeps its FIX feedback. `expander._strip_terms` is
  word-boundaried (avoid "toy" no longer guts "toyota").
- **Agent run sidecar records the BEST iteration's seed/prompt** (matched by verdict identity),
  not the last iteration's — on exhaustion they often differ.
- **DCC edge paths:** the Blender runner wraps corrupt-manifest JSON in `BlenderJobError`,
  surfaces stderr in the no-manifest error, and discovers the default Windows install via a
  version glob (5.2+-safe); `render --mode finish` rejects unsupported `--formats` host-side
  instead of exiting 0 with no export; `mesh_eval.py` actually restores the grey-clay material
  after a failed Phase-4a bake (a half-built emission tree rendered the judge stills black).
- **`doctor` preflights the inline auto-repaint graph's node types** (derived from
  `repaint.build` itself — a missing IPAdapter pack is caught before the Blender depth renders),
  loads brand.yaml once, and `update-check`'s pinned-deps line is sourced from
  `update_report`'s tables; a hung `git fetch` no longer reports "not a git checkout".
- **ComfyUI client:** HTTP-400 validation failures surface ComfyUI's per-node detail from the
  response body (the old `node_errors` check was dead code); renders reuse `wait()`'s history
  record instead of re-fetching `/history`.
- **brand.yaml sub-sections are type-checked at load** — `width: "1024"` fails in lint/load with
  the key named instead of a TypeError deep in a filler (ints still coerce where floats are
  expected). `_probe_video` honors its best-effort contract on corrupt files; `image --mode
  product` requires `--asset` (no silent logo-default substitution);
  `train_brand_lora.py --run` invokes only the requested backend and exits cleanly on failure.
- **Perf:** `repaint._mask_background` uses Pillow's C-level `point()`+`paste(mask)` instead of
  a ~1M-op per-view Python pixel loop. The CLI fails fast with a `pip install -e .` hint when
  run outside a repo checkout (a non-editable install doesn't package the templates).

### Security
- **`comfyui-mcp` hold extended through `0.50.x` (resolves #49).** The 0.50.93 gatekeeper scan
  confirms the default-on startup self-update + panel auto-install persist and adds a material
  escalation: **`npx` installs are now auto-update-ELIGIBLE** — the exact launch mode this repo
  uses would silently `npm install` latest at startup were the opt-outs unset. The pin stays on
  the audited `0.18.0`; the `COMFYUI_MCP_AUTOUPDATE=0` + `COMFYUI_MCP_PANEL_AUTOINSTALL=0`
  opt-outs added for #44 now guard against exactly this. Hold documented in
  `modules/agent/README.md` and `docs/STACK.md`.

### Changed
- **Reference build ComfyUI Desktop `0.26.2` → `0.33.3`** — the Desktop app self-updated; the full
  stack was smoke-validated live on it 2026-08-20 (image txt2img, LTX video i2v, Hunyuan3D mesh +
  Blender clay eval + Ollama Qwen3-VL judge via the mesh3d loop, headless Blender render, headless
  FreeCAD cad). The `≥0.24.x` floor is unchanged. `COMFY_REF`/STACK updated.
- **`ComfyUI-LTXVideo` `3b9c5cd → 15d09ab`** (re-audited per [`docs/UPDATING.md`](docs/UPDATING.md);
  resolves the item hidden behind report #50's failed check). 4 upstream commits: LTX-2.5 example
  workflows (inert JSON), the legacy RoPE helpers made self-contained in a new pure-math
  `rope_utils.py` (the old pin's legacy branch imported fork-only names from core), and Gemma-loader
  fixes (config.json-anchored dir resolution + LEFT padding for decoder-only generation). **No new
  nodes, deps, or network**; nothing used by `brand-video-i2v.json` is touched.
- **`blender_mcp` `98b0e49d → 4309a396`** (v1.0.0 +5; re-audited clean — resolves the blender item
  on report #50). 4 upstream commits: screenshot size-limit headroom for the JSON envelope, tool
  docstrings + readme restructure, lint config. No new tools, deps, or network; gates unchanged.
- **`freecad-mcp` `4c3f2ef → 3745ff9`** (v0.1.22; re-audited clean — 27 upstream commits). Adds a
  **new read-only `get_rpc_status` health tool** (Tier 3, ungated — reports stuck GUI dispatch
  without touching the GUI thread), stuck-task fail-fast, per-call `include_screenshot`/`view_name`
  params on existing tools, a 1024px auto-cap on screenshots, Wayland framebuffer capture (with
  legacy fallback), actual-name reporting, socket stop/close fixes, and an mcp 1.x/2.x import shim.
  **No new runtime deps, no new exec/network surface**; the Tier-1/2 gates are unchanged (tool
  count 14 → 15). Most changes are addon-side — **re-copy `addon/FreeCADMCP/` into FreeCAD's
  `Mod/` dir and restart FreeCAD** after updating.

- **Brandkit layering + shared plumbing** (deep-dive modularization, tier 1): `git_provenance`
  moved to `scripts/brandkit/provenance.py` (the agent layer no longer imports the CLI module —
  pinned by an import-graph test); `nodes.py` hosts the shared `node()`, `load_template()`, and
  `assert_free_ids()` helpers (splice injectors now fail loudly on reserved-id collisions,
  ids 70–99); logo and watermark placement share one geometry (`logo_geometry`); a new
  `dcc.py` provides the common Blender/FreeCAD runner core so the two can't drift apart again;
  the ComfyUI URL literal is deduped behind `comfy.DEFAULT_URL`.
- **Modularization tier 2 — generate.py is now a parse+dispatch CLI (938 → 508 lines).**
  The render/cad/finalize-texture orchestration (run_render/run_cad/run_finalize_texture +
  validators, params builders, and the shared `_resolve_asset` locator) moved to
  `scripts/brandkit/dcc_cli.py` beside the runners it drives; the sidecar-inputs/replay
  contract (`SIDECAR_INPUT_KEYS`, `resolve_model_used`, `resolve_sidecar_inputs`,
  `args_from_sidecar`) moved to `scripts/brandkit/replay.py` beside `sidecar.py` (generate.py
  re-exports the old names). New shared stages replace hand-rolled copies:
  `outputs.run_graph_to_file` (the queue→wait→select→local-path dance in the image loop, both
  mesh3d stages, and the auto-repaint view generator — now also reusing `wait()`'s history),
  `render_generate.eval_contact_sheet` (the mesh_eval + contact-sheet stage shared by the
  mesh3d and cad generators), and `finalize.even_azimuths` (one view-ring definition). The
  previously untested `update_report` GitHub/npm/ComfyUI checker arms gained coverage
  (515 → 560 tests across the two batches).
- **Docs truth sweep:** test counts 515 → **552** (README/STACK), STACK's CI table (checkout v7)
  and mermaid pack list (QwenVL retired), CONTRIBUTING's "CI (when enabled)" hedge, CLAUDE.md's
  structure comment (all shipped subcommands + agent modules), the Z-Image negative-prompt
  caveat in brand-kits.md, the FreeCADCmd `$CHIMERA_CAD_PARAMS` invocation in the cad docs,
  the video README `video:` example (real filename, no unsupported `lora:` key), and
  mesh_finalize's stale "roadmap" claim for the shipped auto-repaint backend.
- **`ComfyUI-LTXVideo` `4f45fd6 → 3b9c5cd`** (re-audited per [`docs/UPDATING.md`](docs/UPDATING.md);
  resolves the LTXVideo item on weekly report #42). 4 upstream commits: README/example-workflow
  additions (Pixel Spatial Upscaler IC-LoRA docs + an inert example JSON whose `GemmaAPITextEncode`
  reference has an empty api_key and stays covered by the standing "never use" exclusion) and one
  code change — a behavior-preserving try/except import shim in `embeddings_connector.py` for
  ComfyUI core's upcoming RoPE refactor (core PR #15056), with the legacy fallback verified
  math-equivalent. **No node/API surface changes**; none of the nodes used by
  `workflows/templates/brand-video-i2v.json` are touched. The bump is *protective*: the old pin
  imports the pre-refactor rope helpers unconditionally and would fail to import entirely on a
  future ComfyUI core that ships the refactor. Pin advanced in `docs/STACK.md`, `docs/CATALOG.md`,
  `modules/video/models.md`, and `scripts/update_report.py`.
- **`freecad-mcp` `1697aff → 4c3f2ef`** (re-audited per [`docs/UPDATING.md`](docs/UPDATING.md);
  resolves the freecad item on weekly report #42). 10 upstream commits = **v0.1.19**: stage-labeled
  FEM error handling, idle GUI-queue early-return, screenshot re-framing for occluded/minimized
  windows, and `get_view` RPC-failure error handling. Re-audit **clean**: no new network/egress, no
  new `eval`/`exec` sink, **no new/renamed MCP tools** (Tier gates in `.claude/settings.json` /
  `tests/test_mcp_gates.py` unchanged), no dependency changes (version bump only). 3 of the 5
  changed files live in `addon/FreeCADMCP/` — **re-copy the addon into FreeCAD's `Mod/` dir and
  restart FreeCAD** after updating (the `uvx` pin only refreshes the server half). Pin advanced in
  `.mcp.json`, `docs/STACK.md`, `docs/CATALOG.md`, `docs/SETUP.md`, `modules/cad/README.md`,
  `modules/cad/requirements.md`, `scripts/update_report.py`, and `tests/test_update_report.py`.

- **`comfyui-mcp` hold extended through `0.48.x` (resolves #41, #44).** The gatekeeper scans of
  0.24.5 (#41) and 0.48.1 (#44) found two **default-on startup behaviors** in the plain stdio path —
  a self-update that phones `registry.npmjs.org` every launch and can `npm i comfyui-mcp@latest` on
  disk for global/local installs, and a panel auto-install that mutates the ComfyUI install from an
  unpinned "nightly" channel — plus (0.48.x) a large new multi-provider agent/network surface. The
  pin **stays on the audited `0.18.0`**, and [`.mcp.json`](.mcp.json) now sets
  **`COMFYUI_MCP_AUTOUPDATE=0`** + **`COMFYUI_MCP_PANEL_AUTOINSTALL=0`** as defense-in-depth (inert
  on 0.18.0; they neutralize both behaviors if the pin ever drifts). Hold documented in
  `modules/agent/README.md` and `docs/STACK.md`.

- **`freecad-mcp` `63acb30 → 1697aff`** (re-audited per [`docs/UPDATING.md`](docs/UPDATING.md);
  resolves the freecad item on the weekly update report). 4 upstream bug-fix commits merged by the
  maintainer via PR #64 — FEM socket timeout that no longer aborts long solves, dict/list
  `References` parsing, RGB(A) `ShapeColor` normalisation, `getDocument` raises-vs-`None` handling,
  and FreeCAD addon import resolution. Re-audit **clean** (5-lens adversarial pass): no new
  network/egress, no new `eval`/`exec` sink (the pre-existing `execute_code` RCE is byte-for-byte
  unchanged), **no new MCP tools** (Tier gates in `.claude/settings.json` / `tests/test_mcp_gates.py`
  unchanged), no dependency/build changes. Pin advanced in `.mcp.json`, `docs/STACK.md`,
  `docs/CATALOG.md`, `docs/SETUP.md`, `modules/cad/README.md`, `modules/cad/requirements.md`,
  `scripts/update_report.py`, and `tests/test_update_report.py`.
### Fixed
- **ComfyUI MCP connection — `MCP error -32000: Connection closed`.** The `comfyui` entry in
  [`.mcp.json`](.mcp.json) previously set `NPM_CONFIG_OMIT=optional`, which on node ≥ 24 stripped
  `sharp`'s required native binary (`@img/sharp-*`, shipped as an optionalDependency) so the server
  crashed on startup (*"Could not load the sharp module"*). Replaced it with
  **`NPM_CONFIG_INCLUDE=optional`** — npm's `include` wins over any inherited `omit`, so the optional
  deps (crucially `sharp`'s binary) are forced to install. The optional cloud/tunnel/agent packages
  install too but stay **inert** behind env-gating (per-tool approval gates + loopback binding remain
  the real controls). If a stale error persists, clear the package's npx cache dir under `~/.npm/_npx`
  once and **fully restart the IDE** so it reinstalls and reloads the config. Documented in
  [`modules/agent/README.md`](modules/agent/README.md) and [`docs/STACK.md`](docs/STACK.md).
- **`comfyui-mcp` held on `0.18.0`; the `0.20.9` bump was reverted (resolves #38).** `0.20.9` fails to
  start — its compiled client imports `@stable-canvas/comfyui-client/dist/main.modern.mjs`, absent from
  client `1.5.9` (the only version its `^1.5.9` range allows) — and it adds a startup self-update that
  would auto-pull `@latest` and defeat pinning. It offers nothing this repo uses (all new surfaces are
  opt-in), so the pin stays on the working, audited 0.18.0.

## [0.4.0] - 2026-06-27

Adds **`image --mode relight`** — a FLUX.2 ReferenceLatent relight that changes a still's lighting
while preserving its exact composition (live-validated on ComfyUI 0.26.2) — plus brand-neutral,
field-tested technique notes distilled from production use.

### Added
- **`image --mode relight` — FLUX.2 ReferenceLatent relight.** Relight/restyle a still while keeping
  its **exact composition** (`--asset <source> --subject "<relight prompt>"`). Uses FLUX.2's native
  `ReferenceLatent` edit (encode the source → ride it on the positive conditioning → full-denoise
  sample), which holds the layout that plain img2img drifts. FLUX.2-only: a Z-Image brand default
  transparently falls back to `flux2_dev_fp8mixed.safetensors` (graph + sidecar agree via
  `resolve_image_model`). New parity-guarded template `brand-flux2-relight.json` (+ module mirror),
  `--mode relight` CLI, and filler wiring. **Live-validated on ComfyUI 0.26.2** (sunset + moonlight
  relights both preserved composition while transforming lighting). +4 tests.

### Docs
- **Field-tested technique notes from production use** (brand-neutral; technique only, no brand data):
  a creator-assets recipe doc [`modules/image/recipes.md`](modules/image/recipes.md) (platform
  emotes/stickers — GIF-not-APNG, background-cutout + dark-outline for light/dark legibility,
  matched-seed keyframes for real animation; tiered badge sets); an image-to-video **motion-realism**
  caveat in [`modules/video/README.md`](modules/video/README.md) (i2v reliably animates *energy/
  ambient* motion over a rigid subject, not mechanical/articulated motion); and a **3D-print/casting**
  prep note in [`modules/threed/README.md`](modules/threed/README.md) (prefer one watertight solid
  over a kit-of-parts; clean Hunyuan's stray background plane).
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

[Unreleased]: https://github.com/whartons/Chimera/compare/v0.6.1...HEAD
[0.6.1]: https://github.com/whartons/Chimera/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/whartons/Chimera/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/whartons/Chimera/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/whartons/Chimera/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/whartons/Chimera/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/whartons/Chimera/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/whartons/Chimera/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/whartons/Chimera/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/whartons/Chimera/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/whartons/Chimera/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/whartons/Chimera/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/whartons/Chimera/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/whartons/Chimera/releases/tag/v0.1.0
