"""The judge-agnostic generate -> judge -> refine loop.

The generator and judge are injected callables, so the whole loop is unit-testable
with no ComfyUI / model / network dependency. Seeds are deterministic.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass, field
from typing import Optional

from .judge import Verdict
from .rubric import build_rubric


@dataclass
class IterRecord:
    """One pass through the loop: which seed/prompt produced which verdict."""
    iter: int
    seed: int
    prompt: str
    verdict: Verdict


@dataclass
class LoopResult:
    """The outcome: the best candidate seen and the full per-iteration history."""
    best_image: object
    best_verdict: Optional[Verdict]
    passed: bool
    history: list = field(default_factory=list)


def run_loop(*, expander, judge, generate, manifest, subject,
             rubric=None, max_iters=4, seeds=None) -> LoopResult:
    """Iterate render->judge, feeding unmet issues back in, until PASS or exhaustion.

    Returns the passing candidate, or (on exhaustion) the highest-scoring one.
    """
    if rubric is None:
        rubric = build_rubric(manifest, subject)

    prior_issues = None
    best = None  # (verdict, image)
    history = []

    for i in range(max_iters):
        seed = seeds[i] if seeds and i < len(seeds) else 1000 + i
        pos, neg = expander.expand(subject, manifest, prior_issues)
        try:
            img = generate(pos, neg, seed)
            v = judge.judge(img, rubric)
        except Exception as exc:  # render/judge failure: skip, don't abort the run
            img = None
            v = Verdict(passed=False, score=0.0,
                        issues=[f"iteration failed: {exc}"])
            history.append(IterRecord(iter=i, seed=seed, prompt=pos, verdict=v))
            print(f"[agent] iter {i} seed={seed} FAILED: {exc}", file=sys.stderr)
            prior_issues = v.issues
            continue

        history.append(IterRecord(iter=i, seed=seed, prompt=pos, verdict=v))

        print(f"[agent] iter {i} seed={seed} score={v.score} "
              f"{'PASS' if v.passed else 'FAIL'}", file=sys.stderr)

        # Only a real render can win; a None image must never become best.
        if img is not None and (best is None or v.score > best[0].score):
            best = (v, img)

        if v.passed:
            return LoopResult(best_image=img, best_verdict=v, passed=True,
                              history=history)
        prior_issues = v.issues

    if best is None:  # max_iters <= 0, or every iteration failed to render/judge
        last_v = history[-1].verdict if history else None
        return LoopResult(best_image=None, best_verdict=last_v, passed=False,
                          history=history)

    best_v, best_img = best
    return LoopResult(best_image=best_img, best_verdict=best_v, passed=False,
                      history=history)
