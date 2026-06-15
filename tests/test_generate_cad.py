import json, argparse, pytest
from pathlib import Path
import scripts.generate as G


def _cad(**kw):
    base = dict(modality="cad", brand=None, seed=5, mode="primitive", shape="box",
                length=40.0, width=30.0, height=20.0, radius=15.0, radius2=0.0,
                inner_radius=8.0, from_=None, script=None, formats="step,stl",
                freecad_bin=None, timeout=None)
    base.update(kw); return argparse.Namespace(**base)


def test_cad_params_box():
    p = G._cad_params(_cad(shape="box"), None, Path("/tmp/w"), 5)
    assert p["shape"] == "box" and p["length"] == 40.0 and p["width"] == 30.0 and p["height"] == 20.0
    assert p["formats"] == ["step", "stl"] and p["out_dir"] == str(Path("/tmp/w"))
    assert p["stem"] == "cad_primitive_5"


def test_cad_params_tube_carries_inner_radius():
    p = G._cad_params(_cad(shape="tube", radius=10.0, inner_radius=6.0, height=30.0), None, Path("/tmp/w"), 1)
    assert p["shape"] == "tube" and p["radius"] == 10.0 and p["inner_radius"] == 6.0 and p["height"] == 30.0
    assert "length" not in p   # tube doesn't carry box dims


def test_cad_params_convert_carries_source():
    p = G._cad_params(_cad(mode="convert", from_="part.step"), "/abs/part.step", Path("/tmp/w"), 2)
    assert p["source"] == "/abs/part.step" and p["formats"] == ["step", "stl"]
    assert "shape" not in p
    assert p["stem"] == "cad_convert_2"


def test_cad_sidecar_params_primitive_and_convert():
    assert G._cad_sidecar_params(_cad(shape="cylinder", radius=12.0, height=40.0)) == \
        {"radius": 12.0, "height": 40.0, "formats": ["step", "stl"]}
    assert G._cad_sidecar_params(_cad(mode="convert", formats="stl")) == {"formats": ["stl"]}


def test_template_map_cad():
    assert G._TEMPLATE_FOR_CAD == {"primitive": "primitive.py", "convert": "convert.py",
                                   "script": "script_exec.py"}


def test_cad_params_script_carries_script_path():
    p = G._cad_params(_cad(mode="script"), "/abs/model.py", Path("/tmp/w"), 3)
    assert p["script"] == "/abs/model.py" and "shape" not in p and "source" not in p
    assert p["formats"] == ["step", "stl"] and p["stem"] == "cad_script_3"


def test_cad_sidecar_params_script_records_name_and_revision_hash(tmp_path):
    s = tmp_path / "m.py"; s.write_text("box = 1")
    d = G._cad_sidecar_params(_cad(mode="script", script=str(s)))
    assert d["script"] == "m.py" and len(d["script_sha"]) == 16 and d["formats"] == ["step", "stl"]
    s.write_text("box = 2")   # in-place revision must change the hash so the params_signature varies
    assert G._cad_sidecar_params(_cad(mode="script", script=str(s)))["script_sha"] != d["script_sha"]


def test_validate_cad_script_requires_existing_file(tmp_path):
    with pytest.raises(SystemExit):   # no --script
        G._validate_cad(_cad(mode="script", script=None), argparse.ArgumentParser())
    with pytest.raises(SystemExit):   # --script points at nothing
        G._validate_cad(_cad(mode="script", script=str(tmp_path / "nope.py")), argparse.ArgumentParser())


def test_validate_cad_script_accepts_existing_file(tmp_path):
    s = tmp_path / "model.py"; s.write_text("pass")
    G._validate_cad(_cad(mode="script", script=str(s)), argparse.ArgumentParser())


def test_run_cad_script_routes_and_sidecars(tmp_path, monkeypatch):
    repo = tmp_path
    s = repo / "model.py"; s.write_text("# build a thing")
    monkeypatch.setattr(G.freecad_runner, "run_template",
                        lambda t, p, **kw: {"outputs": [str(tmp_path / "m.step")],
                                            "freecad_version": "1.1.1", "objects": 1})
    (tmp_path / "m.step").write_text("s")
    def fake_route(root, brand, src, mode, seed, **kw):
        dest = repo / "outputs" / "3d" / f"{mode}_{seed}{Path(src).suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text("x"); return dest
    monkeypatch.setattr(G, "route_output", fake_route)
    monkeypatch.setattr(G, "git_provenance", lambda r: None)
    G.run_cad(_cad(mode="script", script=str(s), formats="step"), repo, argparse.ArgumentParser())
    meta = json.loads((repo / "outputs" / "3d" / "script_5.json").read_text())
    assert meta["kind"] == "cad" and meta["mode"] == "script"
    assert meta["shape"] is None and meta["source"] == "model.py"


def test_primary_cad_output_prefers_step_then_stl():
    paths = [Path("a.stl"), Path("a.step"), Path("a.obj")]
    assert G._primary_cad_output(paths).suffix == ".step"
    assert G._primary_cad_output([Path("a.obj"), Path("a.stl")]).suffix == ".stl"
    assert G._primary_cad_output([Path("a.obj")]).suffix == ".obj"


def test_validate_cad_rejects_bad_format():
    with pytest.raises(SystemExit):
        G._validate_cad(_cad(formats="step,glb"), argparse.ArgumentParser())


def test_validate_cad_rejects_empty_format():
    with pytest.raises(SystemExit):
        G._validate_cad(_cad(formats=" , "), argparse.ArgumentParser())


def test_validate_cad_rejects_tube_bore_ge_radius():
    with pytest.raises(SystemExit):
        G._validate_cad(_cad(shape="tube", radius=5.0, inner_radius=5.0), argparse.ArgumentParser())


def test_validate_cad_rejects_nonpositive_dim():
    with pytest.raises(SystemExit):
        G._validate_cad(_cad(shape="box", length=0.0), argparse.ArgumentParser())


def test_validate_cad_allows_cone_sharp_tip():
    # radius2 == 0 is a valid cone tip and must NOT be rejected
    G._validate_cad(_cad(shape="cone", radius=10.0, radius2=0.0, height=20.0), argparse.ArgumentParser())


def test_validate_cad_rejects_negative_cone_radius2():
    with pytest.raises(SystemExit):
        G._validate_cad(_cad(shape="cone", radius=10.0, radius2=-1.0, height=20.0), argparse.ArgumentParser())


def test_validate_cad_convert_mesh_to_step_refused():
    with pytest.raises(SystemExit):
        G._validate_cad(_cad(mode="convert", from_="m.stl", formats="step"), argparse.ArgumentParser())


def test_validate_cad_convert_mesh_to_stl_ok():
    G._validate_cad(_cad(mode="convert", from_="m.stl", formats="stl,obj"), argparse.ArgumentParser())


def test_validate_cad_convert_rejects_unsupported_source_ext():
    # a .glb legitimately lives in outputs/3d but the convert template can't import it
    with pytest.raises(SystemExit):
        G._validate_cad(_cad(mode="convert", from_="model.glb", formats="stl"), argparse.ArgumentParser())


def test_validate_cad_convert_accepts_brep_source():
    G._validate_cad(_cad(mode="convert", from_="part.iges", formats="step,stl"), argparse.ArgumentParser())


def test_cad_formats_dedups_and_normalizes_case():
    assert G._cad_formats(_cad(formats="step,step")) == ["step"]
    assert G._cad_formats(_cad(formats="STEP, STL")) == ["step", "stl"]


def test_run_cad_routes_and_sidecars(tmp_path, monkeypatch):
    repo = tmp_path
    monkeypatch.setattr(G.freecad_runner, "run_template",
                        lambda t, p, **kw: {"outputs": [str(tmp_path / "x.step"), str(tmp_path / "x.stl")],
                                            "freecad_version": "1.1.1", "shape": "box"})
    (tmp_path / "x.step").write_text("s"); (tmp_path / "x.stl").write_text("m")
    routed = {}
    def fake_route(root, brand, src, mode, seed, **kw):
        dest = repo / "outputs" / "3d" / f"{mode}_{seed}{Path(src).suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text("x")
        routed[dest.suffix] = dest; return dest
    monkeypatch.setattr(G, "route_output", fake_route)
    monkeypatch.setattr(G, "git_provenance", lambda r: "deadbee")
    G.run_cad(_cad(shape="box"), repo, argparse.ArgumentParser())
    side = routed[".step"].with_suffix(".json")   # primary = .step
    meta = json.loads(side.read_text())
    assert meta["kind"] == "cad" and meta["mode"] == "primitive" and meta["shape"] == "box"
    assert meta["seed"] == 5 and meta["provenance"]["freecad_version"] == "1.1.1"
    assert meta["provenance"]["pipeline_git_sha"] == "deadbee"


def test_run_cad_convert_records_source_and_null_shape(tmp_path, monkeypatch):
    repo = tmp_path
    src = repo / "part.step"; src.write_text("brep")   # brandless: --from is a direct path
    monkeypatch.setattr(G.freecad_runner, "run_template",
                        lambda t, p, **kw: {"outputs": [str(tmp_path / "c.stl")], "freecad_version": "1.1.1"})
    (tmp_path / "c.stl").write_text("m")
    def fake_route(root, brand, s, mode, seed, **kw):
        dest = repo / "outputs" / "3d" / f"{mode}_{seed}{Path(s).suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text("x"); return dest
    monkeypatch.setattr(G, "route_output", fake_route)
    monkeypatch.setattr(G, "git_provenance", lambda r: None)
    G.run_cad(_cad(mode="convert", from_=str(src), formats="stl"), repo, argparse.ArgumentParser())
    meta = json.loads((repo / "outputs" / "3d" / "convert_5.json").read_text())
    assert meta["kind"] == "cad" and meta["mode"] == "convert"
    assert meta["shape"] is None and meta["source"] == "part.step"


def test_run_cad_empty_outputs_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(G.freecad_runner, "run_template", lambda t, p, **kw: {"outputs": []})
    with pytest.raises(SystemExit):
        G.run_cad(_cad(shape="box"), tmp_path, argparse.ArgumentParser())


def test_run_cad_job_error_exits(tmp_path, monkeypatch):
    def boom(t, p, **kw):
        raise G.freecad_runner.FreeCADJobError("kaboom")
    monkeypatch.setattr(G.freecad_runner, "run_template", boom)
    with pytest.raises(SystemExit):
        G.run_cad(_cad(shape="box"), tmp_path, argparse.ArgumentParser())


def test_replay_refuses_cad_sidecar():
    with pytest.raises(ValueError, match="cad"):
        G._args_from_sidecar({"schema": 2, "kind": "cad", "modality": "cad"})
