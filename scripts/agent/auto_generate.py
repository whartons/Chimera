#!/usr/bin/env python3
"""Headless self-correction loop: generate -> VLM-judge -> refine, until PASS.

Wires the model-free agent core (expander + run_loop) to a real generator and a vision judge — the
OpenAI-compatible LLMJudge (`--backend api`, default: with nothing configured it calls a local Ollama model
sized to the GPU, see --llm-tier and llm.LOCAL_TIERS) or the optional ComfyUI Qwen3-VL node (`--backend
local`). Each iteration the expander folds the previous verdict's unmet-criterion issues back into the
prompt, so candidates converge on the rubric.

Pipelines (--pipeline):
  * image (default) — ComfyUI txt2img; the rubric scores the 2D render.
  * mesh3d         — txt2img concept -> image-to-3D mesh (TRELLIS.2 by default, textured; --mesh-model)
                     -> headless Blender contact-sheet render (4 orbit views) -> a FORM rubric (plus color
                     for a textured mesh), with deterministic bmesh geometry checks (loose parts, empty
                     mesh) folded into the verdict via GeometryAwareJudge. --from-image fixes the concept
                     and rerolls only the mesh.

--brand is OPTIONAL. With a brand, the rubric enforces that brand's style/palette/negative and the
winner routes into brands/<brand>/outputs/. Brandless (omit --brand), the rubric collapses to
subject + quality (image) or subject + form (mesh3d), and the winner routes into the global outputs/.

  python scripts/agent/auto_generate.py [--brand example-brand] --subject "an armored rover" \
      --comfy-output-dir <comfy_output_dir> [--max-iters 4] [--seeds 7,8,9] [--variant turbo]
  python scripts/agent/auto_generate.py --pipeline mesh3d --subject "an armored knight" \
      --comfy-output-dir <comfy_output_dir> [--from-image concept.png] [--octree 256] [--max-iters 3]

A third pipeline, `cad`, is fully autonomous generative CAD: a provider-agnostic LLM writes/revises a
FreeCAD script -> `cad --mode script` -> Blender contact-sheet render -> form judge -> revise.

Judge backends (--backend): `api` (default — a provider-agnostic, OpenAI-compatible LLM judge; with no
--judge-*/--llm-* flags or CHIMERA_* env it uses Chimera's local Ollama model for the GPU's tier (Qwen 3.8
27B on 32 GB cards, Qwen3-VL 8B on 12-24 GB, Qwen3-VL 4B below), else point it at OpenAI, Anthropic's
OpenAI-compat endpoint, OpenRouter, or any OpenAI-compatible server — a thinking model must run with
thinking off, or it returns empty content; see .env.example / scripts/agent/llm.py) or `local` (the
optional ComfyUI-QwenVL judge node). --comfy-output-dir routes
ComfyUI renders and is where the local judge drops verdicts; required except for `--pipeline cad
--backend api` (no ComfyUI).
"""
import argparse, datetime, sys, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent.expander import TemplatedExpander
from scripts.agent.judge import LocalVLMJudge, GeometryAwareJudge
from scripts.agent.loop import SeedNames, run_loop
from scripts.agent.rubric import build_rubric
from scripts.agent.render_generate import make_render_generate
from scripts.brandkit import workflow as image_filler
from scripts.brandkit.comfy import ComfyClient
from scripts.brandkit.manifest import ManifestError, load_manifest, default_manifest
from scripts.brandkit.outputs import brand_name_ok, route_output, run_graph_to_file, write_sidecar
from scripts.brandkit import gpu
from scripts.brandkit.comfy import DEFAULT_URL as DEFAULT_COMFY_URL
from scripts.brandkit.provenance import git_provenance


def _parse_seeds(raw):
    """'7,8,9' -> [7, 8, 9]; None/'' -> None (the caller picks fresh seeds)."""
    if not raw:
        return None
    return [int(s) for s in raw.split(",") if s.strip()]


def _run_seeds(raw, max_iters):
    """--seeds as given, else a fresh random run of seeds; a shorter --seeds list is topped up with fresh
    ones. The loop's fixed 1000+i default made a second run overwrite the first run's winner (outputs are
    named <mode>_<seed>); the seeds are printed so a run can be repeated with --seeds."""
    seeds = _parse_seeds(raw) or []
    if len(seeds) >= max_iters:
        return seeds
    import random
    base = random.randrange(1, 2**31 - 1000)
    seeds = seeds + [base + i for i in range(max_iters - len(seeds))]
    print(f"[agent] seeds {','.join(map(str, seeds))} (repeat this run with --seeds)", file=sys.stderr)
    return seeds


def _backend_error(backend):
    """Return an error message if `backend` can't run from this headless entrypoint, else None.
    'local' (ComfyUI Qwen3-VL judge) and 'api' (an OpenAI-compatible LLM judge, e.g. Ollama Qwen3-VL) are
    the autonomous paths. 'assistant' (multi-judge vision consensus) needs the agent's own eyes in the
    loop, which a bare subprocess doesn't have — so it's offered but gated: choose it and the CLI refuses,
    pointing at the local/api backends / the assistant recipe."""
    if backend == "assistant":
        return ("the 'assistant' consensus backend judges with the agent's own vision and only runs "
                "with the agent in the loop (see workflows/agent/README.md). For an unattended run use "
                "--backend local (the ComfyUI Qwen3-VL judge) or --backend api (e.g. Ollama Qwen3-VL).")
    return None


def _resolve_manifest(repo_root, brand):
    """With --brand, load brands/<brand>/brand.yaml (branded self-correction). Brandless (brand
    None/'') -> the neutral default_manifest(): build_rubric collapses to subject + quality, so the
    loop runs as a general QA gate and winners route to the global outputs/ (route_output's brandless
    path). Mirrors generate.py's brand-optional resolution."""
    if brand:
        return load_manifest(Path(repo_root) / "brands" / brand / "brand.yaml")
    return default_manifest()


def _make_generate(args, repo_root, manifest, client):
    """Build the loop's generate(pos, neg, seed) -> routed-image-path closure. Each call builds
    the txt2img graph, queues it, waits, and routes the result into the output folder (brand or
    global, per --brand) with mode label 'agent' so per-iteration renders are distinguishable."""
    out_dir = Path(args.comfy_output_dir)
    name = SeedNames()

    def generate(pos, neg, seed):
        wf = image_filler.build(repo_root, manifest, positive=pos, negative=neg, seed=seed,
                                mode="txt2img", variant=args.variant, model=args.model)
        local = run_graph_to_file(client, wf, out_dir, timeout=args.timeout)
        return str(route_output(repo_root, args.brand, local, "agent", name(seed)))

    return generate


def _write_run_sidecar(result, args, repo_root):
    """Write a sidecar next to the winning image summarizing the self-correction run."""
    if result.best_image is None:
        return
    # the record that produced best_image: match on the best verdict's identity — on exhaustion
    # the best iteration is often NOT the last one, and the sidecar must describe its neighbor file
    last = next((r for r in result.history if r.verdict is result.best_verdict),
                result.history[-1])
    meta = {
        # `kind` discriminator: this is a run summary, NOT a replayable render sidecar
        # (no inputs/model/negative) — generate.py replay refuses it on this key.
        "schema": 2, "kind": "agent-run",
        "modality": {"mesh3d": "3d", "cad": "cad"}.get(getattr(args, "pipeline", "image"), "image"),
        "mode": "agent",
        "brand": args.brand, "subject": args.subject, "agent": True,
        # the subject the loop ended on, when it dropped flagged off-brand styling from the original
        **({"corrected_subject": result.subject} if getattr(result, "subject", "") not in ("", args.subject) else {}),
        "backend": args.backend, "iterations": len(result.history),
        "passed": result.passed,
        "final_score": result.best_verdict.score if result.best_verdict else 0.0,
        "winning_seed": last.seed, "winning_prompt": last.prompt,
        "comfy_url": args.comfy_url,
        "provenance": {"pipeline_git_sha": git_provenance(repo_root)},
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    write_sidecar(result.best_image, meta)


def _share_gpu(client, llms):
    """The reverse of _hand_gpu_back: before a local Ollama model loads (judge, rewriter, CAD codegen),
    ComfyUI unloads its models if the card lacks room (gpu.make_room). ComfyUI keeps its models resident
    after a render; on 2026-10-15 the judge loading next to it had 0.1 GB free, timed out, and the GPU
    driver hung. Only for a ComfyUI on this machine (freeing a remote one frees nothing here)."""
    if not gpu.is_local(getattr(client, "base", "")):
        return
    for llm in llms:
        if llm is not None:
            llm.make_room = lambda need: gpu.make_room(client, need)


def _clear_other_ollama_models(llms):
    """Before the first render, unload local Ollama models this run didn't load (another tool's, or an
    earlier run's): ComfyUI can't see their memory, so a render beside them can overcommit the card the way
    the judge did on 2026-10-15. Checks the run's own local endpoints and the default Ollama; honours
    CHIMERA_KEEP_LLM_LOADED=1."""
    if gpu.keep_llms_loaded():
        return
    live = [llm for llm in llms if llm is not None and gpu.is_local(getattr(llm, "base_url", ""))]
    roots = {gpu.ollama_root(llm.base_url) for llm in live} | {gpu.ollama_root()}
    for root in roots:
        if not gpu.is_local(root):
            continue
        keep = {llm.ollama_name for llm in live if gpu.ollama_root(llm.base_url) == root}
        for name, vram in gpu.unload_others(root, keep):
            print(f"[gpu] unloaded {name} ({vram / 2**30:.1f} GB) from Ollama before rendering: ComfyUI can't "
                  "see that memory, so rendering beside it could overcommit the card", file=sys.stderr)
        stuck = [n for n, _ in gpu.loaded_models(root) if not any(gpu.same_model(n, k) for k in keep)]
        if stuck:
            sys.exit(f"[gpu] Ollama still holds {', '.join(stuck)} and rendering beside it could overcommit the "
                     "card (ComfyUI can't see that memory): run `python scripts/generate.py free`, or close the "
                     "app using it, then retry")


def _endpoint_problems(roles):
    """[(role, message)] for each role a local Ollama can't serve: Ollama not answering, or the model not
    pulled. Checked before anything renders: v0.6 made a local model the default judge, and a run with Ollama
    down rendered every iteration (3D meshes and Blender included) and only then failed at the judge. A local
    server that isn't Ollama (LM Studio, vLLM) is left alone unless it sits at Ollama's address or port."""
    out = []
    for role, llm in roles:
        if llm is None or not gpu.is_local(llm.base_url):
            continue
        root = gpu.ollama_root(llm.base_url)
        if gpu.is_ollama(root):
            if not any(gpu.same_model(n, llm.ollama_name) for n in gpu.pulled_models(root)):
                out.append((role, f"Ollama at {root} doesn't have the {role} model {llm.model}: run "
                                  f"`ollama pull {llm.model}`"))
        elif root == gpu.ollama_root() or urllib.parse.urlsplit(root).port == 11434:
            out.append((role, f"the {role} model {llm.model} runs on Ollama at {root}, which isn't answering: "
                              "start Ollama, or point the role elsewhere (see --llm-tier and --judge-base-url)"))
    return out


def _release_all(clients):
    """Unload each client's local model; the models Ollama still holds afterwards (none with
    CHIMERA_KEEP_LLM_LOADED=1, which keeps them on purpose)."""
    for c in clients:
        c.release()
    if gpu.keep_llms_loaded():
        return []
    return [c.model for c in clients if getattr(c, "resident", None) and c.resident()]


def _same_llm(a, b):
    """True when two role clients run the same model on the same server (the large tier's code-gen and judge)."""
    ma, mb = getattr(a, "model", None), getattr(b, "model", None)
    return bool(ma and mb) and getattr(a, "base_url", None) == getattr(b, "base_url", None) and gpu.same_model(ma, mb)


def _hand_gpu_back(generate, clients):
    """Unload this run's local Ollama models before every render (LLMClient.release), so a resident
    judge/rewriter never starves ComfyUI or Blender on a single GPU. A no-op for hosted endpoints. A model
    that won't unload stops that iteration rather than render beside memory ComfyUI can't see."""
    live = [c for c in clients if c is not None]
    if not live:
        return generate

    def wrapped(*args, **kwargs):
        stuck = _release_all(live)
        if stuck:
            raise RuntimeError(f"{', '.join(stuck)} is still loaded in Ollama, so not rendering beside it "
                               "(ComfyUI can't see that memory); `python scripts/generate.py free` unloads it")
        return generate(*args, **kwargs)
    return wrapped


def _print_summary(result):
    print(f"\n[agent] winning image: {result.best_image}")
    print(f"[agent] passed={result.passed} "
          f"best_score={result.best_verdict.score if result.best_verdict else 0.0}")
    for rec in result.history:
        print(f"  iter {rec.iter}: seed={rec.seed} score={rec.verdict.score} "
              f"{'PASS' if rec.verdict.passed else 'FAIL'}")


def main():
    for stream in (sys.stdout, sys.stderr):   # a name outside the console's code page crashed a piped run
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(prog="auto_generate.py",
                                 description="Headless self-correction loop (generate, VLM-judge, refine).")
    ap.add_argument("--brand", default=None,
                    help="brand folder under brands/; omit for general (non-branded) "
                         "self-correction (subject+quality rubric, output -> outputs/)")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--max-iters", dest="max_iters", type=int, default=None)
    ap.add_argument("--seeds", default=None, help="comma-separated seeds, one per iteration")
    ap.add_argument("--backend", choices=["api", "local", "assistant"], default="api",
                    help="api = OpenAI-compatible LLM judge (default; unconfigured, it uses a local Ollama model "
                         "sized to your GPU, see --llm-tier; --judge-*/--llm-* or CHIMERA_* point it anywhere, "
                         "see .env.example); local = the optional ComfyUI-QwenVL judge node; assistant = "
                         "agent-driven vision consensus (requires the agent in the loop)")
    ap.add_argument("--pipeline", choices=["image", "mesh3d", "cad"], default="image",
                    help="image = txt2img self-correction (default); mesh3d = concept -> image-to-3D mesh "
                         "(TRELLIS.2 by default) -> Blender contact-sheet render -> form judge; cad = LLM writes "
                         "a FreeCAD script -> cad -> render -> judge -> revise (autonomous generative CAD)")
    ap.add_argument("--from-image", dest="from_image", default=None,
                    help="(mesh3d) fix the concept image and reroll only the mesh (skips txt2img)")
    ap.add_argument("--octree", type=int, default=None, help="(mesh3d, Hunyuan3D only) octree_resolution")
    ap.add_argument("--mesh-model", dest="mesh_model", default=None,
                    help="(mesh3d) 3D model: trellis2 (default, textured) | pixal3d (textured) | hunyuan21 "
                         "(shape only, ~4x faster; needed for --texture / --finalize), or a file name")
    ap.add_argument("--samples", type=int, default=48, help="(mesh3d) Cycles samples per still")
    ap.add_argument("--res", type=int, nargs=2, default=[640, 640],
                    help="(mesh3d) per-still resolution W H")
    ap.add_argument("--blender-bin", dest="blender_bin", default=None,
                    help="(mesh3d) path to the Blender executable (else $BLENDER_BIN / PATH / default)")
    ap.add_argument("--blender-timeout", dest="blender_timeout", type=int, default=None,
                    help="(mesh3d) max seconds for the Blender render job (default 1800)")
    ap.add_argument("--texture", action="store_true",
                    help="(mesh3d) bake a front-projected albedo texture so the loop judges color "
                         "(Phase 4a: front-faithful, back palette-filled)")
    ap.add_argument("--back-fill", dest="back_fill", choices=["palette", "mirror"], default="palette",
                    help="(mesh3d --texture) fill for faces the front concept can't see "
                         "(palette = flat brand color; mirror = back-project a flipped concept)")
    ap.add_argument("--texture-res", dest="texture_res", type=int, default=1024,
                    help="(mesh3d --texture) baked albedo resolution")
    ap.add_argument("--finalize", action="store_true",
                    help="(mesh3d) after the loop, texture the winning mesh via the multi-view "
                         "auto-repaint bake and re-judge it (informational). Emits a textured GLB "
                         "and prints a copy-paste retry command. Mutually exclusive with --texture.")
    ap.add_argument("--finalize-views", dest="finalize_views", type=int, default=4,
                    help="(mesh3d --finalize) ring views to generate + bake (1..7; default 4)")
    ap.add_argument("--comfy-url", dest="comfy_url", default=DEFAULT_COMFY_URL)
    ap.add_argument("--comfy-output-dir", dest="comfy_output_dir", default=None,
                    help="ComfyUI output dir: routes renders (and is where the --backend local judge drops "
                         "verdicts). Required except for `--pipeline cad --backend api` (no ComfyUI in that loop).")
    ap.add_argument("--freecad-bin", dest="freecad_bin", default=None,
                    help="(cad) FreeCADCmd path (else $FREECAD_BIN / PATH / default install)")
    ap.add_argument("--freecad-timeout", dest="freecad_timeout", type=int, default=None,
                    help="(cad) max seconds for the FreeCAD script job (default 600)")
    ap.add_argument("--llm-base-url", dest="llm_base_url", default=None,
                    help="(api/cad) OpenAI-compatible base URL (else $CHIMERA_LLM_BASE_URL); e.g. "
                         "https://api.openai.com/v1, https://api.anthropic.com/v1, http://localhost:11434/v1")
    ap.add_argument("--llm-model", dest="llm_model", default=None,
                    help="(api/cad) shared fallback model for all roles (else $CHIMERA_LLM_MODEL); "
                         "e.g. gpt-4o, claude-opus-4-8")
    ap.add_argument("--codegen-base-url", dest="codegen_base_url", default=None,
                    help="(cad) codegen LLM base URL — overrides --llm-base-url for codegen (else $CHIMERA_CODEGEN_BASE_URL)")
    ap.add_argument("--codegen-model", dest="codegen_model", default=None,
                    help="(cad) codegen model — overrides --llm-model for codegen (else $CHIMERA_CODEGEN_MODEL)")
    ap.add_argument("--judge-base-url", dest="judge_base_url", default=None,
                    help="(--backend api) judge LLM base URL — overrides --llm-base-url for the judge (else $CHIMERA_JUDGE_BASE_URL)")
    ap.add_argument("--judge-model", dest="judge_model", default=None,
                    help="(--backend api) judge model — overrides --llm-model for the judge (else $CHIMERA_JUDGE_MODEL)")
    ap.add_argument("--rewriter-base-url", dest="rewriter_base_url", default=None,
                    help="(--rewrite-prompts) rewriter LLM base URL — overrides --llm-base-url (else $CHIMERA_REWRITER_BASE_URL)")
    ap.add_argument("--rewriter-model", dest="rewriter_model", default=None,
                    help="(--rewrite-prompts) rewriter model — overrides --llm-model (else $CHIMERA_REWRITER_MODEL)")
    ap.add_argument("--llm-reasoning-effort", dest="llm_reasoning", default=None,
                    help="(api/cad) reasoning_effort sent to every role, e.g. none|low|medium|high (else "
                         "$CHIMERA_LLM_REASONING_EFFORT; unset = not sent, with an automatic retry at 'none' "
                         "when a thinking model returns only reasoning)")
    ap.add_argument("--codegen-reasoning-effort", dest="codegen_reasoning", default=None,
                    help="(cad) codegen reasoning_effort — overrides --llm-reasoning-effort (else $CHIMERA_CODEGEN_REASONING_EFFORT)")
    ap.add_argument("--judge-reasoning-effort", dest="judge_reasoning", default=None,
                    help="(--backend api) judge reasoning_effort (else $CHIMERA_JUDGE_REASONING_EFFORT)")
    ap.add_argument("--rewriter-reasoning-effort", dest="rewriter_reasoning", default=None,
                    help="(--rewrite-prompts) rewriter reasoning_effort (else $CHIMERA_REWRITER_REASONING_EFFORT)")
    ap.add_argument("--rewrite-prompts", dest="rewrite_prompts", action="store_true",
                    help="(image/mesh3d) use an LLM to rewrite prompts from the judge's FIX feedback instead "
                         "of the templated expander; falls back to templated on any LLM error")
    ap.add_argument("--llm-tier", dest="llm_tier", choices=["auto", "large", "medium", "small"], default=None,
                    help="Chimera's local Ollama models for roles you haven't configured. large (32 GB cards): Qwen 3.8 "
                         "27B for every role; medium (12-24 GB): Qwen3-VL 8B judge and rewriter; small (under 12 GB): "
                         "Qwen3-VL 4B judge and rewriter. Code-gen is Qwen 3.8 27B in every tier (partly on the CPU "
                         "below 24 GB). Default auto, from the GPU's memory (else $CHIMERA_LLM_TIER)")
    ap.add_argument("--judge-passes", dest="judge_passes", type=int, default=1,
                    help="(--backend api) number of LLM vision passes to consensus-judge (default 1)")
    ap.add_argument("--variant", choices=["base", "turbo"], default=None,
                    help="Z-Image fidelity (turbo=8-step default, base=25-step)")
    ap.add_argument("--model", default=None,
                    help="image model/family override (the concept image for mesh3d; the 3D model is --mesh-model)")
    ap.add_argument("--timeout", type=int, default=900, help="per-render wait (s)")
    args = ap.parse_args()
    backend_err = _backend_error(args.backend)
    if backend_err:
        ap.error(backend_err)
    if args.texture and args.pipeline != "mesh3d":
        ap.error("--texture applies only to --pipeline mesh3d")
    if args.back_fill != "palette" and not args.texture:
        ap.error("--back-fill applies only with --texture (mesh3d albedo bake)")
    if args.finalize and args.pipeline != "mesh3d":
        ap.error("--finalize applies only to --pipeline mesh3d")
    if args.finalize and args.texture:
        ap.error("--finalize and --texture are mutually exclusive (both target color; --finalize is "
                 "the all-around multi-view bake on the winner, --texture is per-iteration front-albedo)")
    if args.finalize and not 1 <= args.finalize_views <= 7:
        ap.error("--finalize-views must be 1..7 (Blender's 8-UV-layer cap minus the bake atlas)")
    # comfy-output-dir is needed for ComfyUI generation (image/mesh3d) and for the Qwen judge; the only
    # loop that touches neither is `cad` + the LLM judge.
    if not args.comfy_output_dir and not (args.pipeline == "cad" and args.backend == "api"):
        ap.error("--comfy-output-dir is required (ComfyUI render and/or the Qwen judge write there); "
                 "omit it only for `--pipeline cad --backend api`")

    if args.max_iters is None:
        args.max_iters = 3 if args.pipeline in ("mesh3d", "cad") else 4
    if args.brand and not brand_name_ok(args.brand):
        ap.error(f"--brand {args.brand!r} isn't a brand folder name (one plain name, not starting with '.')")
    try:
        seeds = _run_seeds(args.seeds, args.max_iters)
    except ValueError:
        ap.error(f"--seeds takes whole numbers separated by commas (got {args.seeds!r})")

    repo_root = Path(__file__).resolve().parents[2]
    try:
        m = _resolve_manifest(repo_root, args.brand)
    except ManifestError as e:   # a brand you don't have, or a brand.yaml mistake: one line, like generate.py
        ap.error(f"brand {args.brand!r}: {e}")
    mesh_textured = False
    if args.pipeline == "mesh3d":
        from scripts.brandkit import threed as threed_filler
        mesh_file = threed_filler.resolved_model(m, args.mesh_model)
        mesh_textured = threed_filler.is_textured(mesh_file)
        if mesh_textured and (args.texture or args.finalize):
            ap.error(f"--texture / --finalize color a shape-only mesh, but {mesh_file} already comes out "
                     "textured; add --mesh-model hunyuan21 for the shape-only + bake path")
    client = ComfyClient(args.comfy_url)
    # Per-role LLM clients (codegen / judge / rewriter), each independently configurable and falling
    # back to the shared --llm-* / CHIMERA_LLM_*. Built only for the roles a run uses. An AI agent
    # driving interactively supersedes all of this (see the role-tagged LLMConfigError hint).
    from scripts.agent.llm import LOCAL_TIERS, LLMConfigError, client_for_role, default_local_base, local_tier
    codegen_llm = judge_llm = rewriter_llm = None
    try:
        # with nothing configured, a role falls back to Chimera's local Ollama model for this GPU's tier
        gpu_gb = None if args.llm_tier not in (None, "auto") else gpu.total_memory_gb(client)
        tier = local_tier(gpu_gb, args.llm_tier)
        spec = LOCAL_TIERS[tier]
        shared = dict(shared_cli_base=args.llm_base_url, shared_cli_model=args.llm_model,
                      shared_cli_reasoning=args.llm_reasoning, default_base=default_local_base())

        def role_defaults(role):
            return dict(default_model=spec[role][0], default_reasoning=spec[role][1])
        if args.pipeline == "cad":
            codegen_llm = client_for_role("codegen", cli_base=args.codegen_base_url, cli_model=args.codegen_model,
                                          cli_reasoning=args.codegen_reasoning, **role_defaults("codegen"), **shared)
        if args.backend == "api":
            judge_llm = client_for_role("judge", cli_base=args.judge_base_url, cli_model=args.judge_model,
                                        cli_reasoning=args.judge_reasoning, **role_defaults("judge"), **shared)
        if args.rewrite_prompts:
            rewriter_llm = client_for_role("rewriter", cli_base=args.rewriter_base_url, cli_model=args.rewriter_model,
                                           cli_reasoning=args.rewriter_reasoning, **role_defaults("rewriter"), **shared)
    except LLMConfigError as e:
        ap.error(str(e))
    fallen_back = [f"{role} {llm.model}" for role, llm in (("judge", judge_llm), ("code-gen", codegen_llm),
                                                         ("rewriter", rewriter_llm))
                   if llm is not None and getattr(llm, "from_default", False)]
    if fallen_back:
        size = f"{gpu_gb:.0f} GB GPU" if gpu_gb else ("chosen" if args.llm_tier not in (None, "auto") else "GPU size unknown")
        print(f"[agent] local models, {tier} tier ({size}): {', '.join(fallen_back)} (--llm-tier to change)",
              file=sys.stderr)
    problems = _endpoint_problems([("judge", judge_llm), ("code-gen", codegen_llm), ("rewriter", rewriter_llm)])
    for role, msg in problems:
        if role == "rewriter":   # optional: the templated expander takes over on any rewriter error
            print(f"warning: {msg}; --rewrite-prompts falls back to the templated expander", file=sys.stderr)
    fatal = [msg for role, msg in problems if role != "rewriter"]
    if fatal:
        ap.error("; ".join(fatal))
    # the hand-back protects a GPU this machine shares: an image run on a remote ComfyUI renders elsewhere, so
    # unloading local models before each render (or refusing to render beside a stuck one) gains nothing
    shares_gpu = gpu.is_local(args.comfy_url) or args.pipeline != "image"
    _share_gpu(client, [codegen_llm, judge_llm, rewriter_llm])
    if shares_gpu:
        _clear_other_ollama_models([codegen_llm, judge_llm, rewriter_llm])

    if rewriter_llm is not None:
        from scripts.agent.llm import LLMExpander
        expander = LLMExpander(rewriter_llm, modality=("3d" if args.pipeline in ("mesh3d", "cad") else "image"))
    else:
        expander = TemplatedExpander()

    def build_judge():
        if args.backend == "api":
            from scripts.agent.llm import LLMJudge
            return LLMJudge(judge_llm, passes=args.judge_passes)
        return LocalVLMJudge(client, repo_root, args.comfy_output_dir)

    if args.pipeline == "cad":
        from scripts.agent.cad_generate import make_cad_generate
        from scripts.agent.llm import LLMCadGenerator
        rubric = build_rubric(m, args.subject, modality="3d")   # clean-solid form rubric (BREP is manifold)
        # the judge and rewriter go before each iteration's renders too (code-gen releases itself before
        # Blender): a resident judge sat beside the next Blender render and a --backend local judge graph. One
        # on code-gen's own model is left to code-gen, which loads it next and releases it before Blender.
        generate = _hand_gpu_back(make_cad_generate(args, repo_root, LLMCadGenerator(codegen_llm)),
                                  [c for c in (judge_llm, rewriter_llm) if not _same_llm(c, codegen_llm)])
        judge = GeometryAwareJudge(build_judge(), strict=True)   # manifold, but a script can build separate bodies
    elif args.pipeline == "mesh3d":
        # textured: the Phase-4a front bake (--texture) or a 3D model that bakes its own textures
        rubric = build_rubric(m, args.subject, modality="3d", textured=bool(args.texture) or mesh_textured)
        generate = _hand_gpu_back(make_render_generate(args, repo_root, m, client), [judge_llm, rewriter_llm])
        judge = GeometryAwareJudge(build_judge())
    else:
        rubric = None  # run_loop builds the image rubric
        generate = _hand_gpu_back(_make_generate(args, repo_root, m, client),
                                  [judge_llm, rewriter_llm] if shares_gpu else [])
        judge = build_judge()

    try:
        result = run_loop(expander=expander, judge=judge, generate=generate, manifest=m,
                          subject=args.subject, rubric=rubric, max_iters=args.max_iters, seeds=seeds)

        _print_summary(result)
        _write_run_sidecar(result, args, repo_root)

        if args.finalize and args.pipeline == "mesh3d":
            from scripts.agent.finalize import finalize_winner
            # build_judge() here is the UN-wrapped judge (the loop wrapped it in GeometryAwareJudge for
            # shape; texture quality is color/material, not geometry).
            # the finalize repaint renders through ComfyUI too: not beside a model that won't unload (skipped,
            # not failed: finalize never costs the run its already-good shape)
            stuck = _release_all([c for c in (judge_llm, rewriter_llm) if c is not None])
            if stuck:
                print(f"[finalize] skipped: {', '.join(stuck)} is still loaded in Ollama and ComfyUI can't see that "
                      "memory. `python scripts/generate.py free` unloads it; then texture the winner with "
                      "`python scripts/generate.py finalize-texture --auto-repaint`", file=sys.stderr)
            else:
                finalize_winner(result, args, repo_root=repo_root, manifest=m,
                                judge=build_judge(), client=client)
    finally:
        # leave the GPU clean for whatever runs next, even on failure (Ollama would otherwise keep a
        # 27B codegen model resident for ~5 minutes; see LLMClient.release)
        for llm in (codegen_llm, judge_llm, rewriter_llm):
            if llm is not None:
                llm.release()
    if not result.passed:
        sys.exit(1)   # a run where nothing passed is a failure to callers/CI, not a silent success


if __name__ == "__main__":
    main()
