#!/usr/bin/env python3
"""Brand LoRA trainer scaffold. Validates a brand's training/ set, generates a backend
config, and (with --run) invokes a pluggable FLUX LoRA backend. Defaults to --dry-run,
which writes the config + a captions/dataset report WITHOUT training, so the plumbing is
verifiable today even where FLUX.2 training tooling isn't ready.

Usage:
  python scripts/train_brand_lora.py --brand example-brand [--steps 1000] \
      [--backend ai-toolkit] [--run]
"""
import argparse, json, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.brandkit.manifest import load_manifest
from scripts.brandkit.training import scan_dataset, build_config, TrainingError


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("--backend", default="ai-toolkit")
    ap.add_argument("--run", action="store_true", help="actually invoke the backend (needs it installed)")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    brand_dir = repo_root / "brands" / args.brand
    m = load_manifest(brand_dir / "brand.yaml")
    try:
        pairs = scan_dataset(brand_dir / "training")
    except TrainingError as e:
        print(f"ERROR: {e}", file=sys.stderr); sys.exit(2)

    cfg = build_config(args.brand, m, args.steps, args.backend)
    cfg_path = brand_dir / "lora" / f"{args.brand}-train-config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    captioned = sum(1 for _, c in pairs if c)
    print(f"dataset: {len(pairs)} images ({captioned} captioned) -> config {cfg_path}")

    if not args.run:
        print("dry-run: config written, no training performed. Re-run with --run once a "
              "FLUX LoRA backend is installed.")
        return

    backend_cli = shutil.which(args.backend) or shutil.which("ai-toolkit")
    if not backend_cli:
        print(f"ERROR: backend '{args.backend}' not found on PATH. Install it or use --dry-run.",
              file=sys.stderr); sys.exit(3)
    # Backend invocation is intentionally a single seam — adjust args to the chosen tool.
    print(f"invoking backend: {backend_cli} (config {cfg_path})")
    subprocess.run([backend_cli, "run", str(cfg_path)], check=True)
    print(f"if training produced {cfg['output_name']}.safetensors in {cfg['output_dir']}, "
          f"set lora.file in brand.yaml to use it.")


if __name__ == "__main__":
    main()
