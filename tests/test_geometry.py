from scripts.agent.geometry import structural_issues, RENDER_CHECKS_SUFFIX

_CLEAN = {"non_manifold_edges": 0, "open_edges": 0, "loose_parts": 1,
          "tri_count": 1000, "bounds_ok": True}


def test_clean_checks_produce_no_issues():
    assert structural_issues(_CLEAN) == []


def test_non_manifold_is_not_a_hard_fail():
    # raw Hunyuan3D output is inherently ~34% non-manifold (confirmed live, even at zero weld);
    # gating on it rejected every real mesh, so it must NOT flag.
    assert structural_issues({**_CLEAN, "non_manifold_edges": 331216}) == []


def test_open_edges_are_not_a_hard_fail():
    # some boundary edges are normal for surface-net meshes; the VLM sees real holes as gaps.
    assert structural_issues({**_CLEAN, "open_edges": 112}) == []


def test_a_few_loose_parts_are_tolerated():
    # body + antenna etc. is fine; only MANY islands signal fragmentation.
    assert structural_issues({**_CLEAN, "loose_parts": 2}) == []
    assert structural_issues({**_CLEAN, "loose_parts": 8}) == []


def test_excessive_fragmentation_flags():
    out = structural_issues({**_CLEAN, "loose_parts": 30})
    assert len(out) == 1 and "fragmented" in out[0] and "30" in out[0]
    assert out[0].startswith("NOT-MET:")


def test_loose_parts_threshold_is_tunable():
    assert structural_issues({**_CLEAN, "loose_parts": 4}, max_loose_parts=3)
    assert structural_issues({**_CLEAN, "loose_parts": 4}, max_loose_parts=8) == []


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
