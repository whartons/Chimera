import pytest
from scripts.agent.judge import (
    CallableJudge, ConsensusJudge, Verdict, combine_verdicts, consensus_verdict,
)


class FakeJudge:
    def __init__(self, verdict):
        self._v = verdict
    def judge(self, image_path, rubric):
        return self._v


def _v(passed, score, issues=()):
    return Verdict(passed=passed, score=score, issues=list(issues))


def test_consensus_majority_pass_and_mean_score():
    cj = ConsensusJudge([_FJ(True, 0.9), _FJ(True, 0.8), _FJ(False, 0.4, ["x not met"])])
    out = cj.judge("img.png", None)
    assert out.passed is True                              # 2/3 pass >= threshold 2
    assert out.score == 0.7                                # mean of sub-scores, rounded (exact, not approx)
    assert out.issues == ["x not met"]                     # surfaced from the dissenter


def test_consensus_minority_fails_unions_issues():
    cj = ConsensusJudge([_FJ(True, 0.9), _FJ(False, 0.3, ["a not met"]), _FJ(False, 0.2, ["b not met"])])
    out = cj.judge("i", None)
    assert out.passed is False                             # only 1/3 pass
    assert out.issues == ["a not met", "b not met"]        # order-preserving union


def test_consensus_dedups_shared_issues():
    cj = ConsensusJudge([_FJ(False, 0.1, ["dup", "x not met"]), _FJ(False, 0.2, ["dup", "y not met"])])
    assert cj.judge("i", None).issues == ["dup", "x not met", "y not met"]   # 'dup' once


def test_consensus_n2_requires_unanimous():
    assert ConsensusJudge([_FJ(True, 0.9), _FJ(True, 0.9)]).judge("i", None).passed is True
    assert ConsensusJudge([_FJ(True, 0.9), _FJ(False, 0.4)]).judge("i", None).passed is False


def test_consensus_custom_threshold():
    cj = ConsensusJudge([_FJ(True, 0.9), _FJ(False, 0.1), _FJ(False, 0.1)], pass_threshold=1)
    assert cj.judge("i", None).passed is True              # threshold=1: any pass -> pass


def test_consensus_flaky_judge_counts_as_fail_not_crash():
    class Boom:
        def judge(self, image_path, rubric):
            raise RuntimeError("kaboom")
    out = ConsensusJudge([_FJ(True, 0.9), _FJ(True, 0.9), Boom()]).judge("i", None)
    assert out.passed is True                              # 2/3 pass; boom counts as a fail
    assert any("judge error" in i for i in out.issues)     # the error is surfaced, not swallowed


def test_consensus_empty_raises():
    with pytest.raises(ValueError):
        ConsensusJudge([])


def _FJ(passed, score, issues=()):
    return FakeJudge(_v(passed, score, issues))


# ---- consensus_verdict: combine the assistant's M independent free-text vision passes ----

def test_consensus_verdict_majority_pass_from_texts():
    texts = [
        "Overall: PASS\nscore: 0.9\n1. MET - subject present",
        "Overall: PASS\nscore: 0.8\n1. MET - subject present",
        "Overall: FAIL\nscore: 0.4\n1. NOT-MET - palette washed out",
    ]
    v = consensus_verdict(texts)
    assert v.passed is True                                 # 2/3 PASS >= threshold 2
    assert v.score == 0.7                                   # mean of the parsed scores, rounded (exact)
    assert any("palette" in i.lower() for i in v.issues)    # the dissenter's miss is surfaced


def test_consensus_verdict_majority_fail_unions_issues():
    texts = [
        "Overall: PASS\nscore: 0.9",
        "Overall: FAIL\nscore: 0.3\n1. NOT-MET - a not met",
        "Overall: FAIL\nscore: 0.2\n1. NOT-MET - b not met",
    ]
    v = consensus_verdict(texts)
    assert v.passed is False                                # only 1/3 PASS
    assert any("a not met" in i for i in v.issues) and any("b not met" in i for i in v.issues)


def test_consensus_verdict_empty_raises():
    with pytest.raises(ValueError):
        consensus_verdict([])


def test_consensus_verdict_honors_threshold():
    texts = ["Overall: PASS\nscore: 0.9", "Overall: FAIL\nscore: 0.1", "Overall: FAIL\nscore: 0.1"]
    assert consensus_verdict(texts, pass_threshold=1).passed is True   # threshold=1: any pass -> pass


def test_combine_verdicts_empty_raises():
    with pytest.raises(ValueError):
        combine_verdicts([])


def test_combine_verdicts_direct_threshold_union_and_mean():
    # exercise the shared primitive in isolation (not via a wrapper): its own pass_threshold kwarg,
    # the order-preserving deduped issue union, and the mean score.
    out = combine_verdicts([_v(True, 0.9, ["dup", "a"]), _v(False, 0.3, ["dup", "b"])],
                           pass_threshold=1)
    assert out.passed is True                  # threshold=1 honored on the function itself
    assert out.issues == ["dup", "a", "b"]     # 'dup' once, order preserved
    assert out.score == 0.6                    # mean of 0.9 and 0.3


def test_combine_verdicts_rounds_mean_to_4dp():
    # pins the documented round(score, 4): a non-terminating mean must land on exactly 4 places,
    # so dropping/loosening the rounding is caught (== not a tolerance).
    out = combine_verdicts([_v(False, 0.1), _v(False, 0.2), _v(False, 0.2)])
    assert out.score == 0.1667                 # 0.5/3 = 0.16666... -> 0.1667


# ---- CallableJudge: adapt an assistant vision pass (a callable) into the Judge seam ----

def test_callable_judge_parses_text_result():
    j = CallableJudge(lambda img, rubric: "Overall: PASS\nscore: 0.95")
    v = j.judge("img.png", None)
    assert v.passed is True and v.score == 0.95


def test_callable_judge_passes_through_verdict_result():
    pre = Verdict(passed=False, score=0.2, issues=["x"])
    j = CallableJudge(lambda img, rubric: pre)
    assert j.judge("i", None) is pre                        # already a Verdict -> returned as-is


def test_callable_judge_composes_into_consensus_panel():
    # the assistant backend = ConsensusJudge over N CallableJudge vision passes (the agent's own eyes)
    panel = ConsensusJudge([
        CallableJudge(lambda img, r: "Overall: PASS\nscore: 0.9"),
        CallableJudge(lambda img, r: "Overall: PASS\nscore: 0.8"),
        CallableJudge(lambda img, r: "Overall: FAIL\nscore: 0.4\nNOT-MET - palette off"),
    ])
    out = panel.judge("img.png", None)
    assert out.passed is True                               # 2/3 vision passes agree
    assert any("palette" in i.lower() for i in out.issues)
