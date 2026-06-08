"""Pure trainer logic: scan a brand's training set + generate a backend config.
The actual training run is delegated to a pluggable backend (see train_brand_lora.py).
"""
from __future__ import annotations
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


class TrainingError(RuntimeError):
    pass


def scan_dataset(training_dir) -> list[tuple[Path, str]]:
    training_dir = Path(training_dir)
    imgs = sorted(p for p in training_dir.glob("*") if p.suffix.lower() in IMAGE_EXTS)
    if not imgs:
        raise TrainingError(f"no training images in {training_dir} (add images + matching .txt captions)")
    pairs = []
    for img in imgs:
        cap = img.with_suffix(".txt")
        pairs.append((img, cap.read_text(encoding="utf-8").strip() if cap.exists() else ""))
    return pairs


def build_config(brand: str, manifest, steps: int, backend: str) -> dict:
    # Paths are repo-relative (brands/<brand>/...) so a generated config is portable and
    # contains no machine-specific absolute paths — safe to commit as an example and to
    # share. Resolve them from the repo root at run time.
    return {
        "backend": backend,
        "brand": brand,
        "base_model": manifest.defaults.model,
        "dataset_dir": f"brands/{brand}/training",
        "output_dir": f"brands/{brand}/lora",
        "output_name": f"{brand}-v1",
        "steps": steps,
        "resolution": [manifest.defaults.width, manifest.defaults.height],
        "trigger_word": brand.replace("-", " "),
    }
