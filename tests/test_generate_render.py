import json, argparse, pytest
from pathlib import Path
import scripts.generate as G


def test_render_params_comfy_scene():
    p = G._render_params(_args(mode="comfy-scene", as_="plane"), "/x/art.png", Path("/tmp/w"), 2)
    assert p["asset"] == "/x/art.png" and p["placement"] == "plane" and p["frames"] == 72
    assert "mesh" not in p


def test_replay_refuses_render_sidecar():
    with pytest.raises(ValueError, match="render"):
        G._args_from_sidecar({"schema": 2, "kind": "render", "modality": "render"})


def _args(**kw):
    base = dict(modality="render", brand=None, seed=7, from_="rover.glb", mode="mesh",
                samples=96, res=[1080, 1080], turntable=False, frames=72, as_="backdrop",
                target_tris=200000, watertight=False, scale_mm=None, color="material",
                formats="stl,glb", render_still=True, blender_bin=None, timeout=None)
    base.update(kw); return argparse.Namespace(**base)


def test_render_params_mesh():
    p = G._render_params(_args(turntable=True), "/x/rover.glb", Path("/tmp/w"), 7)
    assert p["mesh"] == "/x/rover.glb" and p["turntable"] is True and p["frames"] == 72
    assert p["samples"] == 96 and p["res"] == [1080, 1080] and p["engine"] == "CYCLES"
    assert p["out_dir"] == str(Path("/tmp/w"))


def test_render_params_finish():
    p = G._render_params(_args(mode="finish", formats="stl,glb"), "/x/m.glb", Path("/tmp/w"), 1)
    assert p["formats"] == ["stl", "glb"] and p["color"] == "material" and p["target_tris"] == 200000


def test_template_map():
    assert G._TEMPLATE_FOR_MODE["mesh"] == "mesh_render.py"
    assert G._TEMPLATE_FOR_MODE["comfy-scene"] == "comfy_to_scene.py"
    assert G._TEMPLATE_FOR_MODE["finish"] == "mesh_finish.py"


def test_run_render_routes_and_sidecars(tmp_path, monkeypatch, capsys):
    repo = tmp_path
    (repo / "rover.glb").write_text("x")  # brandless: --from is a direct path
    captured = {}
    monkeypatch.setattr(G.blender_runner, "run_template",
                        lambda t, p, **kw: {"outputs": [str(tmp_path / "a_hero.png")],
                                            "blender_version": "5.1.2"})
    (tmp_path / "a_hero.png").write_text("png")
    def fake_route(root, brand, src, mode, seed, **kw):
        dest = repo / "outputs" / "images" / f"{mode}_{seed}.png"
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text("png")
        captured["routed"] = dest; return dest
    monkeypatch.setattr(G, "route_output", fake_route)
    monkeypatch.setattr(G, "git_provenance", lambda r: "deadbee")
    G.run_render(_args(from_=str(repo / "rover.glb")), repo, argparse.ArgumentParser())
    side = captured["routed"].with_suffix(".json")
    meta = json.loads(side.read_text())
    assert meta["kind"] == "render" and meta["mode"] == "mesh" and meta["seed"] == 7
    assert meta["provenance"]["blender_version"] == "5.1.2"
