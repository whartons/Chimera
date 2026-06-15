import json
from pathlib import Path
import scripts.agent.render_generate as rg


class _FakeClient:
    def __init__(self):
        self.uploads, self.queued = [], 0

    def upload_image(self, path):
        self.uploads.append(Path(path))
        return f"uploaded::{Path(path).name}"

    def queue_prompt(self, wf):
        self.queued += 1
        return f"pid{self.queued}"

    def wait(self, pid, max_wait=None):
        return None


def _args(**kw):
    import argparse
    base = dict(brand=None, comfy_output_dir="/comfy/out", from_image=None, octree=256,
                samples=48, res=[640, 640], variant=None, model=None, blender_bin=None, timeout=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _wire(monkeypatch, tmp_path, client):
    """Stub the heavy seams; record what the closure does. Returns a `calls` dict."""
    calls = {"runner": None, "montage": None, "routed": [], "routed_src": []}

    monkeypatch.setattr(rg.image_filler, "build", lambda *a, **k: {"g": "txt2img"})
    monkeypatch.setattr(rg.threed_filler, "build", lambda *a, **k: {"g": "mesh"})
    monkeypatch.setattr(rg, "select_output",
                        lambda c, pid, wf, **k: ("concept.png", "", "output")
                        if wf.get("g") == "txt2img" else ("mesh.glb", "", "output"))

    def fake_route(root, brand, src, mode, seed, **kw):
        sub = "images" if Path(src).suffix == ".png" else "3d"
        dest = tmp_path / "outputs" / sub / f"{mode}_{seed}{Path(src).suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x")
        calls["routed"].append(dest)
        calls["routed_src"].append(Path(src))
        return dest

    monkeypatch.setattr(rg, "route_output", fake_route)

    def fake_runner(template, params, **kw):
        calls["runner"] = (Path(template).name, params)
        stills = [str(Path(params["out_dir"]) / f"{params['stem']}_v{i}.png") for i in range(4)]
        return {"outputs": stills, "checks": {"open_edges": 7}, "blender_version": "5.1.2"}

    def fake_montage(paths, out_path, *, cols=2):
        calls["montage"] = [Path(p) for p in paths]
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("sheet")
        return Path(out_path)

    monkeypatch.setattr(rg.montage, "contact_sheet", fake_montage)
    return calls, fake_runner


def test_generate_chains_concept_mesh_render_and_returns_sheet(monkeypatch, tmp_path):
    client = _FakeClient()
    calls, fake_runner = _wire(monkeypatch, tmp_path, client)
    gen = rg.make_render_generate(_args(), tmp_path, manifest=object(), client=client,
                                  blender_runner=fake_runner)
    sheet = gen("a knight, heroic", "blurry", 7)

    assert client.queued == 2
    assert client.uploads and client.uploads[0].name == "concept.png"
    assert calls["runner"][0] == "mesh_eval.py"
    assert calls["runner"][1]["views"] == 4 and calls["runner"][1]["seed"] == 7
    assert len(calls["montage"]) == 4
    assert Path(sheet).suffix == ".png" and Path(sheet).exists()
    cf = Path(sheet).with_name(Path(sheet).stem + rg.RENDER_CHECKS_SUFFIX)
    assert json.loads(cf.read_text())["open_edges"] == 7


def test_blender_failure_does_not_route_glb(monkeypatch, tmp_path):
    import pytest
    client = _FakeClient()
    calls, _ = _wire(monkeypatch, tmp_path, client)

    def boom(template, params, **kw):
        raise RuntimeError("blender exploded")

    gen = rg.make_render_generate(_args(), tmp_path, manifest=object(), client=client,
                                  blender_runner=boom)
    with pytest.raises(RuntimeError):
        gen("a knight", "blurry", 7)
    # a failed render must not orphan a routed GLB in outputs/3d
    assert not any(p.suffix == ".glb" for p in calls["routed"])


def test_from_image_skips_txt2img(monkeypatch, tmp_path):
    client = _FakeClient()
    calls, fake_runner = _wire(monkeypatch, tmp_path, client)
    concept = tmp_path / "fixed_concept.png"
    concept.write_text("img")
    gen = rg.make_render_generate(_args(from_image=str(concept)), tmp_path, manifest=object(),
                                  client=client, blender_runner=fake_runner)
    sheet = gen("ignored", "ignored", 11)
    assert client.queued == 1                       # mesh graph only; txt2img skipped
    assert client.uploads[0].name == "fixed_concept.png"
    # the rest of the chain still fires on the skip path
    assert calls["runner"] is not None and len(calls["montage"]) == 4
    assert Path(sheet).suffix == ".png" and Path(sheet).exists()


def _texture_args(**kw):
    # one source of truth for the baseline namespace: _args() + the texture fields
    return _args(texture=True, back_fill="palette", texture_res=1024, **kw)


class _PaletteManifest:
    palette = ["#1c1f22", "#2e3338"]


def test_texture_threads_concept_and_params_and_routes_textured_glb(monkeypatch, tmp_path):
    client = _FakeClient()
    calls, _ = _wire(monkeypatch, tmp_path, client)

    def textured_runner(template, params, **kw):
        calls["runner"] = (Path(template).name, params)
        stills = [str(Path(params["out_dir"]) / f"{params['stem']}_v{i}.png") for i in range(4)]
        tglb = str(Path(params["out_dir"]) / f"{params['stem']}_textured.glb")
        Path(tglb).write_text("glb")
        return {"outputs": stills, "checks": {"open_edges": 0}, "textured": True, "textured_glb": tglb}

    gen = rg.make_render_generate(_texture_args(), tmp_path, manifest=_PaletteManifest(),
                                  client=client, blender_runner=textured_runner)
    sheet = gen("a knight", "blurry", 7)

    rp = calls["runner"][1]
    assert rp["texture"] is True and rp["back_fill"] == "palette" and rp["texture_res"] == 1024
    assert rp["asset"].endswith("concept.png")
    assert rp["palette"] == ["#1c1f22", "#2e3338"]
    assert any(p.name.endswith("_textured.glb") for p in calls["routed_src"])
    tf = Path(sheet).with_name(Path(sheet).stem + rg.RENDER_TEXTURE_SUFFIX)
    meta = json.loads(tf.read_text())
    assert meta["textured"] is True
    assert meta["glb"].endswith(".glb")  # routed GLB name recorded for Phase 4b


def test_texture_off_still_writes_winner_sidecar(monkeypatch, tmp_path):
    # Phase 4b: the .texture.json sidecar is ALWAYS written (not just under --texture) so in-loop
    # finalize can recover the winner mesh + concept. Without --texture: textured=False, raw GLB.
    client = _FakeClient()
    calls, fake_runner = _wire(monkeypatch, tmp_path, client)
    gen = rg.make_render_generate(_args(), tmp_path, manifest=object(), client=client,
                                  blender_runner=fake_runner)
    sheet = gen("a knight", "blurry", 7)
    rp = calls["runner"][1]
    assert rp["texture"] is False
    assert any(p.name == "mesh.glb" for p in calls["routed_src"])
    tf = Path(sheet).with_name(Path(sheet).stem + rg.RENDER_TEXTURE_SUFFIX)
    meta = json.loads(tf.read_text())
    assert meta["textured"] is False
    assert meta["glb"].endswith(".glb")             # absolute GLB path recorded
    assert meta["concept"].endswith("concept.png")  # concept recorded IN PLACE
    assert meta["seed"] == 7                         # winning seed recorded
    # the concept is NOT routed — route_output MOVES, which would destroy a --from-image source
    assert not any(p.name == "concept.png" for p in calls["routed_src"])
