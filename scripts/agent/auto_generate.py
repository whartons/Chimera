#!/usr/bin/env python3
"""Headless self-correction loop (local backend): generate -> VLM-judge -> refine, until PASS.

Wires the model-free agent core (expander + run_loop) to a real generator and a Qwen3-VL judge — a
ComfyUI Qwen3-VL node (`--backend local`, default) or the OpenAI-compatible LLMJudge (`--backend api`,
recommended: Qwen3-VL-8B via Ollama). Each iteration the expander folds the previous verdict's
unmet-criterion issues back into the prompt, so candidates converge on the rubric.

Two pipelines (--pipeline):
  * image (default) — ComfyUI txt2img; the rubric scores the 2D render.
  * mesh3d         — txt2img concept -> Hunyuan3D mesh -> headless Blender contact-sheet render
                     (4 orbit views) -> a FORM rubric judged on the grey-clay render, with
                     deterministic bmesh geometry checks (watertight/manifold/loose-parts) folded
                     into the verdict via GeometryAwareJudge. --from-image fixes the concept and
                     rerolls only the mesh.

--brand is OPTIONAL. With a brand, the rubric enforces that brand's style/palette/negative and the
winner routes into brands/<brand>/outputs/. Brandless (omit --brand), the rubric collapses to
subject + quality (image) or subject + form (mesh3d), and the winner routes into the global outputs/.

  python scripts/agent/auto_generate.py [--brand example-brand] --subject "an armored rover" \
      --comfy-output-dir <comfy_output_dir> [--max-iters 4] [--seeds 7,8,9] [--variant turbo]
  python scripts/agent/auto_generate.py --pipeline mesh3d --subject "an armored knight" \
      --comfy-output-dir <comfy_output_dir> [--from-image concept.png] [--octree 256] [--max-iters 3]

A third pipeline, `cad`, is fully autonomous generative CAD: a provider-agnostic LLM writes/revises a
FreeCAD script -> `cad --mode script` -> Blender contact-sheet render -> form judge -> revise.

Judge backends (--backend): `local` (a ComfyUI Qwen3-VL judge node, default) or `api` (RECOMMENDED — a
provider-agnostic, OpenAI-compatible LLM judge; point --judge-base-url/--judge-model at local Ollama
qwen3-vl:8b-instruct, OpenAI, Anthropic's OpenAI-compat endpoint, OpenRouter, or any OpenAI-compatible
server — use a NON-thinking '-instruct' VLM judge (a thinking model returns empty content); see
.env.example / scripts/agent/llm.py). --comfy-output-dir routes ComfyUI renders and is where the local
judge drops verdicts; required except for `--pipeline cad --backend api` (no ComfyUI).
"""
import argparse, datetime, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent.expander import TemplatedExpander
from scripts.agent.judge import LocalVLMJudge, GeometryAwareJudge
from scripts.agent.loop import run_loop
from scripts.agent.rubric import build_rubric
from scripts.agent.render_generate import make_render_generate
from scripts.brandkit import workflow as image_filler
from scripts.brandkit.comfy import ComfyClient
from scripts.brandkit.manifest import load_manifest, default_manifest
from scripts.brandkit.outputs import select_output, route_output, write_sidecar
from scripts.generate import git_provenance


def _parse_seeds(raw):
    """'7,8,9' -> [7, 8, 9]; None/'' -> None (loop falls back to its deterministic seeds)."""
    if not raw:
        return None
    return [int(s) for s in raw.split(",") if s.strip()]


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

    def generate(pos, neg, seed):
        wf = image_filler.build(repo_root, manifest, positive=pos, negative=neg, seed=seed,
                                mode="txt2img", variant=args.variant, model=args.model)
        pid = client.queue_prompt(wf)
        client.wait(pid, max_wait=args.timeout)
        fname, subfolder, _ = select_output(client, pid, wf)
        dest = route_output(repo_root, args.brand, out_dir / subfolder / fname, "agent", seed)
        return str(dest)

    return generate


def _write_run_sidecar(result, args, repo_root):
    """Write a sidecar next to the winning image summarizing the self-correction run."""
    if result.best_image is None:
        return
    last = result.history[-1]
    meta = {
        # `kind` discriminator: this is a run summary, NOT a replayable render sidecar
        # (no inputs/model/negative) — generate.py replay refuses it on this key.
        "schema": 2, "kind": "agent-run",
        "modality": {"mesh3d": "3d", "cad": "cad"}.get(getattr(args, "pipeline", "image"), "image"),
        "mode": "agent",
        "brand": args.brand, "subject": args.subject, "agent": True,
        "backend": args.backend, "iterations": len(result.history),
        "passed": result.passed,
        "final_score": result.best_verdict.score if result.best_verdict else 0.0,
        "winning_seed": last.seed, "winning_prompt": last.prompt,
        "comfy_url": args.comfy_url,
        "provenance": {"pipeline_git_sha": git_provenance(repo_root)},
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    write_sidecar(result.best_image, meta)


def _print_summary(result):
    print(f"\n[agent] winning image: {result.best_image}")
    print(f"[agent] passed={result.passed} "
          f"best_score={result.best_verdict.score if result.best_verdict else 0.0}")
    for rec in result.history:
        print(f"  iter {rec.iter}: seed={rec.seed} score={rec.verdict.score} "
              f"{'PASS' if rec.verdict.passed else 'FAIL'}")


def main():
    ap = argparse.ArgumentParser(prog="auto_generate.py",
                                 description="Headless brand self-correction loop (local VLM judge).")
    ap.add_argument("--brand", default=None,
                    help="brand folder under brands/; omit for general (non-branded) "
                         "self-correction (subject+quality rubric, output -> outputs/)")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--max-iters", dest="max_iters", type=int, default=None)
    ap.add_argument("--seeds", default=None, help="comma-separated seeds, one per iteration")
    ap.add_argument("--backend", choices=["local", "api", "assistant"], default="local",
                    help="local = ComfyUI Qwen3-VL judge node (default); api = OpenAI-compatible LLM judge "
                         "(RECOMMENDED — point --llm-base-url/--llm-model or CHIMERA_* at local Ollama "
                         "qwen3-vl:8b-instruct [non-thinking] or any cloud; see .env.example / scripts/agent/llm.py); "
                         "assistant = agent-driven vision consensus (requires the agent in the loop)")
    ap.add_argument("--pipeline", choices=["image", "mesh3d", "cad"], default="image",
                    help="image = txt2img self-correction (default); mesh3d = concept -> Hunyuan3D "
                         "mesh -> Blender contact-sheet render -> form judge; cad = LLM writes a FreeCAD "
                         "script -> cad -> render -> judge -> revise (autonomous generative CAD)")
    ap.add_argument("--from-image", dest="from_image", default=None,
                    help="(mesh3d) fix the concept image and reroll only the mesh (skips txt2img)")
    ap.add_argument("--octree", type=int, default=None, help="(mesh3d) Hunyuan3D octree_resolution")
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
    ap.add_argument("--comfy-url", dest="comfy_url", default="http://127.0.0.1:8000")
    ap.add_argument("--comfy-output-dir", dest="comfy_output_dir", default=None,
                    help="ComfyUI output dir: routes renders AND is where the Qwen judge drops verdicts. "
                         "Required except for `--pipeline cad --backend api` (no ComfyUI in that loop).")
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
    ap.add_argument("--rewrite-prompts", dest="rewrite_prompts", action="store_true",
                    help="(image/mesh3d) use an LLM to rewrite prompts from the judge's FIX feedback instead "
                         "of the templated expander; falls back to templated on any LLM error")
    ap.add_argument("--judge-passes", dest="judge_passes", type=int, default=1,
                    help="(--backend api) number of LLM vision passes to consensus-judge (default 1)")
    ap.add_argument("--variant", choices=["base", "turbo"], default=None,
                    help="Z-Image fidelity (turbo=8-step default, base=25-step)")
    ap.add_argument("--model", default=None, help="image model/family override")
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

    repo_root = Path(__file__).resolve().parents[2]
    m = _resolve_manifest(repo_root, args.brand)
    client = ComfyClient(args.comfy_url)
    # Per-role LLM clients (codegen / judge / rewriter), each independently configurable and falling
    # back to the shared --llm-* / CHIMERA_LLM_*. Built only for the roles a run uses. An AI agent
    # driving interactively supersedes all of this (see the role-tagged LLMConfigError hint).
    from scripts.agent.llm import LLMConfigError, client_for_role
    codegen_llm = judge_llm = rewriter_llm = None
    try:
        if args.pipeline == "cad":
            codegen_llm = client_for_role("codegen", cli_base=args.codegen_base_url, cli_model=args.codegen_model,
                                          shared_cli_base=args.llm_base_url, shared_cli_model=args.llm_model)
        if args.backend == "api":
            judge_llm = client_for_role("judge", cli_base=args.judge_base_url, cli_model=args.judge_model,
                                        shared_cli_base=args.llm_base_url, shared_cli_model=args.llm_model)
        if args.rewrite_prompts:
            rewriter_llm = client_for_role("rewriter", cli_base=args.rewriter_base_url, cli_model=args.rewriter_model,
                                           shared_cli_base=args.llm_base_url, shared_cli_model=args.llm_model)
    except LLMConfigError as e:
        ap.error(str(e))

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
        generate = make_cad_generate(args, repo_root, LLMCadGenerator(codegen_llm))
        judge = build_judge()
    elif args.pipeline == "mesh3d":
        rubric = build_rubric(m, args.subject, modality="3d", textured=bool(args.texture))
        generate = make_render_generate(args, repo_root, m, client)
        judge = GeometryAwareJudge(build_judge())
    else:
        rubric = None  # run_loop builds the image rubric
        generate = _make_generate(args, repo_root, m, client)
        judge = build_judge()

    result = run_loop(expander=expander, judge=judge, generate=generate, manifest=m,
                      subject=args.subject, rubric=rubric, max_iters=args.max_iters,
                      seeds=_parse_seeds(args.seeds))

    _print_summary(result)
    _write_run_sidecar(result, args, repo_root)

    if args.finalize and args.pipeline == "mesh3d":
        from scripts.agent.finalize import finalize_winner
        # build_judge() here is the UN-wrapped judge (the loop wrapped it in GeometryAwareJudge for
        # shape; texture quality is color/material, not geometry).
        finalize_winner(result, args, repo_root=repo_root, manifest=m,
                        judge=build_judge(), client=client)


if __name__ == "__main__":
    main()
