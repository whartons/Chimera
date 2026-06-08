from __future__ import annotations
from scripts.brandkit.manifest import BrandManifest
from scripts.agent.judge import Verdict
from scripts.agent.loop import run_loop, LoopResult


def _m() -> BrandManifest:
    return BrandManifest(name="ACME", style="rugged tactical",
                         palette=["#1c1f22"], negative="blurry")


class RecordingExpander:
    """Records each expand() call and returns a prompt embedding the inputs."""
    def __init__(self):
        self.calls = []

    def expand(self, subject, manifest, prior_issues=None):
        self.calls.append({"subject": subject, "prior_issues": prior_issues})
        suffix = "" if not prior_issues else " | fix:" + ",".join(prior_issues)
        return (f"pos:{subject}{suffix}", "neg")


class RecordingGenerate:
    """Records (pos, neg, seed) and returns a deterministic per-call path."""
    def __init__(self):
        self.calls = []

    def __call__(self, pos, neg, seed):
        self.calls.append((pos, neg, seed))
        return f"/img/{seed}.png"


class PassOnNthJudge:
    """Fails the first n-1 candidates with issues, passes the nth."""
    def __init__(self, pass_on):
        self.pass_on = pass_on
        self.n = 0

    def judge(self, image_path, rubric):
        self.n += 1
        if self.n >= self.pass_on:
            return Verdict(passed=True, score=0.9, issues=[])
        return Verdict(passed=False, score=0.1 * self.n, issues=[f"issue{self.n}"])


class IncreasingFailJudge:
    """Always fails, with a strictly increasing score per call."""
    def __init__(self):
        self.n = 0

    def judge(self, image_path, rubric):
        self.n += 1
        return Verdict(passed=False, score=0.1 * self.n, issues=[f"f{self.n}"])


def test_loop_stops_on_pass_and_threads_prior_issues():
    exp, gen, judge = RecordingExpander(), RecordingGenerate(), PassOnNthJudge(pass_on=3)
    res = run_loop(expander=exp, judge=judge, generate=gen,
                   manifest=_m(), subject="rover", max_iters=4)
    assert isinstance(res, LoopResult)
    assert res.passed is True
    assert res.best_image == "/img/1002.png"          # 3rd candidate (seed 1000+2)
    assert len(res.history) == 3                       # stopped at iter 2 (0-indexed)
    # first iter has no prior issues; iters 1 and 2 received the previous verdict's issues
    assert exp.calls[0]["prior_issues"] is None
    assert exp.calls[1]["prior_issues"] == ["issue1"]
    assert exp.calls[2]["prior_issues"] == ["issue2"]
    # generate received the expanded prompt + derived seed
    assert gen.calls[0] == ("pos:rover", "neg", 1000)
    assert gen.calls[2][0] == "pos:rover | fix:issue2"
    assert gen.calls[2][2] == 1002


def test_loop_returns_best_on_exhaustion():
    exp, gen, judge = RecordingExpander(), RecordingGenerate(), IncreasingFailJudge()
    res = run_loop(expander=exp, judge=judge, generate=gen,
                   manifest=_m(), subject="rover", max_iters=4)
    assert res.passed is False
    assert len(res.history) == 4
    # highest score is the last (4th) iteration: seed 1003, score 0.4
    assert res.best_image == "/img/1003.png"
    assert res.best_verdict.score == 0.4


def test_loop_uses_explicit_seeds_when_given():
    exp, gen, judge = RecordingExpander(), RecordingGenerate(), IncreasingFailJudge()
    run_loop(expander=exp, judge=judge, generate=gen, manifest=_m(),
             subject="rover", max_iters=3, seeds=[7, 8])
    # first two seeds from the list, third derived (1000+2)
    assert [c[2] for c in gen.calls] == [7, 8, 1002]


def test_loop_respects_provided_rubric_object():
    exp, gen = RecordingExpander(), RecordingGenerate()
    seen = {}

    class CapturingJudge:
        def judge(self, image_path, rubric):
            seen["rubric"] = rubric
            return Verdict(passed=True, score=1.0, issues=[])

    sentinel = object()
    res = run_loop(expander=exp, judge=CapturingJudge(), generate=gen,
                   manifest=_m(), subject="rover", rubric=sentinel, max_iters=2)
    assert seen["rubric"] is sentinel
    assert res.passed is True


def test_loop_max_iters_zero_returns_cleanly():
    exp, gen, judge = RecordingExpander(), RecordingGenerate(), IncreasingFailJudge()
    res = run_loop(expander=exp, judge=judge, generate=gen,
                   manifest=_m(), subject="rover", max_iters=0)
    assert isinstance(res, LoopResult)
    assert res.passed is False
    assert res.best_image is None
    assert res.best_verdict is None
    assert res.history == []
    assert gen.calls == []  # nothing generated


class RaiseThenSucceedGenerate:
    """Raises on the first call, returns a deterministic path thereafter."""
    def __init__(self):
        self.calls = []

    def __call__(self, pos, neg, seed):
        self.calls.append((pos, neg, seed))
        if len(self.calls) == 1:
            raise RuntimeError("comfy boom")
        return f"/img/{seed}.png"


class AlwaysRaiseGenerate:
    """Every call raises — simulates a persistently broken render path."""
    def __init__(self):
        self.calls = []

    def __call__(self, pos, neg, seed):
        self.calls.append((pos, neg, seed))
        raise RuntimeError("comfy boom")


def test_loop_survives_failed_iteration_and_returns_later_success():
    exp, gen = RecordingExpander(), RaiseThenSucceedGenerate()
    # judge passes whatever it sees; it is only reached on the (successful) 2nd iter
    judge = PassOnNthJudge(pass_on=1)
    res = run_loop(expander=exp, judge=judge, generate=gen,
                   manifest=_m(), subject="rover", max_iters=4)
    assert res.passed is True
    # the failed 1st iter (seed 1000) must not win; the 2nd (seed 1001) does
    assert res.best_image == "/img/1001.png"
    # both iterations are recorded; the first is the failure
    assert len(res.history) == 2
    assert res.history[0].verdict.passed is False
    assert res.history[0].verdict.score == 0.0
    assert "iteration failed" in res.history[0].verdict.issues[0]
    assert res.history[1].verdict.passed is True
    # the failure's issues are threaded into the next expand() call
    assert exp.calls[1]["prior_issues"] == res.history[0].verdict.issues


def test_loop_all_iterations_fail_returns_without_raising():
    exp, gen, judge = RecordingExpander(), AlwaysRaiseGenerate(), PassOnNthJudge(pass_on=1)
    res = run_loop(expander=exp, judge=judge, generate=gen,
                   manifest=_m(), subject="rover", max_iters=3)
    assert isinstance(res, LoopResult)
    assert res.passed is False
    assert res.best_image is None
    assert len(res.history) == 3                       # every iter recorded as failed
    assert all(r.verdict.passed is False for r in res.history)
    assert all(r.verdict.score == 0.0 for r in res.history)
    # caller still gets a verdict to report (the last failure), not a bare None
    assert res.best_verdict is res.history[-1].verdict


def test_loop_history_records_iter_seed_prompt_verdict():
    exp, gen, judge = RecordingExpander(), RecordingGenerate(), PassOnNthJudge(pass_on=2)
    res = run_loop(expander=exp, judge=judge, generate=gen,
                   manifest=_m(), subject="rover", max_iters=4)
    h0 = res.history[0]
    # history entries expose the per-iteration record (dict or attr access)
    get = (lambda r, k: r[k]) if isinstance(h0, dict) else getattr
    assert get(h0, "iter") == 0
    assert get(h0, "seed") == 1000
    assert get(h0, "prompt") == "pos:rover"
    assert get(h0, "verdict").passed is False
