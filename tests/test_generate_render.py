import json, argparse, pytest
from pathlib import Path
import scripts.brandkit.dcc_cli as G
from scripts.generate import _args_from_sidecar


def test_render_params_comfy_scene():
    p = G._render_params(_args(mode="comfy-scene", as_="plane"), "/x/art.png", Path("/tmp/w"), 2)
    assert p["asset"] == "/x/art.png" and p["placement"] == "plane" and p["frames"] == 72
    assert "mesh" not in p


def test_replay_refuses_render_sidecar():
    with pytest.raises(ValueError, match="render"):
        _args_from_sidecar({"schema": 2, "kind": "render", "modality": "render"})


def _args(**kw):
    base = dict(modality="render", brand=None, seed=7, from_="rover.glb", mode="mesh",
                samples=96, res=[1080, 1080], turntable=False, frames=72, as_="backdrop",
                target_tris=200000, watertight=False, solid=False, scale_mm=None, color="material",
                formats="stl,glb", render_still=True, project_image=None,
                blender_bin=None, timeout=None)
    base.update(kw); return argparse.Namespace(**base)


def test_finish_project_passes_image():
    p = G._render_params(_args(mode="finish", color="project", project_image="/x/c.png"),
                         "/x/m.glb", Path("/tmp/w"), 3)
    assert p["asset"] == "/x/c.png"


def test_finish_rejects_unsupported_formats(monkeypatch):
    # mesh_finish.py only exports stl/glb — an unsupported format must be a clean host-side
    # ap.error (like the cad path), not a silent exit-0 run with no export
    a = _args(mode="finish", formats="obj")
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: Path("/x/m.glb"))
    monkeypatch.setattr(G.blender_runner, "run_template",
                        lambda *x, **k: pytest.fail("blender must not run on invalid --formats"))
    with pytest.raises(SystemExit):
        G.run_render(a, Path("/tmp"), argparse.ArgumentParser())


def test_finish_project_requires_image(monkeypatch):
    a = _args(mode="finish", color="project", project_image=None)
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: Path("/x/m.glb"))
    with pytest.raises(SystemExit):
        G.run_render(a, Path("/tmp"), argparse.ArgumentParser())


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


def test_cli_finish_color_defaults_to_auto_and_accepts_keep(monkeypatch):
    # `auto` keeps a textured mesh's own materials: the old fixed `material` default replaced a TRELLIS.2
    # GLB's baked PBR textures with clay (2026-10)
    import sys
    import scripts.generate as GEN
    seen = []
    monkeypatch.setattr(GEN, "run_render", lambda args, root, ap: seen.append(args.color))
    for extra, want in (([], "auto"), (["--color", "keep"], "keep")):
        monkeypatch.setattr(sys, "argv", ["generate.py", "render", "--from", "m.glb", "--mode", "finish", *extra])
        GEN.main()
        assert seen[-1] == want


def test_finish_keep_rejects_watertight(monkeypatch):
    a = _args(mode="finish", color="keep", watertight=True)
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: Path("/x/m.glb"))
    monkeypatch.setattr(G.blender_runner, "run_template", lambda *x, **k: pytest.fail("must not run"))
    with pytest.raises(SystemExit):
        G.run_render(a, Path("/tmp"), argparse.ArgumentParser())



def test_finish_formats_ignore_case_and_cannot_be_empty(monkeypatch):
    # 'STL,GLB' passed the check but mesh_finish compares lowercase, so nothing was exported
    p = G._render_params(_args(mode="finish", formats="STL, GLB,stl"), "/x/m.glb", Path("/tmp/w"), 1)
    assert p["formats"] == ["stl", "glb"]
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: Path("/x/m.glb"))
    monkeypatch.setattr(G.blender_runner, "run_template", lambda *x, **k: pytest.fail("blender must not run"))
    with pytest.raises(SystemExit):
        G.run_render(_args(mode="finish", formats=" , "), Path("/tmp"), argparse.ArgumentParser())



def test_a_blender_job_listing_a_missing_file_is_one_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: tmp_path / "m.glb")
    monkeypatch.setattr(G.blender_runner, "run_template",
                        lambda t, p, **kw: {"outputs": [str(Path(p["out_dir"]) / "ghost.png")]})
    with pytest.raises(SystemExit) as e:
        G.run_render(_args(), tmp_path, argparse.ArgumentParser())
    err = capsys.readouterr().err
    assert e.value.code == 1 and "render failed: Blender listed ghost.png" in err and "comfy-output-dir" not in err


# --- --solid: AI sheets (TRELLIS.2, Pixal3D) rebuilt as one printable solid; STL in millimetres ---------------

REPO = Path(__file__).resolve().parents[1]


def _no_blender(*a, **k):
    pytest.fail("blender must not run")


@pytest.mark.parametrize("bad, why", [
    (dict(scale_mm=None), "needs --scale-mm"),
    (dict(scale_mm=200.0, watertight=True), "replaces --watertight"),
    (dict(scale_mm=200.0, color="keep"), "keep"),
])
def test_solid_rejects_bad_combinations_before_blender_runs(monkeypatch, capsys, bad, why):
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: Path("/x/m.glb"))
    monkeypatch.setattr(G.blender_runner, "run_template", _no_blender)
    with pytest.raises(SystemExit):
        G.run_render(_args(mode="finish", solid=True, **bad), Path("/tmp"), argparse.ArgumentParser())
    assert why in capsys.readouterr().err


def test_solid_without_the_print_extra_says_how_to_install_it(monkeypatch, capsys):
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: Path("/x/m.glb"))
    monkeypatch.setattr(G.blender_runner, "run_template", _no_blender)
    def missing():
        raise ImportError("No module named 'skimage'")
    monkeypatch.setattr(G, "_print_tools", missing)
    with pytest.raises(SystemExit):
        G.run_render(_args(mode="finish", solid=True, scale_mm=228.6), Path("/tmp"), argparse.ArgumentParser())
    assert ".[print]" in capsys.readouterr().err


class _FakeTools:
    """Stand-ins for the [print] modules: record the solidify call, report a fixed check."""
    def __init__(self, verdict="SOLID"):
        self.calls, self.verdict = [], verdict
        tools = self

        class _S:
            @staticmethod
            def solidify_file(src, dst, **kw):
                tools.calls.append(("solidify", Path(src), Path(dst)))
                Path(dst).write_text("solid")
                return {"close_mm": 1.6, "volume_cm3": 743.1, "voxel_mm": 0.3}

        class _PC:
            @staticmethod
            def check_file(path):
                tools.calls.append(("check", Path(path)))
                return {"size": [106.2, 147.5, 228.6], "volume_cm3": 743.1, "pieces": 1, "bad_edges": 0,
                        "units_warning": False, "verdict": tools.verdict, "inside_share": 0.14}

            @staticmethod
            def format_report(r, name=""):          # the real wording is tested in test_printcheck.py
                return f"print check {name}: verdict {r['verdict']}"

        self.solidify, self.printcheck = _S, _PC

    def __call__(self):
        return self.solidify, self.printcheck


def _fake_run(record, out_dir_files):
    def run(template, params, **kw):
        record.append((Path(template).name, dict(params)))
        if Path(template).name == "mesh_raw_mm.py":
            Path(params["out"]).write_text("raw")
            return {"outputs": [params["out"]], "holes": 3, "capped": 3}
        outs = []
        for name in out_dir_files:
            f = Path(params["out_dir"]) / name
            f.write_text("x")
            outs.append(str(f))
        return {"outputs": outs, "blender_version": "5.2.2"}
    return run


def _fake_route(repo):
    def route(root, brand, src, mode, seed, **kw):
        dest = repo / "outputs" / "3d" / Path(src).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x")
        return dest
    return route


def test_solid_exports_raw_mm_then_solidifies_then_finishes(tmp_path, monkeypatch):
    calls, tools = [], _FakeTools()
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: tmp_path / "trophy.glb")
    monkeypatch.setattr(G.blender_runner, "run_template", _fake_run(calls, ["t_finish_5.stl"]))
    monkeypatch.setattr(G, "_print_tools", tools)
    monkeypatch.setattr(G, "route_output", _fake_route(tmp_path))
    monkeypatch.setattr(G, "git_provenance", lambda r: "deadbee")
    G.run_render(_args(mode="finish", solid=True, scale_mm=228.6, formats="stl", seed=5), tmp_path,
                 argparse.ArgumentParser())
    (t1, p1), (t2, p2) = calls
    assert t1 == "mesh_raw_mm.py" and p1["mesh"] == str(tmp_path / "trophy.glb") and p1["size_mm"] == 228.6
    assert tools.calls[0][0] == "solidify" and tools.calls[0][1] == Path(p1["out"])
    assert t2 == "mesh_finish.py" and Path(p2["mesh"]) == tools.calls[0][2]
    assert p2["solid"] is True and p2["watertight"] is False and p2["scale_mm"] == 228.6
    meta = json.loads((tmp_path / "outputs" / "3d" / "t_finish_5.json").read_text())
    assert meta["params"]["solid"] is True
    assert meta["solidify"]["close_mm"] == 1.6
    assert meta["print_check"]["t_finish_5.stl"]["verdict"] == "SOLID"


def test_solid_says_and_records_which_pieces_it_kept(tmp_path, monkeypatch, capsys):
    # --solid kept only the largest piece and never said so: a separate plaque vanished (2026-10-25)
    calls, tools = [], _FakeTools()
    run = _fake_run(calls, ["t_finish_3.stl"])

    def with_pieces(template, params, **kw):
        m = run(template, params, **kw)
        if Path(template).name == "mesh_finish.py":
            m.update(pieces_kept=2, pieces_dropped=3, faces_dropped=412)
        return m
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: tmp_path / "trophy.glb")
    monkeypatch.setattr(G.blender_runner, "run_template", with_pieces)
    monkeypatch.setattr(G, "_print_tools", tools)
    monkeypatch.setattr(G, "route_output", _fake_route(tmp_path))
    monkeypatch.setattr(G, "git_provenance", lambda r: None)
    G.run_render(_args(mode="finish", solid=True, scale_mm=228.6, formats="stl", seed=3), tmp_path,
                 argparse.ArgumentParser())
    assert "kept 2 piece(s), dropped 3 speck(s) of 412 faces" in capsys.readouterr().out
    assert calls[1][1]["speck_frac"] == G.SPECK_FRAC == 0.01
    meta = json.loads((tmp_path / "outputs" / "3d" / "t_finish_3.json").read_text())
    assert (meta["solidify"]["pieces_kept"], meta["solidify"]["pieces_dropped"]) == (2, 3)
    assert meta["solidify"]["faces_dropped"] == 412


def test_a_solid_render_sidecar_holds_no_local_paths(tmp_path, monkeypatch):
    import re
    calls, tools = [], _FakeTools()
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: tmp_path / "trophy.glb")
    monkeypatch.setattr(G.blender_runner, "run_template", _fake_run(calls, ["t_finish_4.stl", "t_finish_4.glb"]))
    monkeypatch.setattr(G, "_print_tools", tools)
    monkeypatch.setattr(G, "route_output", _fake_route(tmp_path))
    monkeypatch.setattr(G, "git_provenance", lambda r: "deadbee")
    G.run_render(_args(mode="finish", solid=True, scale_mm=228.6, formats="stl,glb", seed=4,
                       color="project", project_image=str(tmp_path / "concept.png")), tmp_path,
                 argparse.ArgumentParser())
    bad = re.compile(r"^[A-Za-z]:[\\/]|^/(?!/)|[\\/](Users|home)[\\/]")       # as test_integration's sidecar check

    def strings(v):
        if isinstance(v, dict):
            return [s for x in v.values() for s in strings(x)]
        if isinstance(v, list):
            return [s for x in v for s in strings(x)]
        return [v] if isinstance(v, str) else []
    meta = json.loads((tmp_path / "outputs" / "3d" / "t_finish_4.json").read_text())
    assert [s for s in strings(meta) if bad.search(s)] == []


def test_every_stl_is_print_checked_and_a_hollow_one_is_reported(tmp_path, monkeypatch, capsys):
    calls, tools = [], _FakeTools(verdict="HOLLOW")
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: tmp_path / "trophy.glb")
    monkeypatch.setattr(G.blender_runner, "run_template", _fake_run(calls, ["t_finish_6.stl"]))
    monkeypatch.setattr(G, "_print_tools", tools)
    monkeypatch.setattr(G, "route_output", _fake_route(tmp_path))
    monkeypatch.setattr(G, "git_provenance", lambda r: None)
    G.run_render(_args(mode="finish", watertight=True, scale_mm=228.6, formats="stl", seed=6), tmp_path,
                 argparse.ArgumentParser())
    assert [c[0] for c in tools.calls] == ["check"]              # no solidify without --solid
    assert "verdict HOLLOW" in capsys.readouterr().out
    meta = json.loads((tmp_path / "outputs" / "3d" / "t_finish_6.json").read_text())
    assert meta["print_check"]["t_finish_6.stl"]["verdict"] == "HOLLOW"


def test_finish_without_the_print_extra_still_works_and_skips_the_check(tmp_path, monkeypatch, capsys):
    calls = []
    def missing():
        raise ImportError("No module named 'numpy'")
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: tmp_path / "m.glb")
    monkeypatch.setattr(G.blender_runner, "run_template", _fake_run(calls, ["m_finish_7.stl"]))
    monkeypatch.setattr(G, "_print_tools", missing)
    monkeypatch.setattr(G, "route_output", _fake_route(tmp_path))
    monkeypatch.setattr(G, "git_provenance", lambda r: None)
    G.run_render(_args(mode="finish", formats="stl", seed=7), tmp_path, argparse.ArgumentParser())
    assert "print check skipped" in capsys.readouterr().err


@pytest.mark.parametrize("err, want", [
    (ValueError("no closed volume to fill: the mesh is an open surface"), "no closed volume"),
    (MemoryError(), "out of memory"),
])
def test_a_solidify_failure_is_a_clean_cli_error(tmp_path, monkeypatch, capsys, err, want):
    # a ValueError or MemoryError from solidify reached the user as a raw traceback (2026-10-25)
    calls, tools = [], _FakeTools()

    def fail(src, dst, **kw):
        raise err
    tools.solidify.solidify_file = staticmethod(fail)
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: tmp_path / "trophy.glb")
    monkeypatch.setattr(G.blender_runner, "run_template", _fake_run(calls, ["t_finish_8.stl"]))
    monkeypatch.setattr(G, "_print_tools", tools)
    monkeypatch.setattr(G, "route_output", _fake_route(tmp_path))
    with pytest.raises(SystemExit) as e:
        G.run_render(_args(mode="finish", solid=True, scale_mm=228.6, formats="stl", seed=8), tmp_path,
                     argparse.ArgumentParser())
    err_text = capsys.readouterr().err
    assert e.value.code == 1 and "render failed: solidify" in err_text and want in err_text
    assert [t for t, _ in calls] == ["mesh_raw_mm.py"]                   # the finish never ran


def test_a_print_check_that_breaks_still_leaves_the_sidecar(tmp_path, monkeypatch, capsys):
    # an exception from the check came after routing, so the outputs were left without a sidecar
    calls, tools = [], _FakeTools()

    def broken(path):
        raise ValueError("the STL has no triangles")
    tools.printcheck.check_file = staticmethod(broken)
    monkeypatch.setattr(G, "_resolve_asset", lambda *x, **k: tmp_path / "m.glb")
    monkeypatch.setattr(G.blender_runner, "run_template", _fake_run(calls, ["m_finish_9.stl"]))
    monkeypatch.setattr(G, "_print_tools", tools)
    monkeypatch.setattr(G, "route_output", _fake_route(tmp_path))
    monkeypatch.setattr(G, "git_provenance", lambda r: None)
    G.run_render(_args(mode="finish", formats="stl", seed=9), tmp_path, argparse.ArgumentParser())
    assert "print check of m_finish_9.stl failed" in capsys.readouterr().err
    meta = json.loads((tmp_path / "outputs" / "3d" / "m_finish_9.json").read_text())
    assert "no triangles" in meta["print_check"]["m_finish_9.stl"]["error"]


@pytest.mark.parametrize("asset, scale_mm, want", [
    ("/x/m.glb", None, 1000.0),      # glTF is in metres: a 1-unit GLB is a 1000 mm STL
    ("/x/m.fbx", None, 1000.0),
    ("/x/m.glb", 60.0, 1000.0),      # --scale-mm sizes the model in metres; a slicer read 60 as 0.06 mm
    ("/x/part.stl", None, 1.0),      # STL/OBJ are unitless, mm by convention (a FreeCAD part): keep the
    ("/x/PART.OBJ", None, 1.0),      #   numbers, or a 30 mm part comes back 30,000 mm
    ("/x/part.stl", 60.0, 1000.0),   # rescaled to metres, so back to mm (the --solid path lands here)
])
def test_finish_stl_scale_follows_the_input_units(asset, scale_mm, want):
    p = G._render_params(_args(mode="finish", scale_mm=scale_mm), asset, Path("/tmp/w"), 3)
    assert p["stl_scale"] == want


def test_finish_template_exports_stl_at_the_host_scale():
    src = (REPO / "workflows" / "templates" / "blender" / "mesh_finish.py").read_text(encoding="utf-8")
    assert 'global_scale=float(p.get("stl_scale", 1000.0))' in src


def test_cli_accepts_solid(monkeypatch):
    import sys
    import scripts.generate as GEN
    seen = []
    monkeypatch.setattr(GEN, "run_render", lambda args, root, ap: seen.append((args.solid, args.scale_mm)))
    monkeypatch.setattr(sys, "argv", ["generate.py", "render", "--from", "m.glb", "--mode", "finish", "--solid",
                                      "--scale-mm", "228.6"])
    GEN.main()
    assert seen == [(True, 228.6)]


def test_two_finishes_with_one_seed_keep_both_and_each_keeps_its_files_together(tmp_path, monkeypatch):
    # the second finish replaced the first one's still, STL, GLB and sidecar (2026-10-25 review)
    (tmp_path / "a.glb").write_text("a")
    (tmp_path / "b.glb").write_text("b")

    def fake_blender(t, p, **kw):
        outs = [Path(p["out_dir"]) / f"{p['stem']}{ext}" for ext in (".png", ".stl", ".glb")]
        for o in outs:
            o.write_text(Path(p["mesh"]).name)
        return {"outputs": [str(o) for o in outs], "blender_version": "5.2.2"}
    monkeypatch.setattr(G.blender_runner, "run_template", fake_blender)
    monkeypatch.setattr(G, "_check_stls", lambda paths, tools: {})
    monkeypatch.setattr(G, "git_provenance", lambda r: None)
    for mesh in ("a.glb", "b.glb"):
        G.run_render(_args(mode="finish", from_=str(tmp_path / mesh)), tmp_path, argparse.ArgumentParser())
    out = tmp_path / "outputs"
    assert sorted(p.name for p in (out / "3d").iterdir()) == ["finish_7.glb", "finish_7.stl",
                                                              "finish_7_2.glb", "finish_7_2.stl"]
    assert sorted(p.name for p in (out / "images").iterdir()) == ["finish_7.json", "finish_7.png",
                                                                  "finish_7_2.json", "finish_7_2.png"]
    assert (out / "3d" / "finish_7.stl").read_text() == "a.glb" and (out / "3d" / "finish_7_2.stl").read_text() == "b.glb"
    assert json.loads((out / "images" / "finish_7_2.json").read_text())["source"] == "b.glb"
