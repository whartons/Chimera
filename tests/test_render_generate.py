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
    calls = {"runner": None, "montage": None, "routed": []}

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


def test_from_image_skips_txt2img(monkeypatch, tmp_path):
    client = _FakeClient()
    calls, fake_runner = _wire(monkeypatch, tmp_path, client)
    concept = tmp_path / "fixed_concept.png"
    concept.write_text("img")
    gen = rg.make_render_generate(_args(from_image=str(concept)), tmp_path, manifest=object(),
                                  client=client, blender_runner=fake_runner)
    gen("ignored", "ignored", 11)
    assert client.queued == 1
    assert client.uploads[0].name == "fixed_concept.png"
