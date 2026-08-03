"""Tests for the trainer CLI seam (scripts/train_brand_lora.py) — previously zero coverage.
The pure logic (scan_dataset/build_config) is covered in test_training.py; these pin the CLI
contract: dry-run writes the config, --run invokes ONLY the requested backend (no silent
substitution), and backend failures exit cleanly."""
from __future__ import annotations
import json
import subprocess
import pytest
from scripts import train_brand_lora as T


def _tmp_brand(tmp_path):
    b = tmp_path / "brands" / "b"
    (b / "training").mkdir(parents=True)
    (b / "brand.yaml").write_text('name: "B"\n', encoding="utf-8")
    (b / "training" / "img.png").write_bytes(b"x")
    (b / "training" / "img.txt").write_text("a caption", encoding="utf-8")
    return tmp_path


def test_dry_run_writes_config_and_trains_nothing(tmp_path, capsys, monkeypatch):
    repo = _tmp_brand(tmp_path)
    monkeypatch.setattr(T.subprocess, "run",
                        lambda *a, **k: pytest.fail("dry-run must not invoke a backend"))
    T.main(["--brand", "b"], repo_root=repo)
    cfg = json.loads((repo / "brands" / "b" / "lora" / "b-train-config.json")
                     .read_text(encoding="utf-8"))
    assert cfg["backend"] == "ai-toolkit" and cfg["steps"] == 1000
    assert "dry-run" in capsys.readouterr().out


def test_run_errors_when_requested_backend_missing(tmp_path, monkeypatch, capsys):
    # kohya requested but only ai-toolkit installed: a config built for kohya must NOT be fed
    # to ai-toolkit — that silent substitution was the bug
    repo = _tmp_brand(tmp_path)
    monkeypatch.setattr(T.shutil, "which",
                        lambda n: "C:/tools/ai-toolkit.exe" if n == "ai-toolkit" else None)
    monkeypatch.setattr(T.subprocess, "run",
                        lambda *a, **k: pytest.fail("must not invoke a substitute backend"))
    with pytest.raises(SystemExit) as e:
        T.main(["--brand", "b", "--backend", "kohya", "--run"], repo_root=repo)
    assert e.value.code == 3
    assert "kohya" in capsys.readouterr().err


def test_run_invokes_requested_backend(tmp_path, monkeypatch):
    repo = _tmp_brand(tmp_path)
    calls = []
    monkeypatch.setattr(T.shutil, "which",
                        lambda n: "C:/tools/kohya.exe" if n == "kohya" else None)
    monkeypatch.setattr(T.subprocess, "run", lambda argv, **k: calls.append(argv))
    T.main(["--brand", "b", "--backend", "kohya", "--run"], repo_root=repo)
    assert calls and calls[0][0] == "C:/tools/kohya.exe"


def test_run_backend_failure_exits_cleanly(tmp_path, monkeypatch, capsys):
    repo = _tmp_brand(tmp_path)
    monkeypatch.setattr(T.shutil, "which", lambda n: "C:/tools/ai-toolkit.exe")
    def boom(argv, **k):
        raise subprocess.CalledProcessError(2, argv)
    monkeypatch.setattr(T.subprocess, "run", boom)
    with pytest.raises(SystemExit) as e:
        T.main(["--brand", "b", "--run"], repo_root=repo)
    assert e.value.code == 4
    assert "exited" in capsys.readouterr().err
