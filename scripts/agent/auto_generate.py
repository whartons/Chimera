#!/usr/bin/env python3
"""Headless self-correction loop (local backend): render -> VLM-judge -> refine, until PASS.

Wires the model-free agent core (expander + run_loop) to the real ComfyUI image filler and a
local Qwen2.5-VL judge (LocalVLMJudge over the agent-vlm-judge.json graph). Each iteration the
expander folds the previous verdict's unmet-criterion issues back into the prompt, so renders
converge on the brand rubric. The winning image is routed into brands/<brand>/outputs/ with a
sidecar recording the run.

  python scripts/agent/auto_generate.py --brand example-brand --subject "an armored rover" \
      --comfy-output-dir <comfy_output_dir> [--max-iters 4] [--seeds 7,8,9] [--variant turbo]

--comfy-output-dir is required: it both routes renders into the brand folder AND is where the
judge graph drops its verdict .txt. Only the local backend exists (no Claude-API / batch path).
"""
import argparse, datetime, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.agent.expander import TemplatedExpander
from scripts.agent.judge import LocalVLMJudge
from scripts.agent.loop import run_loop
from scripts.brandkit import workflow as image_filler
from scripts.brandkit.comfy import ComfyClient
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.outputs import select_output, route_output, write_sidecar
from scripts.generate import git_provenance


def _parse_seeds(raw):
    """'7,8,9' -> [7, 8, 9]; None/'' -> None (loop falls back to its deterministic seeds)."""
    if not raw:
        return None
    return [int(s) for s in raw.split(",") if s.strip()]


def _make_generate(args, repo_root, manifest, client):
    """Build the loop's generate(pos, neg, seed) -> routed-image-path closure. Each call builds
    the txt2img graph, queues it, waits, and routes the result into the brand folder (mode label
    'agent' so per-iteration renders are distinguishable)."""
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
    ap.add_argument("--brand", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--max-iters", dest="max_iters", type=int, default=4)
    ap.add_argument("--seeds", default=None, help="comma-separated seeds, one per iteration")
    ap.add_argument("--backend", choices=["local"], default="local")
    ap.add_argument("--comfy-url", dest="comfy_url", default="http://127.0.0.1:8000")
    ap.add_argument("--comfy-output-dir", dest="comfy_output_dir", required=True,
                    help="ComfyUI output dir: routes renders AND is where the judge drops verdicts")
    ap.add_argument("--variant", choices=["base", "turbo"], default=None,
                    help="Z-Image fidelity (turbo=8-step default, base=25-step)")
    ap.add_argument("--model", default=None, help="image model/family override")
    ap.add_argument("--timeout", type=int, default=900, help="per-render wait (s)")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    m = load_manifest(repo_root / "brands" / args.brand / "brand.yaml")
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
