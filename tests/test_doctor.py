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


def test_repaint_class_types_derived_from_builder():
    # the Phase-4b auto-repaint graph is built inline (no tracked template) — its node types must
    # be derivable for doctor, sourced from the builder itself so they can never drift
    types = doctor._repaint_class_types()
    assert "IPAdapterAdvanced" in types and "ControlNetApplyAdvanced" in types


def test_doctor_checks_repaint_graph_nodes():
    # a box with every TEMPLATE node type but no IPAdapter pack must warn — otherwise
    # finalize-texture --auto-repaint dies mid-run after the Blender depth renders completed
    types = doctor._template_class_types(ROOT)
    results = doctor.run_checks(
        FakeClient(stats={"system": {"comfyui_version": "v1"}}, object_info=_oi(types)), ROOT)
    assert not any(lvl == "ok" and "node types are installed" in msg for lvl, msg in results)
    assert any("IPAdapterAdvanced" in msg for _, msg in results)


def test_doctor_loads_brand_manifest_once(monkeypatch):
    # run_checks previously parsed brand.yaml twice (lint + model checks) — pin the single load
    from scripts.brandkit import scaffold, manifest as mf
    calls = []
    real = mf.load_manifest
    def counting(p):
        calls.append(p)
        return real(p)
    monkeypatch.setattr(doctor, "load_manifest", counting)
    monkeypatch.setattr(scaffold, "load_manifest", counting)
    types = doctor._required_class_types(ROOT)
    doctor.run_checks(FakeClient(stats={"system": {}}, object_info=_oi(types)), ROOT,
                      brand="example-brand")
    assert len(calls) == 1


def test_doctor_unreachable_reports_fail_and_skips_node_check():
    results = doctor.run_checks(FakeClient(stats_raises=True), ROOT)
    assert results[0][0] == "fail" and "not reachable" in results[0][1]
    assert not any("node type" in msg for _, msg in results)   # node/model checks skipped


def test_doctor_all_required_nodes_present_and_version_shown():
    types = doctor._required_class_types(ROOT)   # templates + the inline repaint graph
    results = doctor.run_checks(
        FakeClient(stats={"system": {"comfyui_version": "v0.24.1"}}, object_info=_oi(types)), ROOT)
    assert ("ok", "all required workflow node types are installed") in results
    assert any(lvl == "ok" and "reachable (v0.24.1)" in msg for lvl, msg in results)


def test_doctor_missing_node_type_warns():
    types = doctor._required_class_types(ROOT)
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
    # force PIL, av and skimage to be unimportable so the ('info', ...) arm with the pip hints is exercised
    real_import = builtins.__import__
    def no_optional(name, *a, **k):
        if name in ("PIL", "av", "skimage"):
            raise ImportError("forced")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_optional)
    results = doctor.run_checks(FakeClient(stats={"system": {}}, object_info=_oi(set())), ROOT)
    # Pillow also builds the contact sheet the mesh3d and cad loops judge, and auto_generate refuses them without it
    assert ("info", "PIL not installed - optional (non-PNG logo sizing, and the contact sheet the mesh3d and cad "
                    "loops judge); pip install pillow") in results
    assert ("info", "av not installed - optional (foley fps/duration auto-probe); pip install av") in results
    assert ("info", "skimage not installed - optional (3D printing: render --mode finish --solid + the STL "
                    "print check); pip install -e .[print]") in results


def test_doctor_malformed_system_stats_still_reachable(monkeypatch):
    # a reachable server returning {'system': None} must report reachable (unknown version), not fail
    results = doctor.run_checks(FakeClient(stats={"system": None}, object_info=_oi(set())), ROOT)
    assert any(lvl == "ok" and "reachable (unknown version)" in msg for lvl, msg in results)


def test_print_doctor_returns_fail_count(capsys):
    results = [("ok", "fine"), ("warn", "meh"), ("fail", "broken"), ("fail", "also broken")]
    assert doctor.print_doctor("b", results) == 2
    out = capsys.readouterr().out
    assert "[FAIL]" in out and "-> 2 fail, 1 warn" in out


def test_doctor_resolves_a_3d_short_name_before_checking_it_is_installed(tmp_path):
    # a brand may pin threed.model: pixal3d; doctor must look for the FILE that resolves to
    from scripts.brandkit.doctor import run_checks
    (tmp_path / "workflows" / "templates").mkdir(parents=True)
    bdir = tmp_path / "brands" / "b"; bdir.mkdir(parents=True)
    (bdir / "brand.yaml").write_text('name: "B"\ndefaults: { model: z_image_turbo_nvfp4.safetensors }\n'
                                     'threed: { model: pixal3d }\n', encoding="utf-8")
    client = FakeClient(stats={"system": {}}, object_info=_oi(set(), models=[
        "z_image_turbo_nvfp4.safetensors", "pixal3d_int8_convrot.safetensors"]))
    out = run_checks(client, tmp_path, "b")
    assert any(lvl == "ok" and "pixal3d_int8_convrot.safetensors" in msg for lvl, msg in out)


def test_available_models_reads_v3_combo_options_and_optional_inputs():
    # ComfyUI 0.40 v3 nodes report a dropdown as ["COMBO", {"options": [...]}]: doctor missed them and
    # flagged an installed birefnet.safetensors as missing (2026-10)
    oi = {"LoadBackgroundRemovalModel": {"input": {"required": {
              "bg_removal_name": ["COMBO", {"tooltip": "t", "options": ["birefnet.safetensors"]}]}}},
          "X": {"input": {"optional": {"m": [["opt.safetensors"], {}]}}}}
    assert {"birefnet.safetensors", "opt.safetensors"} <= doctor._available_models(oi)


def test_doctor_reports_each_modalitys_default_model_files():
    rows = doctor._default_model_files(ROOT)
    assert [r[0] for r in rows] == ["image", "--upscale", "video", "video --camera", "music / sfx", "3d"]
    every = {f for r in rows for f in r[3]}
    types = doctor._required_class_types(ROOT)
    out = doctor.run_checks(FakeClient(stats={"system": {}}, object_info=_oi(types, sorted(every))), ROOT)
    assert sum(1 for lvl, msg in out if lvl == "ok" and " default (" in msg) == len(rows)
    one = rows[-1][3][0]                       # drop one 3D file: only the 3d row warns, and names it
    out = doctor.run_checks(FakeClient(stats={"system": {}}, object_info=_oi(types, sorted(every - {one}))), ROOT)
    warns = [msg for lvl, msg in out if lvl == "warn" and " default (" in msg]
    assert len(warns) == 1 and warns[0].startswith("3d default (TRELLIS.2)") and one in warns[0]



def test_available_models_skips_inputs_that_are_not_dropdowns():
    from scripts.brandkit.doctor import _available_models
    info = {"N": {"input": {"required": {"steps": "INT", "empty": [], "ckpt": [["a.safetensors"], {}]},
                            "optional": {"vae": ["COMBO", {"options": ["v.safetensors"]}]}}}}
    assert _available_models(info) == {"a.safetensors", "v.safetensors"}
