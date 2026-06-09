from __future__ import annotations
from pathlib import Path

import pytest
from scripts.agent.judge import Judge, LocalVLMJudge, Verdict, parse_verdict
from scripts.agent.rubric import Rubric


def test_verdict_default_issues_independent():
    a, b = Verdict(passed=True, score=1.0), Verdict(passed=False, score=0.0)
    a.issues.append("x")
    assert b.issues == []


def test_judge_abc_cannot_instantiate():
    with pytest.raises(TypeError):
        Judge()  # abstract


def test_parse_pass_with_score_and_issue():
    text = (
        "1. depicts rover: MET\n"
        "2. brand palette: not-met: brand palette is washed out and not dominant\n"
        "Overall: PASS\n"
        "score 0.82\n"
    )
    v = parse_verdict(text)
    assert v.passed is True
    assert v.score == 0.82
    assert any("palette" in i.lower() for i in v.issues)


def test_parse_fail():
    text = "Overall: FAIL\nscore: 0.4\n1. subject: NOT-MET - the rover is missing entirely"
    v = parse_verdict(text)
    assert v.passed is False
    assert v.score == 0.4
    assert v.issues  # the NOT-MET criterion line is collected


def test_parse_collects_fix_directive_for_the_expander():
    # the judge's structured 'FIX: add ...; avoid ...' correction must reach the expander via issues
    text = ("Overall: FAIL\nscore: 0.5\n"
            "1. NOT-MET - looks like a toy. FIX: add rugged tactical armor; avoid toy, glossy plastic\n")
    v = parse_verdict(text)
    assert any("fix:" in i.lower() and "rugged tactical armor" in i.lower() for i in v.issues)


def test_parse_garbage_does_not_raise_and_fails():
    for junk in ("", "   ", "no verdict here at all", None):
        v = parse_verdict(junk)
        assert v.passed is False
        assert v.score == 0.0


def test_parse_score_clamped_and_default():
    assert parse_verdict("PASS score: 1.7").score == 1.0
    assert parse_verdict("PASS score: -0.3").score == 0.0
    # no score token -> default 0.0
    assert parse_verdict("Overall: PASS").score == 0.0


def test_pass_not_fooled_by_substring():
    # 'passable' / 'compass' must NOT be read as an overall PASS verdict;
    # with no standalone PASS token and a FAIL present, this is a fail.
    text = "the framing is passable but the compass is wrong\nOverall: FAIL\nscore 0.5"
    v = parse_verdict(text)
    assert v.passed is False


def test_pass_requires_standalone_token():
    # a bare 'passable' with no real verdict token -> not passed
    v = parse_verdict("this is passable quality, score 0.9")
    assert v.passed is False


def test_pass_not_contaminated_by_fail_in_criterion_reason():
    # The verdict is on its own line (Overall: PASS); a criterion reason that
    # merely contains the word 'fail' must NOT flip the overall to FAIL.
    text = (
        "Overall: PASS\n"
        "score: 0.9\n"
        "1. subject: MET, does not fail to depict the rover\n"
    )
    v = parse_verdict(text)
    assert v.passed is True
    assert v.score == 0.9


def test_real_overall_fail_line_is_fail():
    text = "Overall: FAIL\nscore: 0.4\n1. subject: not-met: rover absent"
    v = parse_verdict(text)
    assert v.passed is False


def test_overall_fail_line_not_collected_as_issue():
    # The 'Overall: FAIL' line must be excluded from issues, but a genuine
    # not-met criterion line must still be collected.
    text = (
        "Overall: FAIL\n"
        "score: 0.4\n"
        "1. palette: not-met: brand palette absent\n"
    )
    v = parse_verdict(text)
    assert not any("overall" in i.lower() for i in v.issues)
    assert any("palette" in i.lower() for i in v.issues)


def test_issues_only_collects_not_met_lines():
    # MET lines that happen to contain 'avoids'/'missing' must NOT be collected as issues;
    # only the genuine NOT-MET line is threaded back to the expander.
    text = (
        "Overall: FAIL\n"
        "1. MET - the image avoids blur\n"
        "2. NOT-MET - the palette is absent\n"
        "3. MET - sharp, missing nothing\n"
        "score: 0.5\n"
    )
    v = parse_verdict(text)
    assert any("palette" in i.lower() for i in v.issues)
    assert not any("avoids blur" in i.lower() for i in v.issues)
    assert not any("missing nothing" in i.lower() for i in v.issues)
    assert len(v.issues) == 1


def test_all_met_pass_has_no_issues():
    text = (
        "Overall: PASS\n"
        "1. MET - subject depicted\n"
        "2. MET - palette dominant\n"
        "score: 0.95\n"
    )
    v = parse_verdict(text)
    assert v.passed is True
    assert v.issues == []


def test_score_fraction_and_percent_normalized():
    assert parse_verdict("Overall: PASS\nScore: 8/10").score == 0.8
    assert parse_verdict("Overall: PASS\nScore: 85%").score == 0.85
    assert parse_verdict("Overall: PASS\nScore: 1/1").score == 1.0
    # bare decimal still works (regression)
    assert parse_verdict("Overall: PASS\nscore: 0.82").score == 0.82
    # no score token -> default 0.0
    assert parse_verdict("Overall: PASS").score == 0.0


# ---- LocalVLMJudge (mocked client; tmp_path stands in for ComfyUI's output dir) ----

REPO_ROOT = Path(__file__).resolve().parents[1]
_RUBRIC = Rubric(subject="an armored rover", criteria=["depicts the rover."])


class FakeClient:
    """Stands in for ComfyClient: records the queued graph and, at wait() time, simulates
    ComfyUI by writing the verdict .txt (and an optional junk .png) the graph would emit."""

    def __init__(self, output_dir, verdict_text, *, write_png=False):
        self.output_dir = Path(output_dir)
        self.verdict_text = verdict_text
        self.write_png = write_png
        self.uploaded = None
        self.queued_wf = None

    def upload_image(self, path):
        self.uploaded = f"uploaded_{Path(path).name}"
        return self.uploaded

    def queue_prompt(self, wf):
        self.queued_wf = wf
        return "pid-123"

    def wait(self, pid, max_wait=None):
        prefix = self.queued_wf["3"]["inputs"]["filename_prefix"]
        vdir = self.output_dir / "agent_verdicts"
        vdir.mkdir(parents=True, exist_ok=True)
        if self.verdict_text is not None:
            (vdir / f"{prefix}_00000.txt").write_text(self.verdict_text, encoding="utf-8")
        if self.write_png:
            (vdir / f"{prefix}_00000.png").write_bytes(b"\x89PNG junk")


def _node(wf, title):
    return next(n for n in wf.values() if n.get("_meta", {}).get("title") == title)


def test_localvlmjudge_pass(tmp_path):
    text = "1. Met - rover present\n\nOverall Verdict:\nPASS\n\nScore: 1/1\n"
    client = FakeClient(tmp_path, text)
    j = LocalVLMJudge(client, REPO_ROOT, tmp_path)
    v = j.judge(tmp_path / "render.png", _RUBRIC)
    assert v == parse_verdict(text)
    assert v.passed is True


def test_localvlmjudge_fail_with_issues(tmp_path):
    text = ("1. not-met: brand palette absent\n"
            "Overall Verdict:\nFAIL\nScore: 0.3\n")
    client = FakeClient(tmp_path, text)
    j = LocalVLMJudge(client, REPO_ROOT, tmp_path)
    v = j.judge(tmp_path / "render.png", _RUBRIC)
    assert v == parse_verdict(text)
    assert v.passed is False
    assert v.issues  # the not-met line is threaded back for refinement


def test_localvlmjudge_fills_graph_by_title(tmp_path):
    client = FakeClient(tmp_path, "Overall: PASS\nscore: 1")
    j = LocalVLMJudge(client, REPO_ROOT, tmp_path)
    j.judge(tmp_path / "render.png", _RUBRIC)
    wf = client.queued_wf
    assert _node(wf, "brand:vlm_image")["inputs"]["image"] == client.uploaded
    assert _node(wf, "brand:vlm")["inputs"]["custom_prompt"] == _RUBRIC.as_prompt()
    # run-unique prefix: verdict_<stem>_<pid>_<n>, so just check the stable prefix.
    fp = _node(wf, "brand:vlm_out")["inputs"]["filename_prefix"]
    assert fp.startswith("verdict_render_")


def test_localvlmjudge_deletes_junk_png(tmp_path):
    client = FakeClient(tmp_path, "Overall: PASS\nscore: 1", write_png=True)
    j = LocalVLMJudge(client, REPO_ROOT, tmp_path)
    j.judge(tmp_path / "render.png", _RUBRIC)
    # the prefix is run-unique now; the junk PNG (whatever its index) must be gone.
    assert not list((tmp_path / "agent_verdicts").glob("verdict_render_*.png"))


def test_localvlmjudge_missing_verdict_degrades_to_fail(tmp_path):
    # verdict_text=None -> wait() writes no .txt; judge must FAIL, not raise.
    # _read_delay=0 keeps the retry loop instant (no ~2s sleep).
    client = FakeClient(tmp_path, None)
    j = LocalVLMJudge(client, REPO_ROOT, tmp_path, timeout=1, _read_delay=0)
    v = j.judge(tmp_path / "render.png", _RUBRIC)
    assert v.passed is False
    assert v.score == 0.0
    assert any("no verdict file" in i.lower() for i in v.issues)
