"""The judge-agnostic generate -> judge -> refine loop.

The generator and judge are injected callables, so the whole loop is unit-testable
with no ComfyUI / model / network dependency. Seeds are deterministic.
"""
from __future__ import annotations
import dataclasses
import sys
from dataclasses import dataclass, field

from .expander import brand_guard, correct_subject, parse_fixes
from .judge import Verdict
from .rubric import Rubric, build_rubric


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
    best_verdict: Verdict | None
    passed: bool
    history: list = field(default_factory=list)
    subject: str = ""   # the subject the run ended on (branded runs may drop flagged styling from it)


def _brand_corrected(subject, rubric, manifest, issues):
    """Branded runs only: drop the subject styling the judge flagged as off-brand from the subject AND the
    rubric. Otherwise a subject like 'a candy-red toy rover' under a gunmetal brand keeps the judge
    demanding the candy colors it also forbids, and a small judge never converges (2026-10)."""
    if not (manifest.style or manifest.palette or manifest.negative):
        return subject, rubric
    _, avoid = brand_guard(*parse_fixes(issues), manifest)
    fixed = correct_subject(subject, avoid) if avoid else subject
    if fixed == subject:
        return subject, rubric
    print(f"[agent] subject corrected for the brand: {fixed!r}", file=sys.stderr)
    if isinstance(rubric, Rubric):
        rubric = dataclasses.replace(rubric, subject=fixed,
                                     criteria=[c.replace(subject, fixed) for c in rubric.criteria])
    return fixed, rubric


class SeedNames:
    """Output names for one run's renders: the seed, then <seed>_2, <seed>_3, ... when the run repeats a seed
    (`--seeds 7,7,7` re-renders one seed with corrected prompts). Each pass needs its own file: under one
    name a later pass replaced the reported winner's file (2026-10 review)."""

    def __init__(self):
        self._uses = {}

    def __call__(self, seed):
        n = self._uses[seed] = self._uses.get(seed, 0) + 1
        return seed if n == 1 else f"{seed}_{n}"


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
            # keep the last JUDGE issues: threading the error text in put "Fix: iteration failed: prompt did
            # not finish in 900s" into the next image prompt. (The CAD generator keeps its own last error.)
            continue

        history.append(IterRecord(iter=i, seed=seed, prompt=pos, verdict=v))

        print(f"[agent] iter {i} seed={seed} score={v.score} "
              f"{'PASS' if v.passed else 'FAIL'}", file=sys.stderr)

        # Only a real render can win; a None image must never become best.
        if img is not None and (best is None or v.score > best[0].score):
            best = (v, img)

        if v.passed:
            return LoopResult(best_image=img, best_verdict=v, passed=True,
                              history=history, subject=subject)
        prior_issues = v.issues
        subject, rubric = _brand_corrected(subject, rubric, manifest, v.issues)

    if best is None:  # max_iters <= 0, or every iteration failed to render/judge
        last_v = history[-1].verdict if history else None
        return LoopResult(best_image=None, best_verdict=last_v, passed=False,
                          history=history, subject=subject)

    best_v, best_img = best
    return LoopResult(best_image=best_img, best_verdict=best_v, passed=False,
                      history=history, subject=subject)
