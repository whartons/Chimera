"""End-to-end smoke tests for the CLI seam — the glue (run/main) that unit tests don't cover.
A fully-faked ComfyClient (no server, no GPU) drives the whole pipeline: parse args -> build the
real graph -> queue -> route the output -> write the sidecar. Catches wiring regressions (wrong
route, missing sidecar, bad dispatch) that per-function unit tests miss."""
from __future__ import annotations
import argparse, json, shutil, sys
from pathlib import Path
import pytest
from scripts import generate

ROOT = Path(__file__).resolve().parents[1]


class FakeComfy:
    """A ComfyClient stand-in: 'queues', 'waits', and reports one produced output — no network."""
    def __init__(self, url=None):
        pass
    def free(self, **k):
        pass
    def upload_image(self, p):
        return f"up:{Path(p).name}"
    def queue_prompt(self, wf):
        self.wf = wf
        return "pid"
    def wait(self, pid, max_wait=0):
        return {}
    def output_files_by_node(self, pid):
        return [("999", "out.png", "", "output")]   # node id won't match brand:save -> falls back
    def output_filenames(self, pid):
        return [("out.png", "", "output")]
    def comfyui_version(self):
        return "vTest"


class _StubAp:
    def error(self, msg):
        raise AssertionError(f"ap.error unexpectedly called: {msg}")


def _img_args(**over):
    base = dict(modality="image", mode="txt2img", brand="b", subject="a rover", seed=None,
                variant=None, model=None, asset=None, upscale=False, upscale_model=None,
                watermark=False, comfy_url="http://x", comfy_output_dir=None,
                free_before=None, timeout=None, out_name=None, from_image=None, from_video=None,
                length=None, fps=None, width=None, height=None, audio=True, duration=None,
                bpm=None, keyscale=None, octree=None)
    base.update(over)
    return argparse.Namespace(**base)


def _tmp_repo(tmp_path):
    """A minimal repo: the one template the zimage txt2img path loads + a minimal brand."""
    (tmp_path / "workflows" / "templates").mkdir(parents=True)
    shutil.copy(ROOT / "workflows" / "templates" / "brand-zimage-txt2img.json",
                tmp_path / "workflows" / "templates" / "brand-zimage-txt2img.json")
    bdir = tmp_path / "brands" / "b"; bdir.mkdir(parents=True)
    (bdir / "brand.yaml").write_text(
        'name: "B"\ndefaults: { model: z_image_turbo_nvfp4.safetensors }\n', encoding="utf-8")
    return tmp_path


def test_run_image_end_to_end_routes_and_writes_sidecar(monkeypatch, tmp_path):
    repo = _tmp_repo(tmp_path)
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    comfyout = tmp_path / "comfyout"; comfyout.mkdir()
    (comfyout / "out.png").write_bytes(b"PNGDATA")          # the file the fake "produced"

    generate.run(_img_args(seed=7, comfy_output_dir=str(comfyout)), repo, _StubAp())

    dest = repo / "brands" / "b" / "outputs" / "images" / "b_txt2img_7.png"
    assert dest.exists() and dest.read_bytes() == b"PNGDATA"   # routed to the brand folder by media type
    side = dest.with_suffix(".json")
    assert side.exists()
    meta = json.loads(side.read_text(encoding="utf-8"))
    assert meta["modality"] == "image" and meta["mode"] == "txt2img" and meta["seed"] == 7
    assert meta["model"] == "z_image_turbo_nvfp4.safetensors"   # resolved via the filler
    # provenance flowed end-to-end (graph signature always, faked comfyui version)
    assert meta["provenance"]["graph_signature"]
    assert meta["provenance"]["comfyui_version"] == "vTest"


def test_run_image_upscale_records_resolved_model_in_sidecar(monkeypatch, tmp_path):
    # second end-to-end case exercising the upscale-on branch: the sidecar must record the RESOLVED
    # upscaler (filler-owned), proving that branch of run()/_resolve_sidecar_inputs is wired
    from scripts.brandkit.workflow import DEFAULT_UPSCALE_MODEL
    repo = _tmp_repo(tmp_path)
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    comfyout = tmp_path / "comfyout"; comfyout.mkdir()
    (comfyout / "out.png").write_bytes(b"PNGDATA")
    generate.run(_img_args(seed=9, comfy_output_dir=str(comfyout), upscale=True), repo, _StubAp())
    meta = json.loads((repo / "brands" / "b" / "outputs" / "images" / "b_txt2img_9.json")
                      .read_text(encoding="utf-8"))
    assert meta["inputs"]["upscale"] is True
    assert meta["inputs"]["upscale_model"] == DEFAULT_UPSCALE_MODEL


def test_run_without_output_dir_prints_filename_only(monkeypatch, tmp_path, capsys):
    # no --comfy-output-dir: it shouldn't route/sidecar, just print the raw ComfyUI filename
    repo = _tmp_repo(tmp_path)
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    generate.run(_img_args(seed=3), repo, _StubAp())
    out = capsys.readouterr().out
    assert "out.png" in out
    assert not (repo / "brands" / "b" / "outputs").exists()    # nothing routed


def test_run_brandless_routes_to_global_outputs(monkeypatch, tmp_path):
    # no --brand: neutral manifest, output -> repo_root/outputs/<media>/<mode>_<seed>, sidecar brand=None
    (tmp_path / "workflows" / "templates").mkdir(parents=True)
    shutil.copy(ROOT / "workflows" / "templates" / "brand-zimage-txt2img.json",
                tmp_path / "workflows" / "templates" / "brand-zimage-txt2img.json")
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    comfyout = tmp_path / "comfyout"; comfyout.mkdir()
    (comfyout / "out.png").write_bytes(b"PNGDATA")
    generate.run(_img_args(brand=None, seed=7, comfy_output_dir=str(comfyout)), tmp_path, _StubAp())
    dest = tmp_path / "outputs" / "images" / "txt2img_7.png"
    assert dest.exists() and dest.read_bytes() == b"PNGDATA"   # global outputs/, not a brand folder
    meta = json.loads(dest.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["brand"] is None
    assert meta["model"] == "z_image_turbo_nvfp4.safetensors"  # brandless default model


def test_run_brandless_watermark_errors(tmp_path):
    # --watermark needs a brand (the logo lives in the brand folder) -> clean ap.error, no crash
    class _Err(Exception):
        pass
    class _Ap:
        def error(self, msg):
            raise _Err(msg)
    with pytest.raises(_Err):
        generate.run(_img_args(brand=None, watermark=True), tmp_path, _Ap())


def test_main_image_brandless_dispatches(monkeypatch):
    # --brand is now optional: `chimera image --subject ...` parses (brand=None) and dispatches
    captured = {}
    monkeypatch.setattr(generate, "run",
                        lambda args, repo_root, ap: captured.update(brand=args.brand, subj=args.subject))
    monkeypatch.setattr(sys, "argv", ["generate.py", "image", "--subject", "a rover"])
    generate.main()
    assert captured == {"brand": None, "subj": "a rover"}


def test_main_dispatches_image_to_run(monkeypatch):
    captured = {}
    monkeypatch.setattr(generate, "run",
                        lambda args, repo_root, ap: captured.update(mod=args.modality, subj=args.subject))
    monkeypatch.setattr(sys, "argv",
                        ["generate.py", "image", "--brand", "b", "--subject", "a rover", "--seed", "5"])
    generate.main()
    assert captured == {"mod": "image", "subj": "a rover"}


def test_main_replay_reads_sidecar_then_runs(monkeypatch, tmp_path):
    sidecar = tmp_path / "s.json"
    sidecar.write_text(json.dumps({
        "schema": 2, "modality": "image", "mode": "txt2img", "brand": "b", "seed": 7,
        "inputs": {"subject": "x"}, "comfy_url": "http://x"}), encoding="utf-8")
    captured = {}
    monkeypatch.setattr(generate, "run",
                        lambda args, repo_root, ap: captured.update(brand=args.brand, seed=args.seed))
    monkeypatch.setattr(sys, "argv", ["generate.py", "replay", str(sidecar)])
    generate.main()
    assert captured == {"brand": "b", "seed": 7}


def test_main_lint_dispatches_and_exits_with_fail_count(monkeypatch):
    # dispatch test, DECOUPLED from any real brand: a clean lint result -> exit 0
    import scripts.brandkit.scaffold as scaffold
    monkeypatch.setattr(scaffold, "lint_brand", lambda root, brand: [("ok", "clean")])
    monkeypatch.setattr(sys, "argv", ["generate.py", "lint", "--brand", "whatever"])
    with pytest.raises(SystemExit) as e:
        generate.main()
    assert e.value.code == 0


def test_example_brand_lints_clean():
    # fixture-health (separate from dispatch): the tracked example-brand must lint with zero fails,
    # so a failure here points at the brand assets, not at main()'s wiring
    from scripts.brandkit.scaffold import lint_brand
    assert [m for lvl, m in lint_brand(ROOT, "example-brand") if lvl == "fail"] == []


def test_main_doctor_dispatches_green(monkeypatch):
    import scripts.brandkit.doctor as d
    monkeypatch.setattr(generate, "ComfyClient", lambda url: object())
    monkeypatch.setattr(d, "run_checks", lambda client, root, brand: [("ok", "all good")])
    monkeypatch.setattr(sys, "argv", ["generate.py", "doctor"])
    with pytest.raises(SystemExit) as e:
        generate.main()
    assert e.value.code == 0


def test_main_doctor_exits_1_on_fail(monkeypatch):
    # the exit-code contract: doctor finding a fail must exit non-zero (for CI/scripting)
    import scripts.brandkit.doctor as d
    monkeypatch.setattr(generate, "ComfyClient", lambda url: object())
    monkeypatch.setattr(d, "run_checks", lambda client, root, brand: [("fail", "broken")])
    monkeypatch.setattr(sys, "argv", ["generate.py", "doctor", "--brand", "b"])
    with pytest.raises(SystemExit) as e:
        generate.main()
    assert e.value.code == 1
