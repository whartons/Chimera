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
    shutil.copy(ROOT / "workflows" / "templates" / "brand-qwen-image-txt2img.json",
                tmp_path / "workflows" / "templates" / "brand-qwen-image-txt2img.json")
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    comfyout = tmp_path / "comfyout"; comfyout.mkdir()
    (comfyout / "out.png").write_bytes(b"PNGDATA")
    generate.run(_img_args(brand=None, seed=7, comfy_output_dir=str(comfyout)), tmp_path, _StubAp())
    dest = tmp_path / "outputs" / "images" / "txt2img_7.png"
    assert dest.exists() and dest.read_bytes() == b"PNGDATA"   # global outputs/, not a brand folder
    meta = json.loads(dest.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["brand"] is None
    assert meta["model"] == "qwen_image_2.1_int8_convrot.safetensors"  # brandless default model


def test_run_brandless_watermark_errors(tmp_path):
    # --watermark needs a brand (the logo lives in the brand folder) -> clean ap.error, no crash
    class _Err(Exception):
        pass
    class _Ap:
        def error(self, msg):
            raise _Err(msg)
    with pytest.raises(_Err):
        generate.run(_img_args(brand=None, watermark=True), tmp_path, _Ap())


def test_run_watermark_with_null_logo_default_errors(monkeypatch, tmp_path):
    # the exact state new-brand scaffolds: logos/ DIR exists but logo.default is null.
    # --watermark must produce the friendly ap.error, not a PermissionError on the directory.
    class _Err(Exception):
        pass
    class _Ap:
        def error(self, msg):
            raise _Err(msg)
    repo = _tmp_repo(tmp_path)
    (repo / "brands" / "b" / "logos").mkdir()          # dir present, no logo file, no logo.default
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    with pytest.raises(_Err, match="logo"):
        generate.run(_img_args(watermark=True), repo, _Ap())


def test_prepare_image_passes_source_canvas_for_product_and_relight(monkeypatch, tmp_path):
    # product/relight graphs render at the SOURCE image's native size (plain VAEEncode, no resize),
    # so the watermark canvas must be the probed source size — not the brand defaults.
    repo = _tmp_repo(tmp_path)
    pdir = repo / "brands" / "b" / "products"; pdir.mkdir()
    (pdir / "photo.png").write_bytes(b"fakepng")
    monkeypatch.setattr(generate, "_image_size", lambda p: (1920, 1080))
    m = generate.load_manifest(repo / "brands" / "b" / "brand.yaml")
    for mode in ("product", "relight"):
        fkw = generate._prepare_image(_img_args(mode=mode, asset="photo.png"),
                                      m, repo / "brands" / "b", FakeComfy(), _StubAp())
        assert fkw["canvas"] == (1920, 1080), mode


def test_check_repo_layout_errors_outside_a_checkout(tmp_path):
    # a non-editable install (pip install . / a wheel) has no workflows/templates next to the
    # package — fail fast with the editable-install hint instead of a template-not-found deep in
    # a filler
    class _Err(Exception):
        pass
    class _Ap:
        def error(self, msg):
            raise _Err(msg)
    with pytest.raises(_Err, match="pip install -e"):
        generate._check_repo_layout(tmp_path, _Ap())
    generate._check_repo_layout(ROOT, _Ap())   # a real checkout passes silently


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


def test_main_video_flags_default_to_none_so_brand_video_block_wins(monkeypatch):
    # the video subparser must NOT bake hard defaults (97/25/768/512/True): they'd shadow the
    # documented brand.yaml video: block, making it dead config
    captured = {}
    monkeypatch.setattr(generate, "run", lambda args, repo_root, ap: captured.update(vars(args)))
    monkeypatch.setattr(sys, "argv", ["generate.py", "video", "--brand", "b", "--subject", "s",
                                      "--from-image", "x.png"])
    generate.main()
    assert (captured["length"], captured["fps"], captured["width"], captured["height"],
            captured["audio"]) == (None, None, None, None, None)


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


def test_main_update_check_dispatches(monkeypatch, capsys):
    import scripts.brandkit.updates as u
    monkeypatch.setattr(generate, "ComfyClient", lambda url: object())
    monkeypatch.setattr(u, "check_updates", lambda client, root, latest_comfyui=None: [("ok", "x")])
    monkeypatch.setattr(u, "latest_comfyui_release", lambda: None)
    monkeypatch.setattr(sys, "argv", ["generate.py", "update-check", "--no-network"])
    generate.main()
    assert "update-check:" in capsys.readouterr().out


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


def test_main_replay_pins_the_recorded_model_and_passes_the_drift_flags(monkeypatch, tmp_path):
    data = {"schema": 2, "modality": "image", "mode": "txt2img", "brand": "b", "seed": 7,
            "model": "flux2_dev_fp8mixed.safetensors", "inputs": {"subject": "x"}, "comfy_url": "http://x"}
    sidecar = tmp_path / "s.json"
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    seen = []
    monkeypatch.setattr(generate, "run", lambda args, repo_root, ap: seen.append(
        (args.model, args.model_override, args.accept_drift, args.expect)))
    monkeypatch.setattr(sys, "argv", ["generate.py", "replay", str(sidecar)])
    generate.main()
    monkeypatch.setattr(sys, "argv", ["generate.py", "replay", str(sidecar), "--model", "q.safetensors",
                                      "--accept-drift"])
    generate.main()
    assert seen == [("flux2_dev_fp8mixed.safetensors", None, False, data),
                    ("q.safetensors", "q.safetensors", True, data)]


def _recorded_render(repo, monkeypatch):
    """Render once through run() and build the sidecar a real render would write."""
    from scripts.brandkit.sidecar import build_meta
    fake = FakeComfy()
    monkeypatch.setattr(generate, "ComfyClient", lambda url: fake)
    args = _img_args(seed=5)
    generate.run(args, repo, _StubAp())
    m = generate.load_manifest(repo / "brands" / "b" / "brand.yaml")
    meta = build_meta(modality="image", mode="txt2img", brand="b", seed=5,
                      model=generate._resolve_model_used(args, m), watermark=False, comfy_url="http://x",
                      wf=fake.wf, inputs=generate._resolve_sidecar_inputs(args, m), timestamp="t")
    return meta, fake


def test_replay_of_an_unchanged_brand_renders(monkeypatch, tmp_path):
    repo = _tmp_repo(tmp_path)
    meta, fake = _recorded_render(repo, monkeypatch)
    fake.wf = None
    generate.run(_img_args(seed=5, expect=meta, accept_drift=False, model_override=None), repo, _StubAp())
    assert fake.wf is not None


def test_replay_stops_when_the_brand_changed_since_the_render(monkeypatch, tmp_path, capsys):
    repo = _tmp_repo(tmp_path)
    meta, fake = _recorded_render(repo, monkeypatch)
    (repo / "brands" / "b" / "brand.yaml").write_text(
        'name: "B"\nstyle: "neon noir"\ndefaults: { model: z_image_turbo_nvfp4.safetensors, width: 640 }\n',
        encoding="utf-8")
    fake.wf = None
    with pytest.raises(SystemExit) as e:
        generate.run(_img_args(seed=5, expect=meta, accept_drift=False, model_override=None), repo, _StubAp())
    assert e.value.code == 1 and fake.wf is None          # nothing was queued
    err = capsys.readouterr().err
    assert "prompt changed" in err and "render settings changed" in err and "--accept-drift" in err
    generate.run(_img_args(seed=5, expect=meta, accept_drift=True, model_override=None), repo, _StubAp())
    assert fake.wf is not None                             # accepted: renders with today's brand


def test_run_reports_an_unrenderable_combination_as_a_cli_error(monkeypatch, tmp_path):
    # a filler's ValueError (e.g. --camera with --model ltx23) becomes a clean ap.error, not a traceback
    repo = _tmp_repo(tmp_path)
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)

    def cannot_render(*a, **k):
        raise ValueError("camera moves need Wan 2.2's Fun Camera model")
    monkeypatch.setitem(generate.FILLERS, "image", cannot_render)

    class _Ap:
        def error(self, msg):
            raise SystemExit(f"error: {msg}")
    with pytest.raises(SystemExit, match="Fun Camera"):
        generate.run(_img_args(seed=1), repo, _Ap())



# --- 2026-10 review: replay side effects ------------------------------------------------------------
class _CountingComfy(FakeComfy):
    def __init__(self, url=None):
        self.freed = 0
        self.wf = None

    def free(self, **k):
        self.freed += 1


def test_a_replay_routes_beside_the_original_instead_of_replacing_it(monkeypatch, tmp_path):
    repo = _tmp_repo(tmp_path)
    meta, fake = _recorded_render(repo, monkeypatch)
    out = repo / "brands" / "b" / "outputs" / "images"; out.mkdir(parents=True)
    (out / "b_txt2img_5.png").write_bytes(b"ORIGINAL"); (out / "b_txt2img_5.json").write_text("{}")
    comfyout = tmp_path / "comfyout"; comfyout.mkdir()
    (comfyout / "out.png").write_bytes(b"REPLAY")
    generate.run(_img_args(seed=5, comfy_output_dir=str(comfyout), expect=meta, accept_drift=False,
                           model_override=None), repo, _StubAp())
    assert (out / "b_txt2img_5.png").read_bytes() == b"ORIGINAL" and (out / "b_txt2img_5.json").read_text() == "{}"
    assert (out / "b_txt2img_5_replay.png").read_bytes() == b"REPLAY" and (out / "b_txt2img_5_replay.json").exists()


def test_a_replay_stopped_by_drift_frees_nothing(monkeypatch, tmp_path):
    repo = _tmp_repo(tmp_path)
    meta, _ = _recorded_render(repo, monkeypatch)
    fake = _CountingComfy()
    monkeypatch.setattr(generate, "ComfyClient", lambda url: fake)
    (repo / "brands" / "b" / "brand.yaml").write_text(
        'name: "B"\nstyle: "neon noir"\ndefaults: { model: z_image_turbo_nvfp4.safetensors }\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        generate.run(_img_args(seed=5, expect=meta, accept_drift=False, model_override=None, free_before=True),
                     repo, _StubAp())
    assert fake.freed == 0 and fake.wf is None


def test_a_replay_keeps_the_recorded_watermark_decision(monkeypatch, tmp_path):
    # the brand turned watermark.enabled_default on after the render: the replay must not stamp it
    repo = _tmp_repo(tmp_path)
    meta, fake = _recorded_render(repo, monkeypatch)
    (repo / "brands" / "b" / "brand.yaml").write_text(
        'name: "B"\ndefaults: { model: z_image_turbo_nvfp4.safetensors }\nwatermark: { enabled_default: true }\n',
        encoding="utf-8")
    fake.wf = None
    generate.run(_img_args(seed=5, expect=meta, accept_drift=False, model_override=None), repo, _StubAp())
    assert not any("watermark" in n.get("_meta", {}).get("title", "") for n in fake.wf.values())


def test_comfyui_rejecting_the_graph_is_one_clean_error(monkeypatch, tmp_path, capsys):
    repo = _tmp_repo(tmp_path)

    class _Rejects(FakeComfy):
        def queue_prompt(self, wf):
            raise RuntimeError("ComfyUI validation errors: {'3': 'Value not in list: unet_name'}")
    monkeypatch.setattr(generate, "ComfyClient", _Rejects)
    with pytest.raises(SystemExit) as e:
        generate.run(_img_args(seed=1), repo, _StubAp())
    assert e.value.code == 1 and "Value not in list" in capsys.readouterr().err


def test_main_replay_ignores_the_sidecars_comfy_url(monkeypatch, tmp_path, capsys):
    data = {"schema": 2, "modality": "image", "mode": "txt2img", "brand": "b", "seed": 7,
            "inputs": {"subject": "x"}, "comfy_url": "http://attacker.invalid:8000"}
    sidecar = tmp_path / "s.json"
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    seen = []
    monkeypatch.setattr(generate, "run", lambda args, repo_root, ap: seen.append(args.comfy_url))
    monkeypatch.setattr(sys, "argv", ["generate.py", "replay", str(sidecar)])
    generate.main()
    assert seen == ["http://127.0.0.1:8000"] and "attacker.invalid" in capsys.readouterr().err


def test_tracked_sidecars_hold_no_local_paths():
    # sidecars are committed for the example brand: none may carry a drive, a root path or a home folder
    import re
    bad = re.compile(r"^[A-Za-z]:[\\/]|^/(?!/)|[\\/](Users|home)[\\/]")
    hits = []

    def walk(v, where):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{where}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{where}[{i}]")
        elif isinstance(v, str) and bad.search(v):
            hits.append(f"{where}: {v}")
    for p in sorted((ROOT / "brands" / "example-brand" / "outputs").rglob("*.json")):
        walk(json.loads(p.read_text(encoding="utf-8")), p.name)
    assert hits == []



def test_free_before_unloads_comfyui_just_before_queueing(monkeypatch, tmp_path):
    # after the drift and flag checks, so a stopped replay or a bad flag frees nothing
    repo = _tmp_repo(tmp_path)
    order = []

    class _Ordered(FakeComfy):
        def free(self, **k):
            order.append("free")

        def queue_prompt(self, wf):
            order.append("queue")
            return super().queue_prompt(wf)
    monkeypatch.setattr(generate, "ComfyClient", _Ordered)
    generate.run(_img_args(seed=2, free_before=True), repo, _StubAp())
    assert order == ["free", "queue"]



def test_a_missing_reported_file_is_one_clean_error(monkeypatch, tmp_path, capsys):
    repo = _tmp_repo(tmp_path)
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    comfyout = tmp_path / "comfyout"; comfyout.mkdir()          # FakeComfy reports out.png; it isn't there
    with pytest.raises(SystemExit) as e:
        generate.run(_img_args(seed=4, comfy_output_dir=str(comfyout)), repo, _StubAp())
    assert e.value.code == 1 and "isn't in its output folder" in capsys.readouterr().err



# --- the 2026-10 review: one-line errors, flags a mode ignores, 3D formats ---------------------------------
class _ErrAp:
    def error(self, msg):
        raise SystemExit(f"ap.error: {msg}")


def _main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["generate.py", *argv])
    generate.main()


def test_an_unknown_brand_is_one_clean_error(monkeypatch, tmp_path):
    repo = _tmp_repo(tmp_path)
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    with pytest.raises(SystemExit, match="brand 'nope'"):
        generate.run(_img_args(brand="nope"), repo, _ErrAp())


def test_a_missing_watermark_logo_is_caught_before_anything_uploads(monkeypatch, tmp_path):
    repo = _tmp_repo(tmp_path)
    uploads = []

    class _C(FakeComfy):
        def upload_image(self, p):
            uploads.append(p)
            return "x"
    monkeypatch.setattr(generate, "ComfyClient", _C)
    (repo / "brands" / "b" / "products").mkdir()
    (repo / "brands" / "b" / "products" / "rover.png").write_bytes(b"x")
    with pytest.raises(SystemExit, match="watermark"):
        generate.run(_img_args(mode="product", asset="rover.png", watermark=True), repo, _ErrAp())
    assert uploads == []


def test_comfyui_timing_out_is_one_line(monkeypatch, capsys):
    monkeypatch.setattr(generate, "run", lambda *a: (_ for _ in ()).throw(TimeoutError("timed out")))
    with pytest.raises(SystemExit) as e:
        generate._run_comfy(_img_args(), Path("."), _StubAp())
    assert e.value.code == 1 and "stopped answering" in capsys.readouterr().err


def test_flags_the_mode_would_ignore_are_errors(monkeypatch, capsys):
    monkeypatch.setattr(generate, "_run_comfy", lambda *a: pytest.fail("must not render"))
    with pytest.raises(SystemExit):
        _main(monkeypatch, "image", "--subject", "x", "--upscale-model", "4x-UltraSharp.pth")
    assert "add --upscale" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _main(monkeypatch, "audio", "--mode", "sfx", "--subject", "whoosh", "--bpm", "120")
    assert "music settings" in capsys.readouterr().err


def test_replaying_a_file_that_is_not_a_sidecar_is_one_clean_error(monkeypatch, tmp_path, capsys):
    png = tmp_path / "r.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff")
    lst = tmp_path / "l.json"
    lst.write_text("[1, 2]", encoding="utf-8")
    for f in (png, lst, tmp_path / "missing.json"):
        with pytest.raises(SystemExit):
            _main(monkeypatch, "replay", str(f))
        assert "sidecar" in capsys.readouterr().err


def _repo_3d(tmp_path):
    repo = _tmp_repo(tmp_path)
    shutil.copytree(ROOT / "workflows" / "templates", repo / "workflows" / "templates", dirs_exist_ok=True)
    (repo / "brands" / "b" / "products").mkdir()
    (repo / "brands" / "b" / "products" / "rover.png").write_bytes(b"x")
    return repo


class _Comfy3D(FakeComfy):
    def output_files_by_node(self, pid):
        return [("999", "out.glb", "", "output")]


def _3d_args(**over):
    return _img_args(modality="3d", mode="image", from_image="rover.png", format="stl", **over)


def test_3d_stl_keeps_the_textured_glb_beside_it(monkeypatch, tmp_path):
    # TRELLIS.2 bakes its textures into the GLB, which converting to STL used to delete
    import scripts.brandkit.mesh as mesh
    repo = _repo_3d(tmp_path)
    monkeypatch.setattr(generate, "ComfyClient", _Comfy3D)

    def fake_convert(p, fmt):
        out = Path(p).with_suffix("." + fmt)
        out.write_bytes(b"stl")
        return out
    monkeypatch.setattr(mesh, "convert", fake_convert)
    comfyout = tmp_path / "comfyout"
    comfyout.mkdir()
    (comfyout / "out.glb").write_bytes(b"glb")
    generate.run(_3d_args(seed=5, comfy_output_dir=str(comfyout)), repo, _StubAp())
    d = repo / "brands" / "b" / "outputs" / "3d"
    assert (d / "b_image_5.glb").exists() and (d / "b_image_5.stl").exists() and (d / "b_image_5.json").exists()


def test_a_3d_file_that_will_not_convert_is_one_line(monkeypatch, tmp_path, capsys):
    import scripts.brandkit.mesh as mesh
    repo = _repo_3d(tmp_path)
    monkeypatch.setattr(generate, "ComfyClient", _Comfy3D)
    monkeypatch.setattr(mesh, "convert", lambda p, fmt: (_ for _ in ()).throw(ValueError("out.glb has 2 mesh parts")))
    comfyout = tmp_path / "comfyout"
    comfyout.mkdir()
    (comfyout / "out.glb").write_bytes(b"glb")
    with pytest.raises(SystemExit) as e:
        generate.run(_3d_args(seed=5, comfy_output_dir=str(comfyout)), repo, _StubAp())
    assert e.value.code == 1 and "the GLB is at" in capsys.readouterr().err


def test_3d_stl_without_an_output_dir_says_it_stays_a_glb(monkeypatch, tmp_path, capsys):
    repo = _repo_3d(tmp_path)
    monkeypatch.setattr(generate, "ComfyClient", _Comfy3D)
    generate.run(_3d_args(seed=5), repo, _StubAp())
    assert "ComfyUI's GLB only" in capsys.readouterr().err



# --- 2026-10 third review -----------------------------------------------------------------------------
def test_run_refuses_a_history_name_outside_the_output_dir(monkeypatch, tmp_path, capsys):
    repo = _tmp_repo(tmp_path)

    class Hostile(FakeComfy):
        def output_files_by_node(self, pid): return [("999", "secret.png", "../outside", "output")]
    monkeypatch.setattr(generate, "ComfyClient", Hostile)
    comfyout = tmp_path / "comfyout"; comfyout.mkdir()
    (tmp_path / "outside").mkdir(); (tmp_path / "outside" / "secret.png").write_bytes(b"S")
    with pytest.raises(SystemExit):
        generate.run(_img_args(seed=1, comfy_output_dir=str(comfyout)), repo, _StubAp())
    assert (tmp_path / "outside" / "secret.png").exists() and "outside" in capsys.readouterr().err


def test_run_applies_the_default_free_before(monkeypatch, tmp_path):
    repo, freed = _tmp_repo(tmp_path), []

    class C(FakeComfy):
        def free(self, **k): freed.append(1)
    monkeypatch.setattr(generate, "ComfyClient", C)
    monkeypatch.setattr(generate, "_default_free_before", lambda args, m: True)   # e.g. a FLUX.2 or video job
    generate.run(_img_args(seed=2, free_before=None), repo, _StubAp())
    assert freed == [1]


def test_a_foley_sidecar_records_the_timing_it_used(monkeypatch, tmp_path):
    # probed at 30 fps / 7.2 s; replayed where the probe can't run, the old record fell back to 25 fps / 5 s
    repo = _tmp_repo(tmp_path)
    shutil.copy(ROOT / "workflows" / "templates" / "brand-audio-foley.json",
                repo / "workflows" / "templates" / "brand-audio-foley.json")
    clip = repo / "brands" / "b" / "references" / "clip.mp4"
    clip.parent.mkdir(parents=True); clip.write_bytes(b"v")
    monkeypatch.setattr(generate, "_probe_video", lambda p: (30.0, 7.2, 640, 360))

    class C(FakeComfy):
        def upload_video(self, p): return "clip.mp4"
        def output_files_by_node(self, pid): return [("999", "out.mp4", "", "output")]
    monkeypatch.setattr(generate, "ComfyClient", C)
    comfyout = tmp_path / "comfyout"; comfyout.mkdir(); (comfyout / "out.mp4").write_bytes(b"A")
    generate.run(_img_args(modality="audio", mode="foley", subject="footsteps", from_video="clip.mp4", seed=3,
                           comfy_output_dir=str(comfyout)), repo, _StubAp())
    side = next((repo / "brands" / "b" / "outputs").rglob("b_foley_3.json"))
    inputs = json.loads(side.read_text(encoding="utf-8"))["inputs"]
    assert {k: inputs[k] for k in ("fps", "duration", "width", "height")} == \
        {"fps": 30.0, "duration": 7.2, "width": 640, "height": 360}


def test_replay_reads_a_sidecar_saved_with_a_bom_and_says_what_an_old_one_cannot_check(monkeypatch, tmp_path,
                                                                                       capsys):
    sidecar = tmp_path / "s.json"
    sidecar.write_text(json.dumps({"schema": 2, "modality": "image", "mode": "txt2img", "brand": "b", "seed": 7,
                                   "inputs": {"subject": "x"}}), encoding="utf-8-sig")   # PowerShell 5.1 adds a BOM
    captured = {}
    monkeypatch.setattr(generate, "run", lambda args, repo_root, ap: captured.update(seed=args.seed))
    monkeypatch.setattr(sys, "argv", ["generate.py", "replay", str(sidecar)])
    generate.main()
    assert captured == {"seed": 7} and "predates Chimera v0.6.0" in capsys.readouterr().err


def test_a_sidecar_missing_a_key_is_one_clean_error(monkeypatch, tmp_path, capsys):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"schema": 2, "modality": "image", "mode": "txt2img", "seed": 7}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["generate.py", "replay", str(p)])
    with pytest.raises(SystemExit) as e:
        generate.main()
    assert e.value.code == 2 and "cannot replay" in capsys.readouterr().err


def test_a_brand_that_is_not_a_folder_name_stops_before_anything_renders(monkeypatch, capsys):
    # route_output refused it after the render, leaving the file in ComfyUI's folder
    monkeypatch.setattr(generate, "ComfyClient", lambda *a, **k: pytest.fail("nothing may reach ComfyUI"))
    monkeypatch.setattr(sys, "argv", ["generate.py", "image", "--brand", ".hidden", "--subject", "x"])
    with pytest.raises(SystemExit) as e:
        generate.main()
    assert e.value.code == 2 and "isn't a brand folder name" in capsys.readouterr().err


def test_main_escapes_what_the_console_cannot_encode(monkeypatch):
    # a piped run on Windows (cp1252) crashed on a non-Latin brand name after the job was queued
    import io
    import scripts.brandkit.scaffold as scaffold
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(scaffold, "lint_brand", lambda root, brand: [("ok", f"{brand} \u2192 fine")])
    monkeypatch.setattr(sys, "argv", ["generate.py", "lint", "--brand", "\u6771\u4eac-brand"])
    with pytest.raises(SystemExit):
        generate.main()
    out.flush()
    assert b"\\u2192" in out.buffer.getvalue()


# --- 2026-10-25 review -------------------------------------------------------------------------------------
def test_new_brand_reports_a_folder_the_os_will_not_create_in_one_line(monkeypatch, capsys):
    # WinError 123 from copytree came out as a traceback
    import scripts.brandkit.scaffold as scaffold

    def refuse(root, name):
        raise OSError(22, "The filename, directory name, or volume label syntax is incorrect", f"brands/{name}")
    monkeypatch.setattr(scaffold, "new_brand", refuse)
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, "new-brand", "CON")
    assert e.value.code == 2 and "can't create brands/CON" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["--from-video", "clip.mp4"], ["--mode", "sfx", "--from-video", "clip.mp4"],
                                  ["--fps", "30"], ["--mode", "sfx", "--fps", "30"]])
def test_foley_flags_without_foley_are_errors(monkeypatch, capsys, argv):
    # `audio --from-video clip.mp4` without --mode foley rendered music from the foley text, without a word
    monkeypatch.setattr(generate, "_run_comfy", lambda *a: pytest.fail("must not render"))
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, "audio", "--subject", "footsteps", *argv)
    assert e.value.code == 2 and "--mode foley" in capsys.readouterr().err


def test_foley_takes_its_own_flags(monkeypatch):
    seen = []
    monkeypatch.setattr(generate, "_run_comfy", lambda args, root, ap: seen.append((args.from_video, args.fps)))
    _main(monkeypatch, "audio", "--mode", "foley", "--subject", "steps", "--from-video", "clip.mp4", "--fps", "30")
    assert seen == [("clip.mp4", 30.0)]


def _watermark_brand(repo, enabled_default):
    bdir = repo / "brands" / "b"
    (bdir / "logos").mkdir(exist_ok=True)
    (bdir / "logos" / "primary.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
                                                  + (64).to_bytes(4, "big") * 2 + b"\x08\x06\x00\x00\x00")
    (bdir / "brand.yaml").write_text(
        'name: "B"\ndefaults: { model: z_image_turbo_nvfp4.safetensors }\nlogo: { default: "logos/primary.png" }\n'
        f"watermark: {{ enabled_default: {'true' if enabled_default else 'false'} }}\n", encoding="utf-8")


def _stamped(wf):
    return any("watermark" in n.get("_meta", {}).get("title", "") for n in wf.values())


@pytest.mark.parametrize("flag, enabled_default, stamped", [
    (None, True, True), (False, True, False), (True, False, True), (None, False, False)])
def test_no_watermark_turns_a_brands_default_off_for_one_render(monkeypatch, tmp_path, flag, enabled_default,
                                                                 stamped):
    # a brand with watermark.enabled_default: true had no way to render one image without the logo
    repo = _tmp_repo(tmp_path)
    _watermark_brand(repo, enabled_default)
    fake = FakeComfy()
    monkeypatch.setattr(generate, "ComfyClient", lambda url: fake)
    generate.run(_img_args(seed=3, watermark=flag), repo, _StubAp())
    assert _stamped(fake.wf) is stamped


def test_the_sidecar_records_the_watermark_the_render_used(monkeypatch, tmp_path):
    repo = _tmp_repo(tmp_path)
    _watermark_brand(repo, True)
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    comfyout = tmp_path / "comfyout"; comfyout.mkdir()
    for flag, seed in ((None, 1), (False, 2)):
        (comfyout / "out.png").write_bytes(b"PNG")
        generate.run(_img_args(seed=seed, watermark=flag, comfy_output_dir=str(comfyout)), repo, _StubAp())
    out = repo / "brands" / "b" / "outputs" / "images"
    assert json.loads((out / "b_txt2img_1.json").read_text(encoding="utf-8"))["watermark"] is True
    assert json.loads((out / "b_txt2img_2.json").read_text(encoding="utf-8"))["watermark"] is False


@pytest.mark.parametrize("sub", ["image", "video", "audio", "3d"])
def test_every_subcommand_with_watermark_takes_no_watermark(monkeypatch, sub):
    extra = {"image": ["--subject", "x"], "video": ["--subject", "x", "--from-image", "r.png"],
             "audio": ["--subject", "x"], "3d": ["--from-image", "r.png"]}[sub]
    seen = []
    monkeypatch.setattr(generate, "_run_comfy", lambda args, root, ap: seen.append(args.watermark))
    for flag in ([], ["--watermark"], ["--no-watermark"]):
        _main(monkeypatch, sub, *extra, *flag)
    assert seen == [None, True, False]          # None: the brand's watermark.enabled_default decides


@pytest.mark.parametrize("over", [dict(modality="3d", mode="image", from_image="rover.png", format="glb"),
                                  dict(modality="audio", mode="music", subject="a sting")])
def test_watermark_says_when_the_render_has_no_frame_to_stamp(monkeypatch, tmp_path, capsys, over):
    # --watermark on a 3D mesh or a music track was dropped without a word
    repo = _repo_3d(tmp_path)
    _watermark_brand(repo, False)
    monkeypatch.setattr(generate, "ComfyClient", _Comfy3D)
    generate.run(_img_args(seed=4, watermark=True, **over), repo, _StubAp())
    err = capsys.readouterr().err
    assert "--watermark" in err and "ignored" in err


def _replay_args(meta):
    rargs = generate._args_from_sidecar(meta)
    rargs.expect, rargs.accept_drift, rargs.model_override = meta, False, None
    return rargs


def test_a_replay_says_when_an_input_file_changed_since_the_render(monkeypatch, tmp_path, capsys):
    # sidecars kept only the input's file name, so replay used whatever file had it and reported no drift
    import hashlib
    repo = _repo_3d(tmp_path)                        # every template; brands/b/products/rover.png holds b"x"
    _watermark_brand(repo, False)
    monkeypatch.setattr(generate, "ComfyClient", FakeComfy)
    comfyout = tmp_path / "comfyout"; comfyout.mkdir()
    (comfyout / "out.png").write_bytes(b"PNG")
    generate.run(_img_args(mode="product", asset="rover.png", seed=6, watermark=True,
                           comfy_output_dir=str(comfyout)), repo, _StubAp())
    meta = json.loads((repo / "brands" / "b" / "outputs" / "images" / "b_product_6.json").read_text(encoding="utf-8"))
    logo = repo / "brands" / "b" / "logos" / "primary.png"
    assert meta["provenance"]["input_hashes"] == {
        "asset": hashlib.sha256(b"x").hexdigest()[:16],
        "watermark_logo": hashlib.sha256(logo.read_bytes()).hexdigest()[:16]}
    generate.run(_replay_args(meta), repo, _StubAp())                       # the same files: it renders
    (repo / "brands" / "b" / "products" / "rover.png").write_bytes(b"another rover")
    with pytest.raises(SystemExit) as e:
        generate.run(_replay_args(meta), repo, _StubAp())
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "rover.png" in err and "content" in err and "--accept-drift" in err
    rargs = _replay_args(meta)
    rargs.accept_drift = True
    generate.run(rargs, repo, _StubAp())                                    # drift, not a refusal


def test_a_brand_default_watermark_on_music_says_nothing(monkeypatch, tmp_path, capsys):
    repo = _repo_3d(tmp_path)
    _watermark_brand(repo, True)
    monkeypatch.setattr(generate, "ComfyClient", _Comfy3D)
    generate.run(_img_args(seed=4, watermark=None, modality="audio", mode="music", subject="a sting"), repo, _StubAp())
    assert "--watermark" not in capsys.readouterr().err



# --- 2026-10-25 review: values ComfyUI refuses stop the CLI before it frees the GPU or uploads -------------
class _ApError(Exception):
    pass


class _RaisingAp:
    def error(self, msg):
        raise _ApError(msg)


class _NothingSent(FakeComfy):
    def free(self, **k):
        pytest.fail("nothing may be freed")

    def upload_video(self, p):
        pytest.fail("nothing may be uploaded")

    def queue_prompt(self, wf):
        pytest.fail("nothing may be queued")


def test_a_foley_clip_longer_than_hunyuan_renders_stops_before_the_upload(monkeypatch, tmp_path):
    repo = _tmp_repo(tmp_path)
    clip = repo / "brands" / "b" / "references" / "long.mp4"
    clip.parent.mkdir(parents=True); clip.write_bytes(b"v")
    monkeypatch.setattr(generate, "_probe_video", lambda p: (30.0, 75.0, 640, 360))
    monkeypatch.setattr(generate, "ComfyClient", _NothingSent)
    with pytest.raises(_ApError, match="1 to 60 s"):
        generate.run(_img_args(modality="audio", mode="foley", subject="rain", from_video="long.mp4", seed=3,
                               free_before=True), repo, _RaisingAp())


def test_a_key_ace_step_does_not_know_stops_before_the_gpu_is_freed(monkeypatch, tmp_path):
    repo = _tmp_repo(tmp_path)
    shutil.copy(ROOT / "workflows" / "templates" / "brand-audio-music.json",
                repo / "workflows" / "templates" / "brand-audio-music.json")
    monkeypatch.setattr(generate, "ComfyClient", _NothingSent)
    with pytest.raises(_ApError, match="--keyscale 'H minor'"):
        generate.run(_img_args(modality="audio", mode="music", subject="anthem", model="acestep", keyscale="H minor",
                               seed=3, free_before=True), repo, _RaisingAp())
