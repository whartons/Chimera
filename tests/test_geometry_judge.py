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


def test_fragmentation_forces_fail_and_adds_issue(tmp_path):
    sheet = _sheet_with_checks(tmp_path, {**_CLEAN, "loose_parts": 30})
    j = GeometryAwareJudge(_Stub(Verdict(True, 0.95, ["MET - looks great"])))
    v = j.judge(str(sheet), rubric=None)
    assert v.passed is False
    assert any("fragmented" in i for i in v.issues)
    assert "MET - looks great" in v.issues  # inner issues preserved, structural unioned in


def test_inherent_non_manifold_does_not_force_fail(tmp_path):
    # the key live-validated behavior: a good Hunyuan3D mesh (hugely non-manifold, a few open edges,
    # 2 parts) must PASS through to the VLM verdict, not get force-failed on topology.
    sheet = _sheet_with_checks(tmp_path, {"non_manifold_edges": 331216, "open_edges": 112,
                                          "loose_parts": 2, "tri_count": 781004, "bounds_ok": True})
    j = GeometryAwareJudge(_Stub(Verdict(True, 0.9, ["MET - clean rover"])))
    v = j.judge(str(sheet), rubric=None)
    assert v.passed is True and v.score == 0.9 and v.issues == ["MET - clean rover"]


def test_empty_mesh_forces_fail(tmp_path):
    sheet = _sheet_with_checks(tmp_path, {**_CLEAN, "tri_count": 0})
    j = GeometryAwareJudge(_Stub(Verdict(True, 0.6, ["MET - ok"])))
    v = j.judge(str(sheet), rubric=None)
    assert v.passed is False
    assert any("empty" in i for i in v.issues)
    assert "MET - ok" in v.issues
    assert len(v.issues) == len(set(v.issues))  # no duplicates


def test_already_failed_inner_stays_failed_and_unions(tmp_path):
    sheet = _sheet_with_checks(tmp_path, {**_CLEAN, "bounds_ok": False})
    j = GeometryAwareJudge(_Stub(Verdict(False, 0.4, ["NOT-MET - wrong shape"])))
    v = j.judge(str(sheet), rubric=None)
    assert v.passed is False and v.score == 0.4
    assert "NOT-MET - wrong shape" in v.issues
    assert any("degenerate" in i for i in v.issues)


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
