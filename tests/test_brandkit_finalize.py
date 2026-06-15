from pathlib import Path
import pytest
import scripts.brandkit.finalize as F


def test_finalize_params_shape():
    p = F.finalize_params(mesh="/x/win.glb", view_paths=["/x/f.png", "/x/b.png"],
                          azimuths=[0.0, 180.0], brand=None, seed=9, elevation=15.0,
                          back_fill="palette", palette=["#1c4fb2"], texture_res=1024,
                          samples=48, res=[768, 768], out_dir="/tmp/w")
    assert p["mesh"] == "/x/win.glb" and p["view_images"] == ["/x/f.png", "/x/b.png"]
    assert p["azimuths"] == [0.0, 180.0] and p["palette"] == ["#1c4fb2"]
    assert p["back_fill"] == "palette" and p["texture_res"] == 1024 and p["elevation"] == 15.0
    assert p["stem"] == "finalize_9" and p["out_dir"] == "/tmp/w"
    assert p["samples"] == 48 and p["res"] == [768, 768] and p["seed"] == 9


def test_finalize_params_brand_stem():
    p = F.finalize_params(mesh="m", view_paths=[], azimuths=[], brand="acme", seed=3,
                          elevation=15.0, back_fill="palette", palette=[], texture_res=1024,
                          samples=48, res=[768, 768], out_dir="/t")
    assert p["stem"] == "acme_3"


def test_constants():
    assert F.FINALIZE_TEMPLATE == "mesh_finalize.py" and F.FINALIZE_TIMEOUT == 1800


class _FakeClient:
    def upload_image(self, p): return f"up::{Path(p).name}"
    def queue_prompt(self, wf): return "pid"
    def wait(self, pid, max_wait=None): return None
    def free(self): pass


def test_repaint_views_delegates_and_returns_paths(monkeypatch, tmp_path):
    captured = {}

    def fake_generate_views(client, **kw):
        captured.update(kw)
        return [str(tmp_path / "v0.png"), str(tmp_path / "v1.png")], ["d0", "d1"]

    monkeypatch.setattr(F.repaint_filler, "generate_views", fake_generate_views)
    runner = lambda *a, **k: {"outputs": []}
    views, az = F.repaint_views(_FakeClient(), mesh="m.glb", concept="c.png", subject="a rover",
                                azimuths=[0.0, 180.0], comfy_output_dir=str(tmp_path),
                                repo_root=tmp_path, blender_runner=runner, seed=7, res=1024)
    assert [Path(v).name for v in views] == ["v0.png", "v1.png"] and az == [0.0, 180.0]
    assert captured["render_views_template"].name == "render_views.py"
    assert captured["seed"] == 7 and captured["cn_strength"] == 0.7 and captured["ip_weight"] == 0.8


def test_repaint_views_underproduction_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(F.repaint_filler, "generate_views",
                        lambda client, **kw: ([str(tmp_path / "v0.png")], ["d0"]))   # 1 view, asked 2
    with pytest.raises(F.FinalizeError, match="under-produced"):
        F.repaint_views(_FakeClient(), mesh="m", concept="c", subject="s", azimuths=[0.0, 180.0],
                        comfy_output_dir=str(tmp_path), repo_root=tmp_path,
                        blender_runner=lambda *a, **k: {}, seed=1)
