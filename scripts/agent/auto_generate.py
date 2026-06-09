#!/usr/bin/env python3
"""Headless self-correction loop (local backend): render -> VLM-judge -> refine, until PASS.

Wires the model-free agent core (expander + run_loop) to the real ComfyUI image filler and a
local Qwen2.5-VL judge (LocalVLMJudge over the agent-vlm-judge.json graph). Each iteration the
expander folds the previous verdict's unmet-criterion issues back into the prompt, so renders
converge on the rubric.

--brand is OPTIONAL. With a brand, the rubric enforces that brand's style/palette/negative and the
winner routes into brands/<brand>/outputs/. Brandless (omit --brand), the rubric collapses to
subject + quality (a general "is this actually X, and is it sharp/clean?" QA gate) and the winner
routes into the global outputs/.

  python scripts/agent/auto_generate.py [--brand example-brand] --subject "an armored rover" \
      --comfy-output-dir <comfy_output_dir> [--max-iters 4] [--seeds 7,8,9] [--variant turbo]

--comfy-output-dir is required: it both routes renders into the output folder (brand or global) AND
is where the judge graph drops its verdict .txt. Only the local backend exists (no Claude-API path).
"""
import argparse, datetime, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent.expander import TemplatedExpander
from scripts.agent.judge import LocalVLMJudge
from scripts.agent.loop import run_loop
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
    'local' (Qwen2.5-VL judge) is the autonomous path. 'assistant' (multi-judge vision consensus)
    needs the agent's own eyes in the loop, which a bare subprocess doesn't have — so it's offered
    but gated: choose it and the CLI refuses, pointing at the local backend / the assistant recipe."""
    if backend == "assistant":
        return ("the 'assistant' consensus backend judges with the agent's own vision and only runs "
                "with the agent in the loop (see workflows/agent/README.md). For an unattended run "
                "use --backend local (the Qwen2.5-VL judge).")
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
        "schema": 2, "kind": "agent-run", "modality": "image", "mode": "agent",
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
    ap.add_argument("--max-iters", dest="max_iters", type=int, default=4)
    ap.add_argument("--seeds", default=None, help="comma-separated seeds, one per iteration")
    ap.add_argument("--backend", choices=["local", "assistant"], default="local",
                    help="local = autonomous Qwen2.5-VL judge (default); assistant = agent-driven "
                         "vision consensus (optional, requires the agent in the loop)")
    ap.add_argument("--comfy-url", dest="comfy_url", default="http://127.0.0.1:8000")
    ap.add_argument("--comfy-output-dir", dest="comfy_output_dir", required=True,
                    help="ComfyUI output dir: routes renders AND is where the judge drops verdicts")
    ap.add_argument("--variant", choices=["base", "turbo"], default=None,
                    help="Z-Image fidelity (turbo=8-step default, base=25-step)")
    ap.add_argument("--model", default=None, help="image model/family override")
    ap.add_argument("--timeout", type=int, default=900, help="per-render wait (s)")
    args = ap.parse_args()
    backend_err = _backend_error(args.backend)
    if backend_err:
        ap.error(backend_err)

    repo_root = Path(__file__).resolve().parents[2]
    m = _resolve_manifest(repo_root, args.brand)
    client = ComfyClient(args.comfy_url)

    expander = TemplatedExpander()
    judge = LocalVLMJudge(client, repo_root, args.comfy_output_dir)
    generate = _make_generate(args, repo_root, m, client)

    result = run_loop(expander=expander, judge=judge, generate=generate, manifest=m,
                      subject=args.subject, max_iters=args.max_iters,
                      seeds=_parse_seeds(args.seeds))

    _print_summary(result)
    _write_run_sidecar(result, args, repo_root)


if __name__ == "__main__":
    main()
