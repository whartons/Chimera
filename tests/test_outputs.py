import pytest
import scripts.brandkit.outputs as outputs
from scripts.brandkit.outputs import brand_output_dir, route_output

def test_brand_output_dir(tmp_path):
    d = brand_output_dir(tmp_path, "example-brand")
    assert d == tmp_path / "brands" / "example-brand" / "outputs"

def test_route_moves_file(tmp_path):
    src = tmp_path / "global" / "img_00001_.png"
    src.parent.mkdir(parents=True); src.write_bytes(b"PNG")
    dest = route_output(repo_root=tmp_path, brand="example-brand", src=src,
                        mode="txt2img", seed=7)
    assert dest.exists() and not src.exists()
    # routed by media type: a .png lands under outputs/images/
    assert dest.parent == tmp_path / "brands" / "example-brand" / "outputs" / "images"
    assert dest.name == "example-brand_txt2img_7.png"

def test_route_by_media_type(tmp_path):
    # foley is a video file -> video/ ; music is audio -> audio/ ; 3d -> 3d/
    for ext, sub in ((".mp4", "video"), (".mp3", "audio"), (".glb", "3d")):
        src = tmp_path / "global" / f"x{ext}"
        src.parent.mkdir(parents=True, exist_ok=True); src.write_bytes(b"X")
        dest = route_output(tmp_path, "example-brand", src, "foley", 42)
        assert dest.parent == tmp_path / "brands" / "example-brand" / "outputs" / sub
        assert dest.name == f"example-brand_foley_42{ext}"

def test_route_none_brand_keeps_in_place(tmp_path):
    src = tmp_path / "global" / "img.png"
    src.parent.mkdir(parents=True); src.write_bytes(b"P")
    dest = route_output(repo_root=tmp_path, brand=None, src=src, mode="txt2img", seed=1)
    assert dest == src and src.exists()

def test_route_overwrites_existing_dest(tmp_path):
    # a prior render already sits at the destination name (in the media-type subfolder)
    out_dir = tmp_path / "brands" / "example-brand" / "outputs" / "images"
    out_dir.mkdir(parents=True)
    (out_dir / "example-brand_txt2img_7.png").write_bytes(b"OLD")
    src = tmp_path / "global" / "new.png"
    src.parent.mkdir(parents=True); src.write_bytes(b"NEW")
    dest = route_output(repo_root=tmp_path, brand="example-brand", src=src,
                        mode="txt2img", seed=7)
    assert dest.read_bytes() == b"NEW" and not src.exists()

def test_route_retries_on_transient_lock(tmp_path, monkeypatch):
    src = tmp_path / "global" / "img.png"
    src.parent.mkdir(parents=True); src.write_bytes(b"P")
    real_move, calls = outputs.shutil.move, {"n": 0}
    def flaky_move(s, d):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("file locked by sync client")
        return real_move(s, d)
    monkeypatch.setattr(outputs.shutil, "move", flaky_move)
    dest = route_output(tmp_path, "example-brand", src, "txt2img", 9, _delay=0)
    assert dest.exists() and not src.exists() and calls["n"] == 2

def test_route_reraises_after_persistent_lock(tmp_path, monkeypatch):
    src = tmp_path / "global" / "img.png"
    src.parent.mkdir(parents=True); src.write_bytes(b"P")
    def always_locked(s, d):
        raise PermissionError("still locked")
    monkeypatch.setattr(outputs.shutil, "move", always_locked)
    with pytest.raises(PermissionError):
        route_output(tmp_path, "example-brand", src, "txt2img", 9, _retries=3, _delay=0)

import json as _json
from scripts.brandkit.outputs import first_output, NoOutputError, write_sidecar

def test_first_output_returns_first_tuple():
    files = [("a.png", "", "output"), ("b.png", "sub", "output")]
    assert first_output(files) == ("a.png", "", "output")

def test_first_output_empty_raises_with_seed_hint():
    with pytest.raises(NoOutputError) as e:
        first_output([])
    assert "seed" in str(e.value).lower()

def test_write_sidecar_records_model_and_seed(tmp_path):
    out = tmp_path / "brand_txt2img_7.png"; out.write_bytes(b"PNG")
    meta = {"seed": 7, "model": "z_image_bf16.safetensors", "mode": "txt2img",
            "prompt": "p", "negative": "n", "comfy_url": "http://x", "template": "brand-txt2img.json"}
    side = write_sidecar(out, meta)
    assert side == out.with_suffix(".json") and side.exists()
    data = _json.loads(side.read_text())
    assert data["model"] == "z_image_bf16.safetensors" and data["seed"] == 7
