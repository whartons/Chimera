"""Unit tests for the pure/near-pure helpers behind the generate.py CLI seam (no live ComfyUI).
The orchestrators run()/main() interleave argparse + IO + HTTP and are covered end-to-end
elsewhere; these target the separable logic: the logo size probe, watermark applicability, the
PyAV-guarded video probe, and the per-modality _prepare_* arg->fkw mapping + validation branches."""
from __future__ import annotations
import argparse, builtins, struct, types
from pathlib import Path
import pytest
from scripts import generate
from scripts.generate import _image_size, _supports_watermark, _probe_video
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit import workflow as image_filler
from scripts.brandkit import video as video_filler

FIX = Path(__file__).parent / "fixtures" / "brand.yaml"
M = load_manifest(FIX)


def _args_ns(**over):
    """A full argparse.Namespace seeded with every sidecar input key = None, plus modality/mode."""
    base = {k: None for k in generate.SIDECAR_INPUT_KEYS}
    base.update(modality=None, mode=None)
    base.update(over)
    return argparse.Namespace(**base)


class _FakeUploadClient:
    def upload_image(self, p): return f"up:{Path(p).name}"
    def upload_video(self, p): return f"vid:{Path(p).name}"


class _ApError(Exception):
    pass


class _StubAp:
    """Stand-in for argparse's parser: .error(msg) aborts — here by raising so tests can assert it."""
    def error(self, msg): raise _ApError(msg)


# ----------------------------------------------------------------------------- _image_size (B3)
def _png_header(w, h):
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00")


def test_image_size_png_header_fallback(tmp_path, monkeypatch):
    # force the no-Pillow path so the PNG-header fallback is exercised deterministically
    real_import = builtins.__import__
    def no_pil(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("forced: no Pillow")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_pil)
    p = tmp_path / "logo.png"; p.write_bytes(_png_header(320, 200))
    assert _image_size(p) == (320, 200)


def test_image_size_non_png_without_pillow_is_none(tmp_path, monkeypatch):
    # a JPG with no Pillow available -> None (the old PNG-only behavior, now an explicit fallback)
    real_import = builtins.__import__
    def no_pil(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("forced: no Pillow")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_pil)
    p = tmp_path / "logo.jpg"; p.write_bytes(b"\xff\xd8\xff\xe0not-really-a-jpeg")
    assert _image_size(p) is None


def test_image_size_unreadable_returns_none(tmp_path):
    # neither a PNG header nor (if Pillow is present) a decodable image -> None on both paths
    p = tmp_path / "logo.bin"; p.write_bytes(b"this is plainly not an image")
    assert _image_size(p) is None


def test_image_size_truncated_png_returns_none(tmp_path, monkeypatch):
    # a valid PNG signature but <24 bytes must return None (the contract), not raise struct.error
    real_import = builtins.__import__
    def no_pil(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("forced: no Pillow")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_pil)
    p = tmp_path / "t.png"; p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")  # signature + 2 bytes
    assert _image_size(p) is None


def test_image_size_jpeg_with_pillow(tmp_path):
    Image = pytest.importorskip("PIL.Image")  # only meaningful when Pillow is installed
    p = tmp_path / "logo.jpg"
    Image.new("RGB", (321, 123)).save(p)
    assert _image_size(p) == (321, 123)


def test_image_size_webp_with_pillow(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    p = tmp_path / "logo.webp"
    try:
        Image.new("RGB", (200, 150)).save(p)
    except (KeyError, OSError):
        pytest.skip("WebP not supported by this Pillow build")
    assert _image_size(p) == (200, 150)


# ----------------------------------------------------------------------- _supports_watermark (B5)
def test_supports_watermark_table():
    assert _supports_watermark("image", "txt2img") is True
    assert _supports_watermark("image", "product") is True
    assert _supports_watermark("image", "logo") is False     # logo already composites a logo
    assert _supports_watermark("video", "i2v") is True
    assert _supports_watermark("audio", "foley") is True
    assert _supports_watermark("audio", "music") is False    # no visual canvas
    assert _supports_watermark("3d", "image") is False


# --------------------------------------------------------------------------- _probe_video (B5)
def test_probe_video_without_pyav_returns_none_tuple(monkeypatch):
    real_import = builtins.__import__
    def no_av(name, *a, **k):
        if name == "av":
            raise ImportError("forced: no PyAV")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_av)
    assert _probe_video("anything.mp4") == (None, None, None, None)


# ----------------------------------------------------- _resolve_model_used / _sidecar_inputs (B6/B5)
def test_resolve_model_used_per_modality():
    rm = generate._resolve_model_used
    assert rm(_args_ns(modality="video", mode="i2v"), M) == video_filler.resolved_model(M)
    from scripts.brandkit import audio as af
    assert rm(_args_ns(modality="audio", mode="foley"), M) == af.resolved_model(M, "foley")
    assert rm(_args_ns(modality="audio", mode="music"), M) == af.resolved_model(M, "music")
    assert rm(_args_ns(modality="3d", mode="image", model="x3d.safetensors"), M) == "x3d.safetensors"
    # image resolves through the Z-Image variant logic, not the brand default verbatim
    assert rm(_args_ns(modality="image", mode="product", variant=None, model=None), M) == \
        image_filler.resolve_image_model("product", None, M.defaults.model)


def test_resolve_sidecar_inputs_image_upscale_on_off():
    on = generate._resolve_sidecar_inputs(
        _args_ns(modality="image", mode="txt2img", subject="s", upscale=True, upscale_model=None), M)
    assert on["upscale"] is True
    assert on["upscale_model"] == image_filler.resolved_upscale_model(M, None)
    off = generate._resolve_sidecar_inputs(
        _args_ns(modality="image", mode="txt2img", subject="s", upscale=False), M)
    assert off["upscale"] is None and off["upscale_model"] is None


def test_resolve_sidecar_inputs_video_uses_video_resolver():
    inp = generate._resolve_sidecar_inputs(
        _args_ns(modality="video", mode="i2v", from_image="r.png", upscale=True,
                 upscale_model="cli.safetensors"), M)
    assert inp["upscale"] is True
    assert inp["upscale_model"] == video_filler.resolved_upscale_model(M, "cli.safetensors")


def test_resolve_sidecar_inputs_3d_records_resolved_format():
    inp = generate._resolve_sidecar_inputs(
        _args_ns(modality="3d", mode="image", from_image="r.png", octree=256), M, fmt="stl")
    assert inp["format"] == "stl"


# ------------------------------------------------------------------------------ _prepare_* (B5)
def test_prepare_image_logo_uploads_and_sizes(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "_image_size", lambda p: (100, 50))  # decouple from the probe
    brand_dir = tmp_path / "brands" / "b"; (brand_dir / "logos").mkdir(parents=True)
    (brand_dir / "logos" / "primary.png").write_bytes(b"x")
    args = _args_ns(modality="image", mode="logo", asset="primary.png", brand="b")
    fkw = generate._prepare_image(args, M, brand_dir, _FakeUploadClient(), _StubAp())
    assert fkw["asset"] == "up:primary.png"
    assert fkw["logo_px"] == (int(100 * M.logo.scale), int(50 * M.logo.scale))
    assert fkw["upscale_model"] is None  # raw passthrough (filler resolves)


def test_prepare_image_logo_missing_asset_calls_ap_error(tmp_path):
    brand_dir = tmp_path / "brands" / "b"; (brand_dir / "logos").mkdir(parents=True)
    args = _args_ns(modality="image", mode="logo", asset="nope.png", brand="b")
    with pytest.raises(_ApError):
        generate._prepare_image(args, M, brand_dir, _FakeUploadClient(), _StubAp())


def test_prepare_image_logo_unsized_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(generate, "_image_size", lambda p: None)  # non-PNG / no Pillow
    brand_dir = tmp_path / "brands" / "b"; (brand_dir / "logos").mkdir(parents=True)
    (brand_dir / "logos" / "logo.webp").write_bytes(b"x")
    args = _args_ns(modality="image", mode="logo", asset="logo.webp", brand="b")
    fkw = generate._prepare_image(args, M, brand_dir, _FakeUploadClient(), _StubAp())
    assert "logo_px" not in fkw                       # no size -> filler falls back to canvas math
    assert "approximate" in capsys.readouterr().err   # user is warned


def test_prepare_video_maps_args_and_passes_raw_upscale_model(tmp_path):
    brand_dir = tmp_path / "brands" / "b"; (brand_dir / "products").mkdir(parents=True)
    (brand_dir / "products" / "r.png").write_bytes(b"x")
    args = _args_ns(modality="video", from_image="r.png", length=49, fps=24, audio=False,
                    width=960, height=544, upscale=True, upscale_model="u.safetensors", brand="b")
    fkw = generate._prepare_video(args, M, brand_dir, _FakeUploadClient(), _StubAp())
    assert fkw["from_image"] == "up:r.png"            # the start frame is an image upload
    assert (fkw["length"], fkw["fps"], fkw["audio"]) == (49, 24, False)
    assert (fkw["width"], fkw["height"]) == (960, 544)
    assert fkw["upscale"] is True and fkw["upscale_model"] == "u.safetensors"


def test_prepare_video_missing_from_image_errors(tmp_path):
    args = _args_ns(modality="video", from_image=None, brand="b")
    with pytest.raises(_ApError):
        generate._prepare_video(args, M, tmp_path, _FakeUploadClient(), _StubAp())


def test_prepare_audio_music_maps(tmp_path):
    args = _args_ns(modality="audio", mode="music", duration=6.0, bpm=120, keyscale="C major", brand="b")
    fkw = generate._prepare_audio(args, M, tmp_path, _FakeUploadClient(), _StubAp())
    assert fkw == {"mode": "music", "duration": 6.0, "bpm": 120, "keyscale": "C major"}


def test_prepare_audio_foley_maps(tmp_path, monkeypatch):
    # hermetic: stub the probe so the test never depends on whether PyAV is installed (av.open on a
    # fake mp4 would raise when PyAV is present). Explicit --fps/--duration win over the probe anyway.
    monkeypatch.setattr(generate, "_probe_video", lambda p: (30.0, 9.9, 640, 480))
    brand_dir = tmp_path / "brands" / "b"; (brand_dir / "references").mkdir(parents=True)
    (brand_dir / "references" / "s.mp4").write_bytes(b"x")
    args = _args_ns(modality="audio", mode="foley", from_video="s.mp4", fps=25.0, duration=3.0, brand="b")
    fkw = generate._prepare_audio(args, M, brand_dir, _FakeUploadClient(), _StubAp())
    assert fkw["mode"] == "foley" and fkw["from_video"] == "vid:s.mp4"
    assert fkw["frame_rate"] == 25.0 and fkw["duration"] == 3.0 and fkw["fps"] == 25.0


def test_prepare_audio_foley_missing_video_errors(tmp_path):
    args = _args_ns(modality="audio", mode="foley", from_video=None, brand="b")
    with pytest.raises(_ApError):
        generate._prepare_audio(args, M, tmp_path, _FakeUploadClient(), _StubAp())


def test_prepare_3d_maps(tmp_path):
    brand_dir = tmp_path / "brands" / "b"; (brand_dir / "products").mkdir(parents=True)
    (brand_dir / "products" / "r.png").write_bytes(b"x")
    args = _args_ns(modality="3d", mode="image", from_image="r.png", model="m3d.safetensors", octree=128, brand="b")
    fkw = generate._prepare_3d(args, M, brand_dir, _FakeUploadClient(), _StubAp())
    assert fkw == {"mode": "image", "from_image": "up:r.png", "octree": 128, "model": "m3d.safetensors"}


def test_prepare_3d_missing_image_errors(tmp_path):
    brand_dir = tmp_path / "brands" / "b"; brand_dir.mkdir(parents=True)
    args = _args_ns(modality="3d", mode="image", from_image="nope.png", model=None, octree=128, brand="b")
    with pytest.raises(_ApError):
        generate._prepare_3d(args, M, brand_dir, _FakeUploadClient(), _StubAp())


# ------------------------------------------------------------- git_provenance (reproducibility)
def _fake_run_factory(rev_out, status_out, returncode=0):
    def fake_run(cmd, **k):
        out = rev_out if "rev-parse" in cmd else status_out
        return types.SimpleNamespace(returncode=returncode, stdout=out, stderr="")
    return fake_run


def test_git_provenance_clean(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", _fake_run_factory("abc1234\n", ""))  # porcelain empty
    assert generate.git_provenance("anyroot") == "abc1234"


def test_git_provenance_dirty(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", _fake_run_factory("abc1234\n", " M scripts/x.py\n"))
    assert generate.git_provenance("anyroot") == "abc1234-dirty"


def test_git_provenance_not_a_repo(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", _fake_run_factory("", "", returncode=128))
    assert generate.git_provenance("anyroot") is None


def test_git_provenance_git_absent(monkeypatch):
    import subprocess
    def boom(cmd, **k):
        raise FileNotFoundError("git not on PATH")
    monkeypatch.setattr(subprocess, "run", boom)
    assert generate.git_provenance("anyroot") is None


# ------------------------------------------------------------------ auto_generate.py helpers (B5)
def test_write_run_sidecar_none_image_short_circuits(monkeypatch):
    from scripts.agent import auto_generate as ag
    calls = []
    monkeypatch.setattr(ag, "write_sidecar", lambda *a, **k: calls.append(1))
    ag._write_run_sidecar(types.SimpleNamespace(best_image=None), types.SimpleNamespace(), Path("."))
    assert calls == []  # no winning image -> no sidecar written


def test_write_run_sidecar_builds_agent_run_meta(monkeypatch, tmp_path):
    from scripts.agent import auto_generate as ag
    captured = {}
    monkeypatch.setattr(ag, "write_sidecar", lambda path, meta: captured.update(path=path, meta=meta))
    monkeypatch.setattr(ag, "git_provenance", lambda root: "abc1234")  # hermetic: no real subprocess
    rec = types.SimpleNamespace(iter=0, seed=7, prompt="P",
                                verdict=types.SimpleNamespace(score=0.9, passed=True))
    result = types.SimpleNamespace(best_image="img.png", history=[rec], passed=True,
                                   best_verdict=types.SimpleNamespace(score=0.97))
    args = types.SimpleNamespace(brand="b", subject="s", backend="local", comfy_url="http://x")
    ag._write_run_sidecar(result, args, tmp_path)
    meta = captured["meta"]
    assert meta["kind"] == "agent-run" and meta["schema"] == 2      # the replay-refusal discriminator
    assert meta["brand"] == "b" and meta["winning_seed"] == 7
    assert meta["final_score"] == 0.97 and meta["passed"] is True and meta["iterations"] == 1
    assert meta["provenance"]["pipeline_git_sha"] == "abc1234"      # provenance recorded


def test_make_generate_queues_waits_and_routes(monkeypatch, tmp_path):
    from scripts.agent import auto_generate as ag
    class FC:
        def queue_prompt(self, wf): return "pid"
        def wait(self, pid, max_wait=0): return {}
        def output_files_by_node(self, pid): return [("10", "f.png", "sub", "output")]
        def output_filenames(self, pid): return [("f.png", "sub", "output")]
    # build returns a graph whose canonical save node carries the brand:save title
    monkeypatch.setattr(ag.image_filler, "build",
                        lambda *a, **k: {"10": {"_meta": {"title": "brand:save"}, "inputs": {}}})
    monkeypatch.setattr(ag, "route_output", lambda root, brand, src, mode, seed: Path(src))
    args = types.SimpleNamespace(comfy_output_dir=str(tmp_path), brand="b",
                                 variant=None, model=None, timeout=10)
    gen = ag._make_generate(args, tmp_path, M, FC())
    out = gen("pos", "neg", 7)
    assert out == str(tmp_path / "sub" / "f.png")   # routed via the brand:save-anchored output


def test_print_summary_runs(capsys):
    from scripts.agent import auto_generate as ag
    rec = types.SimpleNamespace(iter=0, seed=7, verdict=types.SimpleNamespace(score=0.9, passed=True))
    result = types.SimpleNamespace(best_image="x.png", passed=True,
                                   best_verdict=types.SimpleNamespace(score=0.9), history=[rec])
    ag._print_summary(result)
    out = capsys.readouterr().out
    assert "winning image" in out and "iter 0" in out
