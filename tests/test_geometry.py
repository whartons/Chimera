from scripts.agent.geometry import structural_issues, RENDER_CHECKS_SUFFIX

_CLEAN = {"non_manifold_edges": 0, "open_edges": 0, "loose_parts": 1,
          "tri_count": 1000, "bounds_ok": True}


def test_clean_checks_produce_no_issues():
    assert structural_issues(_CLEAN) == []


def test_open_edges_flag_watertight():
    out = structural_issues({**_CLEAN, "open_edges": 12})
    assert len(out) == 1 and "watertight" in out[0] and "12" in out[0]
    assert out[0].startswith("NOT-MET:")


def test_non_manifold_flag():
    out = structural_issues({**_CLEAN, "non_manifold_edges": 3})
    assert len(out) == 1 and "not manifold" in out[0] and "3" in out[0]


def test_loose_parts_only_flag_above_one():
    assert structural_issues({**_CLEAN, "loose_parts": 1}) == []
    out = structural_issues({**_CLEAN, "loose_parts": 4})
    assert "disconnected parts" in out[0] and "4" in out[0]


def test_empty_and_degenerate():
    assert any("0 triangles" in i for i in structural_issues({**_CLEAN, "tri_count": 0}))
    assert any("near-zero extent" in i for i in structural_issues({**_CLEAN, "bounds_ok": False}))


def test_missing_keys_are_treated_as_clean():
    assert structural_issues({}) == []


def test_none_values_treated_as_clean():
    # A malformed/empty checks.json (json null) must not false-trigger — None == "not measured".
    none_checks = {k: None for k in _CLEAN}
    assert structural_issues(none_checks) == []


def test_suffix_constant():
    assert RENDER_CHECKS_SUFFIX == ".checks.json"
