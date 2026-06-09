import builtins
from pathlib import Path
from scripts.brandkit import doctor

ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    def __init__(self, stats=None, object_info=None, stats_raises=False, oi_raises=False):
        self._stats, self._oi = stats, object_info
        self._sr, self._oir = stats_raises, oi_raises

    def system_stats(self):
        if self._sr:
            raise OSError("connection refused")
        return self._stats

    def object_info(self):
        if self._oir:
            raise OSError("no object_info")
        return self._oi


def _oi(types, models=()):
    """Build a fake /object_info. Values are intentionally minimal: only the keys matter for the
    node-presence check (set membership); the nested input schema only matters for _available_models,
    which is exercised separately with a realistic shape in test_available_models_extracts_dropdown_enum."""
    oi = {t: {} for t in types}
    if models:
        oi["UNETLoader"] = {"input": {"required": {"unet_name": [list(models), {}]}}}
    return oi


def test_template_class_types_nonempty_strings():
    types = doctor._template_class_types(ROOT)
    assert types and all(isinstance(t, str) for t in types)


def test_available_models_extracts_dropdown_enum():
    oi = {"UNETLoader": {"input": {"required": {"unet_name": [["a.safetensors", "b.safetensors"], {}]}}},
          "Other": {"input": {"required": {"scalar": ["INT", {}]}}}}  # non-list-of-list -> ignored
    assert doctor._available_models(oi) == {"a.safetensors", "b.safetensors"}


def test_doctor_unreachable_reports_fail_and_skips_node_check():
    results = doctor.run_checks(FakeClient(stats_raises=True), ROOT)
    assert results[0][0] == "fail" and "not reachable" in results[0][1]
    assert not any("node type" in msg for _, msg in results)   # node/model checks skipped


def test_doctor_all_template_nodes_present_and_version_shown():
    types = doctor._template_class_types(ROOT)
    results = doctor.run_checks(
        FakeClient(stats={"system": {"comfyui_version": "v0.24.1"}}, object_info=_oi(types)), ROOT)
    assert ("ok", "all workflow-template node types are installed") in results
    assert any(lvl == "ok" and "reachable (v0.24.1)" in msg for lvl, msg in results)


def test_doctor_missing_node_type_warns():
    types = doctor._template_class_types(ROOT)
    one = sorted(types)[0]
    results = doctor.run_checks(
        FakeClient(stats={"system": {}}, object_info=_oi(types - {one})), ROOT)
    assert any(lvl == "warn" and one in msg for lvl, msg in results)


def test_doctor_object_info_unreadable_warns():
    results = doctor.run_checks(FakeClient(stats={"system": {}}, oi_raises=True), ROOT)
    assert any(lvl == "warn" and "/object_info" in msg for lvl, msg in results)


def test_doctor_brand_model_present_and_absent(tmp_path):
    brand_dir = tmp_path / "brands" / "b"; (brand_dir / "logos").mkdir(parents=True)
    (brand_dir / "brand.yaml").write_text(
        'name: "B"\ndefaults: { model: z_image_turbo_nvfp4.safetensors }\n', encoding="utf-8")
    present = doctor.run_checks(
        FakeClient(stats={"system": {}}, object_info=_oi(set(), models=["z_image_turbo_nvfp4.safetensors"])),
        tmp_path, "b")
    assert any(lvl == "ok" and "defaults.model installed" in msg for lvl, msg in present)
    absent = doctor.run_checks(
        FakeClient(stats={"system": {}}, object_info=_oi(set(), models=["other.safetensors"])),
        tmp_path, "b")
    assert any(lvl == "warn" and "defaults.model not found" in msg for lvl, msg in absent)


def test_doctor_malformed_brand_yaml_degrades_not_crashes(tmp_path):
    # doctor must NEVER raise — a malformed brand.yaml should produce a [FAIL] line, not a traceback
    bdir = tmp_path / "brands" / "bad"; bdir.mkdir(parents=True)
    (bdir / "brand.yaml").write_text(":::: not valid yaml ::::\n", encoding="utf-8")
    results = doctor.run_checks(FakeClient(stats={"system": {}}, object_info=_oi(set())), tmp_path, "bad")
    assert any(lvl == "fail" for lvl, _ in results)   # lint reported the bad manifest, no crash


def test_doctor_reports_missing_optional_helpers(monkeypatch):
    # force PIL + av to be unimportable so the ('info', ...) arm with the pip hints is exercised
    real_import = builtins.__import__
    def no_optional(name, *a, **k):
        if name in ("PIL", "av"):
            raise ImportError("forced")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_optional)
    results = doctor.run_checks(FakeClient(stats={"system": {}}, object_info=_oi(set())), ROOT)
    assert ("info", "PIL not installed - optional (non-PNG logo sizing); pip install pillow") in results
    assert ("info", "av not installed - optional (foley fps/duration auto-probe); pip install av") in results


def test_doctor_malformed_system_stats_still_reachable(monkeypatch):
    # a reachable server returning {'system': None} must report reachable (unknown version), not fail
    results = doctor.run_checks(FakeClient(stats={"system": None}, object_info=_oi(set())), ROOT)
    assert any(lvl == "ok" and "reachable (unknown version)" in msg for lvl, msg in results)


def test_print_doctor_returns_fail_count(capsys):
    results = [("ok", "fine"), ("warn", "meh"), ("fail", "broken"), ("fail", "also broken")]
    assert doctor.print_doctor("b", results) == 2
    out = capsys.readouterr().out
    assert "[FAIL]" in out and "-> 2 fail, 1 warn" in out
