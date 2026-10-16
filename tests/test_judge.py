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


def test_parse_a_pass_contradicted_by_a_not_met_criterion_fails():
    # PASS only if every criterion is MET (the rubric's own rule): the not-met palette wins over the
    # self-contradicting "Overall: PASS", while the score and the issue still come through
    text = (
        "1. depicts rover: MET\n"
        "2. brand palette: not-met: brand palette is washed out and not dominant\n"
        "Overall: PASS\n"
        "score 0.82\n"
    )
    v = parse_verdict(text)
    assert v.passed is False
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


def test_parse_verdict_final_overall_line_beats_criterion_mention():
    # a criterion whose reason says 'overall ... passed' must not hijack the verdict from the
    # real trailing 'Overall: FAIL' line the rubric asks for
    v = parse_verdict("1. MET - overall composition passed muster\nOverall: FAIL\nscore: 0.3")
    assert v.passed is False
    assert v.score == 0.3


def test_parse_verdict_keeps_notmet_line_that_mentions_overall():
    # 'overall proportions' is natural VLM phrasing — the NOT-MET/FIX line must still be
    # threaded back to the expander; only the verdict line itself is excluded from issues
    v = parse_verdict("1. NOT-MET - the overall proportions are stretched. "
                      "FIX: add correct proportions; avoid stretched limbs\n"
                      "Overall: FAIL\nscore: 0.4")
    assert any("proportions" in i for i in v.issues)


def test_parse_verdict_score_line_beats_prose_score_mention():
    # 'scored 7 criteria' must not clamp to 1.0 over the real trailing 'score: 0.55' line
    v = parse_verdict("The model scored 7 criteria as MET out of 8.\n"
                      "1. NOT-MET - palette absent\nOverall: FAIL\nscore: 0.55")
    assert v.score == 0.55


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


# --- a criterion marked NOT-MET fails the verdict even when the judge's last line says PASS (2026-10) ----
import pytest as _pytest  # noqa: E402


@_pytest.mark.parametrize("text", [
    "1. NOT-MET: The head is completely absent. FIX: add head\n2. MET: clean render\nOverall: PASS\nscore: 0.0",
    "**1. Not met** - only two robots. FIX: add a third robot\nOVERALL: PASS\nscore: 0.9",
    "- Palette: NOT-MET (warm tones)\nOverall verdict: PASS\nscore: 0.83",
    "| 4 | NOT-MET | the icon sits between the words |\nPASS\nscore: 1.0",
])
def test_a_not_met_criterion_fails_a_pass_verdict(text):
    # the rubric says PASS only if every criterion is MET; a small judge wrote "NOT-MET: the head is
    # completely absent" and then "Overall: PASS", and the loop accepted the headless robot
    from scripts.agent.judge import parse_verdict
    v = parse_verdict(text)
    assert v.passed is False and v.issues


def test_prose_mentioning_unmet_in_a_met_line_still_passes():
    from scripts.agent.judge import parse_verdict
    assert parse_verdict("1. MET: nothing about the subject is unmet\n2. MET - sharp - nothing unmet\n"
                         "Overall: PASS\nscore: 1.0").passed is True



# --- the 2026-10 review: NOT-MET in the forms judges really write, and scores on other scales -------------
@pytest.mark.parametrize("line", [
    "1. Subject — NOT-MET: the head is missing", "1. **Subject** — NOT-MET", "1. Six-wheeled rover: NOT-MET",
    "1. The image clearly depicts: a robot with arms: NOT-MET", "| 1 | Depicts the robot | NOT-MET | no head |",
    "1. ❌ NOT-MET", "1. Palette: NOT_MET - wrong colors", "1. Avoids toy-like: NOT-MET - glossy plastic",
    "2. Palette: the rover is yellow (NOT-MET)", "Summary: 3 MET, 1 NOT-MET",
    "- No text or watermarks: NOT-MET - a logo is visible", "1. Palette: NOT-MET: no brand colors visible"])
def test_a_criterion_marked_not_met_in_any_common_form_fails_the_verdict(line):
    # each of these, followed by 'Overall: PASS', used to pass
    v = parse_verdict(line + "\nOverall: PASS\nscore: 0.9")
    assert not v.passed and v.issues


@pytest.mark.parametrize("text", [
    "1. Subject: MET - nothing is unmet", "- NOT MET: none", "Unmet criteria: none", "No criteria are NOT-MET.",
    "None of the criteria are NOT-MET", "Criteria: 4 MET, 0 NOT-MET",
    "| 1 | Requirements not met by older designs are fixed | MET |",
    "Be strict: mark a criterion NOT-MET unless it is clearly and fully satisfied.",
    "NOT-MET: none (all criteria met)"])
def test_a_line_that_only_mentions_not_met_does_not_fail_a_pass(text):
    assert parse_verdict(text + "\nOverall: PASS\nscore: 0.9").passed


@pytest.mark.parametrize("line, score", [("score: 4 out of 5", 0.8), ("Score: 7", 0.7), ("score - 0.82", 0.82),
                                         ("score: 85", 0.85), ("score: 85%", 0.85), ("score: 1.7", 1.0)])
def test_scores_on_other_scales_and_separators(line, score):
    # 'score: 4 out of 5' and 'Score: 7' read as a perfect 1.0, 'score - 0.82' as 0.0
    assert round(parse_verdict("PASS\n" + line).score, 3) == score



# --- 2026-10 test review: verdict precedence ----------------------------------------------------------
def test_fail_beats_pass_on_the_verdict_line():
    assert not parse_verdict("1. Palette: MET\nOverall: FAIL - it would pass with the brand palette\nscore: 0.6").passed


def test_the_last_overall_line_wins():
    assert not parse_verdict("Overall: PASS\n1. Subject: MET\nRe-checking the palette: grey.\nOverall: FAIL\n"
                             "score: 0.4").passed
    assert not parse_verdict("1. Subject: MET (overall it would PASS)\n2. Palette: MET\nThe overall verdict: FAIL\n"
                             "score: 0.4").passed


def test_without_an_overall_line_the_last_verdict_word_wins():
    assert not parse_verdict("PASS (draft)\n1. Subject: MET\nFAIL\nscore: 0.2").passed


def test_a_verdict_line_that_mentions_not_met_is_neither_a_criterion_nor_an_issue():
    v = parse_verdict("1. Subject: MET\nOverall: PASS - no criterion is NOT-MET\nscore: 1.0")
    assert v.passed and v.issues == []
    v = parse_verdict("1. Subject: MET\n2. Palette: NOT-MET\nOverall: FAIL - 1 NOT-MET\nscore: 0.4")
    assert v.issues == ["2. Palette: NOT-MET"]


def test_the_last_score_wins():
    assert parse_verdict("Score: 0.9 (draft)\nOverall: FAIL\nFinal score: 0.3").score == 0.3
    assert parse_verdict("I first gave score 0.9; on reflection the score is 0.3\nOverall: FAIL").score == 0.3


def test_a_fix_directive_on_its_own_line_reaches_the_expander():
    v = parse_verdict("1. Palette: NOT-MET\nFIX: add brand red; avoid grey\nOverall: FAIL\nscore: 0.2")
    assert "FIX: add brand red; avoid grey" in v.issues


def test_a_crashing_judge_is_a_fail_vote():
    from scripts.agent.judge import ConsensusJudge

    class Boom:
        def judge(self, image_path, rubric):
            raise RuntimeError("kaboom")

    class Fixed:
        def __init__(self, p): self.p = p
        def judge(self, i, r): return Verdict(self.p, 0.9 if self.p else 0.1, [])
    assert ConsensusJudge([Fixed(True), Fixed(False), Boom()]).judge("i", None).passed is False


@pytest.mark.parametrize("line", [
    "No NOT-MET criteria.", "There are no NOT-MET criteria, so the verdict is PASS.", "No unmet criteria.",
    "   - Reason: all six wheels are present; nothing is unmet.", "For any NOT-MET criterion a FIX is given below.",
    "NOT-MET: none (all criteria met)", "Criteria: 4 MET, 0 NOT-MET"])
def test_a_line_that_only_says_nothing_is_unmet_keeps_a_pass(line):
    # these failed correct renders, and went into the next prompt as "Fix: ..." (2026-10 review)
    v = parse_verdict(f"1. Subject - MET\n2. Style - MET\n{line}\n**Overall verdict:** PASS\nscore: 0.9")
    assert v.passed and v.issues == []


@pytest.mark.parametrize("line", [
    "1. Subject: NOT\u2011MET - the head is missing", "1. Subject: NOT\u2013MET", "- Palette: NOT\u2014MET",
    "- Nothing floats free of the hub: NOT-MET", "1. Subject\n   NOT-MET \u2014 the head is missing",
    "Status: NOT-MET", "2. Palette: the rover is yellow (NOT-MET)"])
def test_every_way_of_writing_not_met_fails_the_render(line):
    v = parse_verdict(f"1. Style - MET\n{line}\nOverall: PASS\nscore: 0.9")
    assert not v.passed and v.issues


def test_a_score_on_the_next_line_or_with_a_plural_label_is_read():
    assert parse_verdict("1. MET\nOverall: FAIL\n**Score:**\n0.85").score == 0.85
    assert parse_verdict("PASS\nScores: 0.4").score == 0.4


# --- final review: a status rule tight enough to need a label layout passed broken renders ---------------------
@pytest.mark.parametrize("line", [
    "3. No missing or broken parts - NOT-MET: the left arm is missing",     # the rubric's own negative phrasing
    "3. No obvious artifacts - NOT MET - heavy banding in the sky",
    "1. The image clearly depicts: a knight without a helmet - NOT-MET (he is wearing one)",
    "- ❌ Palette: NOT-MET - the body is yellow",
    "- Palette (NOT-MET): the body is yellow",
    "- Palette: the body is yellow — NOT-MET",
    "| Palette | NOT-MET - yellow body |",
    "| Palette | NOT-MET. |",
    "1 - Palette: NOT MET (yellow body)",
    "* Palette → NOT-MET",
    "However, the palette criterion is NOT met: the body is yellow.",
    "2. Palette - Partially MET: only some red",
    "- Palette: **NOT** MET",
    "- Palette: not fully met",
])
def test_a_criterion_marked_not_met_fails_the_render_whatever_the_layout(line):
    v = parse_verdict(f"1. Subject - MET\n{line}\nOverall: PASS\nscore: 0.8")
    assert not v.passed and v.issues


@pytest.mark.parametrize("line", ["Criteria met: 3/3 (0/3 NOT-MET)", "Met: 4  Not met: 0", "0/3 NOT-MET",
                                  "Summary: 3 MET, 0 NOT-MET. No criteria are unmet."])
def test_a_zero_count_keeps_a_pass(line):
    v = parse_verdict(f"1. Subject - MET\n2. Palette - MET\n{line}\nOverall: PASS\nscore: 0.9")
    assert v.passed and v.issues == []


def test_a_score_scale_named_before_the_value_is_used():
    for text, want in (("Score (0-1): 0.82", 0.82), ("Score (out of 5): 4", 0.8), ("score (0-10): 8", 0.8)):
        assert round(parse_verdict(f"Overall: PASS\n{text}").score, 3) == want, text


# --- third parser review: a criterion is never the verdict line, and its own status always counts (2026-10) ----
@pytest.mark.parametrize("text, issue", [
    # the 27B writes a bare FAIL: this criterion was taken as the verdict line, left out of the criterion check,
    # and the judge's FAIL came back as a PASS with no issues
    ("1. MET: The image clearly depicts an exploration rover.\n2. NOT-MET: The overall look would not pass as "
     "photoreal. FIX: add photoreal textures; avoid toy-like finish\n\nFAIL\nscore: 0.6",
     "2. NOT-MET: The overall look would not pass as photoreal. FIX: add photoreal textures; avoid toy-like finish"),
    ("Verdict: FAIL\n\n1. MET: The rover is clear.\n2. NOT-MET: palette would not pass review\nscore: 0.6",
     "2. NOT-MET: palette would not pass review"),
    ("1. MET: a clear rover\n- Overall quality: NOT-MET - heavy banding, it would not pass a print check\nPASS\n"
     "score: 0.6", "- Overall quality: NOT-MET - heavy banding, it would not pass a print check"),
])
def test_a_criterion_that_says_pass_or_overall_is_never_the_verdict(text, issue):
    v = parse_verdict(text)
    assert not v.passed and v.issues == [issue]


def test_a_verdict_label_after_a_summary_still_makes_the_verdict_line():
    v = parse_verdict("1. Subject - MET\nNOT-MET: none. Overall: PASS\nscore: 0.9")
    assert v.passed and v.issues == []


@pytest.mark.parametrize("line", [
    "2. NOT-MET: none (the top face is flat and has no holes)", "2. NOT-MET: N/A (the model is a robot, not a dragon)",
    "2. Five hexagonal holes - NOT-MET: 0 (the top face is flat)", "2. NOT-MET: nothing (the head is missing)",
    "2. NOT-MET unless the yellow trim counts as on-palette", "2. Hex holes - NOT-MET: 0, expected five",
    "2. Holes drilled: 0/5 NOT-MET"])
def test_a_numbered_criterion_marked_not_met_is_never_a_summary(line):
    # the summary escapes ('NOT-MET: none', 'Not met: 0', '0/5 NOT-MET', 'unless') passed these renders; the 4B
    # judge wrote PASS over a NOT-MET criterion in 14 of 68 replies, so that line can be the only signal
    v = parse_verdict(f"1. Subject - MET\n{line}\nPASS\nscore: 0.5")
    assert not v.passed and v.issues == [line]


@pytest.mark.parametrize("status", [
    "Mostly MET", "Largely met", "Nearly met", "Almost MET", "Somewhat met", "Half met", "Semi-met", "Barely met",
    "Hardly met", "Scarcely met", "Marginally met", "Not quite met", "Not yet met", "not adequately met",
    "MET (partially)", "MET (partly)", "MET (mostly)", "MET (largely)", "MET (barely)", "Partially-met",
    "PARTIALLY_MET", "Partly met",
    "NOT－MET", "NOT﹣MET", "NOTMET"])
def test_a_qualified_met_is_not_met(status):
    # the rubric passes only what is clearly and fully satisfied; each of these passed a render
    v = parse_verdict(f"1. Subject - MET\n2. Palette - {status}: yellow panels\nOverall: PASS\nscore: 0.8")
    assert not v.passed and v.issues == [f"2. Palette - {status}: yellow panels"]


@pytest.mark.parametrize("status", ["Fully met", "MET (fully)", "MET (partially occluded, but complete)",
                                    "not only met but exceeded", "not just met", "Notably met", "Clearly MET"])
def test_an_emphatic_or_qualified_reason_met_stays_met(status):
    v = parse_verdict(f"1. Subject - MET\n2. Palette - {status}\nOverall: PASS\nscore: 0.9")
    assert v.passed and v.issues == []


def test_the_rubric_instructions_echoed_back_are_ignored():
    # a judge that repeats the prompt: its 'FIX: add <comma-separated visual elements to include>' reached the
    # next prompt as a term to add, and its 'PASS only if EVERY criterion ..., otherwise FAIL' became the verdict
    prompt = Rubric(subject="an armored rover", criteria=["depicts the rover.", "is sharp."]).as_prompt()
    v = parse_verdict(f"{prompt}\n1. MET: a clear rover\n2. MET: sharp\nPASS\nscore: 0.9")
    assert v.passed and v.issues == [] and v.score == 0.9
    assert parse_verdict(f"{prompt}\n1. MET: a clear rover\n2. MET: sharp\nPASS").score == 0.0   # not its 'e.g. 0.82'


@pytest.mark.parametrize("verdict", ["Overall verdict: Does not pass.", "Overall: not a pass", "Verdict: cannot pass",
                                     "Overall: doesn't pass", "Overall: never passed"])
def test_a_negated_pass_is_a_fail(verdict):
    assert not parse_verdict(f"1. Subject - MET\n2. Palette - MET\n{verdict}\nscore: 0.6").passed


@pytest.mark.parametrize("verdict", ["Overall: PASS - criterion 2 NOT-MET is minor",
                                     "Overall: PASS (criterion 3 partially met)",
                                     "Overall: PASS, but 1 criterion unmet"])
def test_a_pass_that_admits_an_unmet_criterion_fails(verdict):
    v = parse_verdict(f"1. Subject - MET\n2. Palette - MET\n{verdict}\nscore: 0.8")
    assert not v.passed and v.issues == [verdict]


@pytest.mark.parametrize("verdict", ["Overall: PASS (all criteria MET)", "Overall: PASS. Criteria NOT-MET: none.",
                                     "Overall: PASS (no unmet criteria)", "PASS: 2/2 MET, 0 NOT-MET"])
def test_a_pass_that_says_nothing_is_unmet_keeps_its_pass(verdict):
    v = parse_verdict(f"1. Subject - MET\n2. Palette - MET\n{verdict}\nscore: 0.8")
    assert v.passed and v.issues == []


def test_a_bracketed_scale_and_a_decimal_comma_are_read():
    for text, want in (("Score [0-1]: 0.7", 0.7), ("score: 0,85", 0.85), ("Score (1-5): 4", 0.8),
                       ("Score [0-5]: 4", 0.8), ("Score (0 to 5): 4", 0.8), ("**Score:**\n0,6", 0.6)):
        assert round(parse_verdict(f"Overall: PASS\n{text}").score, 3) == want, text


# --- pins: each rule below survived its own deletion in the 2026-10 mutation run --------------------------------
def _fails(line):
    v = parse_verdict(f"1. Subject - MET\n{line}\nOverall: PASS\nscore: 0.8")
    return not v.passed and bool(v.issues)


def _keeps(line):
    v = parse_verdict(f"1. Subject - MET\n2. Style - MET\n{line}\nOverall: PASS\nscore: 0.8")
    return v.passed and v.issues == []


@pytest.mark.parametrize("line", [
    "Met: 3  Not met: 1", "3. No missing or broken parts NOT-MET: the left arm is missing",
    "**3.** No missing parts NOT-MET", "3) No missing parts NOT-MET", "3: No missing parts NOT-MET",
    "Criterion 3: No missing parts NOT-MET", "| 3 | No missing parts NOT-MET", "- 3. No missing parts NOT-MET",
    "### 3. No missing parts NOT-MET", "- No missing parts - NOT-MET",
    "- The knight has no helmet and his visor and plume are missing so NOT-MET", "- Palette: partly met",
    "- Palette: not entirely met", "2. Finish: brushed metal, not chrome — NOT-MET",
    "There are no fewer than 2 criteria NOT-MET"])
def test_pinned_rules_fail_a_render(line):
    assert _fails(line)


@pytest.mark.parametrize("line", [
    "Zero NOT-MET criteria.", "Every criterion holds, without a single NOT-MET.",
    "If a criterion were NOT-MET, a FIX would follow.", "| Requirements not met by older designs are fixed | ✅ MET |",
    "| Requirements not met by older designs are fixed | **MET** |", "NOT-MET: N/A", "NOT-MET: 0.", "NOT-MET: zero",
    "Unmet: nothing.", "Summary: 0 criteria NOT-MET", "NOT-MET = 0, MET = 4", "Not met: 0, met: 4"])
def test_pinned_rules_keep_a_pass(line):
    assert _keeps(line)


@pytest.mark.parametrize("text, passed", [
    ("1. Subject: MET\nOverall: FAIL\nNote: with a sharper horizon it would pass overall.\nscore: 0.4", False),
    ("1. Subject: MET\nThe overall verdict: FAIL\nNote: it would pass with a red body.\nscore: 0.4", False),
    ("1. Subject: MET\n**Overall:** FAIL\nNote: overall it would pass with a red body.\nscore: 0.4", False),
    ("1. Subject: MET\nOverall: PASSED\nscore: 0.9", True),
    ("PASS (draft)\n1. Subject: MET\nOverall: FAILED\nscore: 0.3", False),
    ("1. Subject: MET\nOverall: PASS - no criterion fails\nscore: 0.9", True),
    ("1. Subject: MET\nOverall: PASS\nScore: 1/0", True)])
def test_pinned_verdict_rules(text, passed):
    assert parse_verdict(text).passed is passed


def test_pinned_score_and_fix_rules():
    v = parse_verdict("1. Palette: NOT-MET\nFix - add red; avoid grey\nOverall: FAIL\nscore: 0.2")
    assert "Fix - add red; avoid grey" in v.issues
    assert parse_verdict("Overall: PASS\nScore (0–5): 4").score == 0.8
    assert parse_verdict("Overall: PASS\nScore: 5%").score == 0.05
    assert parse_verdict("Overall: PASS\nScore: 10%").score == 0.1
    assert parse_verdict("Overall: PASS\nScores: 0.4\nNote: a score of 0.9 would need studio light.").score == 0.4
