import json
from scripts.agent.judge import GeometryAwareJudge, Verdict, Judge


class _Stub(Judge):
    def __init__(self, v):
        self.v = v

    def judge(self, image_path, rubric):
        return self.v


_CLEAN = {"non_manifold_edges": 0, "open_edges": 0, "loose_parts": 1,
          "tri_count": 1000, "bounds_ok": True}


def _sheet_with_checks(tmp_path, checks):
    sheet = tmp_path / "agent_7.png"
    sheet.write_text("x")
    (tmp_path / "agent_7.checks.json").write_text(json.dumps(checks))
    return sheet


def test_clean_checks_pass_through(tmp_path):
    sheet = _sheet_with_checks(tmp_path, _CLEAN)
    j = GeometryAwareJudge(_Stub(Verdict(True, 0.9, [])))
    v = j.judge(str(sheet), rubric=None)
    assert v.passed and v.score == 0.9 and v.issues == []


def test_open_edges_force_fail_and_add_issue(tmp_path):
    sheet = _sheet_with_checks(tmp_path, {**_CLEAN, "open_edges": 12})
    j = GeometryAwareJudge(_Stub(Verdict(True, 0.95, ["MET - looks great"])))
    v = j.judge(str(sheet), rubric=None)
    assert v.passed is False
    assert any("watertight" in i for i in v.issues)
    assert "MET - looks great" in v.issues  # inner issues preserved, structural unioned in


def test_multiple_defects_all_unioned(tmp_path):
    sheet = _sheet_with_checks(tmp_path, {**_CLEAN, "non_manifold_edges": 5, "loose_parts": 3})
    j = GeometryAwareJudge(_Stub(Verdict(True, 0.6, ["MET - ok"])))
    v = j.judge(str(sheet), rubric=None)
    assert v.passed is False
    assert any("not manifold" in i for i in v.issues)
    assert any("disconnected parts" in i for i in v.issues)
    assert "MET - ok" in v.issues
    assert len(v.issues) == len(set(v.issues))  # no duplicates


def test_no_checks_file_is_passthrough(tmp_path):
    sheet = tmp_path / "agent_7.png"
    sheet.write_text("x")
    j = GeometryAwareJudge(_Stub(Verdict(True, 0.8, ["only this"])))
    v = j.judge(str(sheet), rubric=None)
    assert v.passed and v.issues == ["only this"]


def test_corrupt_checks_file_is_passthrough(tmp_path):
    sheet = tmp_path / "agent_7.png"
    sheet.write_text("x")
    (tmp_path / "agent_7.checks.json").write_text("{not json")
    j = GeometryAwareJudge(_Stub(Verdict(True, 0.7, [])))
    v = j.judge(str(sheet), rubric=None)
    assert v.passed
