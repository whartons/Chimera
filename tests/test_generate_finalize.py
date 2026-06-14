import json, argparse, pytest
from pathlib import Path
import scripts.generate as G


def _ft(**kw):
    base = dict(modality="finalize-texture", brand=None, seed=9, from_="win.glb",
                views="f.png,r.png,b.png,l.png", azimuths=None, elevation=15.0,
                back_fill="palette", texture_res=1024, samples=48, res=[768, 768],
                blender_bin=None, timeout=None)
    base.update(kw); return argparse.Namespace(**base)


def test_finalize_views_parsing():
    assert G._finalize_views(_ft(views="a.png, b.png ,c.png")) == ["a.png", "b.png", "c.png"]


def test_finalize_azimuths_default_even_spacing():
    assert G._finalize_azimuths(_ft(), 4) == [0.0, 90.0, 180.0, 270.0]
    assert G._finalize_azimuths(_ft(), 3) == [0.0, 120.0, 240.0]


def test_finalize_azimuths_explicit():
    assert G._finalize_azimuths(_ft(azimuths="0,45,90"), 3) == [0.0, 45.0, 90.0]


def test_finalize_params_shape():
    p = G._finalize_params(_ft(), "/x/win.glb", ["/x/f.png", "/x/b.png"], [0.0, 180.0], Path("/tmp/w"), 9, ["#1c4fb2"])
    assert p["mesh"] == "/x/win.glb" and p["view_images"] == ["/x/f.png", "/x/b.png"]
    assert p["azimuths"] == [0.0, 180.0] and p["palette"] == ["#1c4fb2"]
    assert p["back_fill"] == "palette" and p["texture_res"] == 1024 and p["elevation"] == 15.0
    assert p["stem"] == "finalize_9" and p["out_dir"] == str(Path("/tmp/w"))


def test_finalize_template_constant():
    assert G._FINALIZE_TEMPLATE == "mesh_finalize.py"


def test_validate_finalize_rejects_empty_views():
    with pytest.raises(SystemExit):
        G._validate_finalize(_ft(views=" , "), argparse.ArgumentParser())


def test_validate_finalize_rejects_azimuth_view_mismatch():
    with pytest.raises(SystemExit):
        G._validate_finalize(_ft(views="a.png,b.png", azimuths="0,90,180"), argparse.ArgumentParser())


def test_validate_finalize_accepts_matching_counts():
    G._validate_finalize(_ft(views="a.png,b.png", azimuths="0,180"), argparse.ArgumentParser())


def test_validate_finalize_rejects_too_many_views():
    with pytest.raises(SystemExit):  # 8 Proj UVs + 1 atlas > Blender's 8-UV-layer cap
        G._validate_finalize(_ft(views=",".join(f"v{i}.png" for i in range(8))), argparse.ArgumentParser())


def test_validate_finalize_rejects_non_numeric_azimuths():
    with pytest.raises(SystemExit):
        G._validate_finalize(_ft(views="a.png,b.png", azimuths="0,front"), argparse.ArgumentParser())


def test_run_finalize_texture_routes_glb_sheet_and_sidecar(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "win.glb").write_text("mesh")
    for v in ("f.png", "r.png", "b.png", "l.png"):
        (repo / v).write_text("img")
    monkeypatch.setattr(G.blender_runner, "run_template",
                        lambda t, p, **kw: {"textured_glb": str(tmp_path / "out.glb"),
                                            "outputs": [str(tmp_path / "v0.png"), str(tmp_path / "v1.png")],
                                            "blender_version": "5.1.2", "views": 4})
    (tmp_path / "out.glb").write_text("g")
    (tmp_path / "v0.png").write_text("p"); (tmp_path / "v1.png").write_text("p")
    routed = {}
    def fake_route(root, brand, src, mode, seed, **kw):
        dest = repo / "outputs" / ("3d" if Path(src).suffix == ".glb" else "images") / f"{mode}_{seed}{Path(src).suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text("x")
        routed[dest.suffix] = dest; return dest
    monkeypatch.setattr(G, "route_output", fake_route)
    monkeypatch.setattr(G, "git_provenance", lambda r: "deadbee")
    # contact_sheet would need Pillow + real images; stub it (its own tests cover it)
    import scripts.brandkit.montage as montage
    monkeypatch.setattr(montage, "contact_sheet", lambda paths, out, **kw: Path(out).write_text("sheet") or Path(out))
    views_abs = ",".join(str(repo / v) for v in ("f.png", "r.png", "b.png", "l.png"))
    G.run_finalize_texture(_ft(from_=str(repo / "win.glb"), views=views_abs), repo, argparse.ArgumentParser())
    side = routed[".glb"].with_suffix(".json")        # sidecar sits next to the textured GLB
    meta = json.loads(side.read_text())
    assert meta["kind"] == "render" and meta["mode"] == "finalize-texture" and meta["seed"] == 9
    assert meta["source"] == "win.glb"
    assert meta["params"]["azimuths"] == [0.0, 90.0, 180.0, 270.0]
    assert meta["params"]["views"] == ["f.png", "r.png", "b.png", "l.png"]
    assert meta["provenance"]["blender_version"] == "5.1.2"


def test_run_finalize_texture_survives_montage_failure(tmp_path, monkeypatch):
    # a failed verification sheet (e.g. Pillow absent) must NOT sink the finalize: the GLB + sidecar
    # still complete, just without the sheet.
    repo = tmp_path
    (repo / "win.glb").write_text("mesh")
    for v in ("f.png", "r.png", "b.png", "l.png"):
        (repo / v).write_text("img")
    monkeypatch.setattr(G.blender_runner, "run_template",
                        lambda t, p, **kw: {"textured_glb": str(tmp_path / "out.glb"),
                                            "outputs": [str(tmp_path / "v0.png")], "blender_version": "5.1.2"})
    (tmp_path / "out.glb").write_text("g"); (tmp_path / "v0.png").write_text("p")
    routed = {}
    def fake_route(root, brand, src, mode, seed, **kw):
        dest = repo / "outputs" / "3d" / f"{mode}_{seed}{Path(src).suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text("x")
        routed[Path(src).suffix] = dest; return dest
    monkeypatch.setattr(G, "route_output", fake_route)
    monkeypatch.setattr(G, "git_provenance", lambda r: None)
    import scripts.brandkit.montage as montage
    def boom(*a, **k):
        raise RuntimeError("Pillow not installed")
    monkeypatch.setattr(montage, "contact_sheet", boom)
    views_abs = ",".join(str(repo / v) for v in ("f.png", "r.png", "b.png", "l.png"))
    G.run_finalize_texture(_ft(from_=str(repo / "win.glb"), views=views_abs), repo, argparse.ArgumentParser())
    # the GLB sidecar still exists despite the montage failure
    meta = json.loads(routed[".glb"].with_suffix(".json").read_text())
    assert meta["mode"] == "finalize-texture"
    assert meta["outputs"] == ["finalize_9.glb"]   # GLB only — sheet was skipped


def test_run_finalize_texture_no_glb_exits(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "win.glb").write_text("mesh")
    for v in ("f.png", "r.png", "b.png", "l.png"):
        (repo / v).write_text("img")
    monkeypatch.setattr(G.blender_runner, "run_template", lambda t, p, **kw: {"outputs": []})
    views_abs = ",".join(str(repo / v) for v in ("f.png", "r.png", "b.png", "l.png"))
    with pytest.raises(SystemExit):
        G.run_finalize_texture(_ft(from_=str(repo / "win.glb"), views=views_abs), repo, argparse.ArgumentParser())


def test_run_finalize_texture_job_error_exits(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "win.glb").write_text("mesh")
    for v in ("f.png", "r.png", "b.png", "l.png"):
        (repo / v).write_text("img")
    def boom(t, p, **kw):
        raise G.blender_runner.BlenderJobError("kaboom")
    monkeypatch.setattr(G.blender_runner, "run_template", boom)
    views_abs = ",".join(str(repo / v) for v in ("f.png", "r.png", "b.png", "l.png"))
    with pytest.raises(SystemExit):
        G.run_finalize_texture(_ft(from_=str(repo / "win.glb"), views=views_abs), repo, argparse.ArgumentParser())
