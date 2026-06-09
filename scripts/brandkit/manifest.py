"""Load and validate a brand.yaml into a typed BrandManifest."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import sys
import yaml


class ManifestError(ValueError):
    pass


@dataclass
class Defaults:
    model: str = "flux2_dev_fp8mixed.safetensors"
    width: int = 1024
    height: int = 1024
    steps: int = 20
    guidance: float = 3.5
    upscale_model: Optional[str] = None   # image --upscale model; filler falls back to DEFAULT_UPSCALE_MODEL


@dataclass
class Logo:
    default: Optional[str] = None
    position: str = "bottom-right"
    scale: float = 0.18
    margin: float = 0.04


@dataclass
class Lora:
    file: Optional[str] = None
    strength: float = 0.8


@dataclass
class IpAdapter:
    enabled: bool = False
    weight: float = 0.5
    references: str = "references/"


@dataclass
class Watermark:
    enabled_default: bool = False
    position: str = "bottom-right"
    scale: float = 0.16
    margin: float = 0.04
    opacity: float = 1.0


@dataclass
class Video:
    model: Optional[str] = None
    width: int = 768
    height: int = 512
    length: int = 97
    fps: int = 25
    audio: bool = True
    upscale_model: Optional[str] = None   # video --upscale model; filler falls back to DEFAULT_VIDEO_UPSCALE_MODEL


@dataclass
class Audio:
    music_model: Optional[str] = None          # filler falls back to DEFAULT_MUSIC_MODEL
    music_tags: str = ""                        # brand sonic identity, prepended to the brief
    music_bpm: int = 100
    music_keyscale: str = "C minor"
    music_duration: float = 8.0
    foley: str = "hunyuan"                       # backend selector: "hunyuan" | "ltx-native"
    foley_model: Optional[str] = None            # filler falls back to DEFAULT_FOLEY_MODEL
    foley_negative: str = "music, speech, voice, singing, noisy, harsh"
    foley_cfg: float = 4.5
    foley_steps: int = 50


@dataclass
class Threed:
    model: Optional[str] = None        # filler falls back to DEFAULT_3D_MODEL
    format: str = "glb"
    octree: int = 256                  # VAEDecodeHunyuan3D octree_resolution (geometry detail)
    steps: int = 30
    cfg: float = 5.0


@dataclass
class BrandManifest:
    name: str
    style: str = ""
    palette: list = field(default_factory=list)
    prompt_prefix: str = ""
    prompt_suffix: str = ""
    negative: str = ""
    defaults: Defaults = field(default_factory=Defaults)
    logo: Logo = field(default_factory=Logo)
    lora: Lora = field(default_factory=Lora)
    ip_adapter: IpAdapter = field(default_factory=IpAdapter)
    watermark: Watermark = field(default_factory=Watermark)
    video: Video = field(default_factory=Video)
    audio: Audio = field(default_factory=Audio)
    threed: Threed = field(default_factory=Threed)
    root: Optional[Path] = None  # the brand folder, set by load_manifest


def _sub(cls, data, key):
    raw = data.get(key) or {}
    if not isinstance(raw, dict):
        raise ManifestError(f"'{key}' must be a mapping")
    allowed = {f for f in cls.__dataclass_fields__}
    unknown = [k for k in raw if k not in allowed]
    if unknown:
        print(f"warning: brand.yaml '{key}' has unknown key(s) {unknown} — ignored "
              f"(valid: {sorted(allowed)})", file=sys.stderr)
    return cls(**{k: v for k, v in raw.items() if k in allowed})


DEFAULT_BRANDLESS_MODEL = "z_image_turbo_nvfp4.safetensors"  # Z-Image is the documented default backend


def default_manifest() -> BrandManifest:
    """A neutral manifest for brandless generation: no style/palette/logo/negative, just the
    documented Z-Image default model. Lets `chimera image --subject "..."` run with no --brand
    (the output routes to the global outputs/ folder). `--model` still overrides it."""
    return BrandManifest(name="default", defaults=Defaults(model=DEFAULT_BRANDLESS_MODEL))


def load_manifest(path) -> BrandManifest:
    path = Path(path)
    if not path.exists():
        raise ManifestError(f"brand.yaml not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        # surface as ManifestError (a ValueError) so callers like lint/doctor degrade to a clean
        # message instead of crashing on a malformed brand.yaml
        raise ManifestError(f"brand.yaml is not valid YAML: {e}")
    if not isinstance(data, dict):
        raise ManifestError("brand.yaml must be a mapping at the top level")
    name = data.get("name")
    if not name or not str(name).strip():
        raise ManifestError("brand.yaml requires a non-empty 'name'")
    return BrandManifest(
        name=str(name),
        style=str(data.get("style", "") or ""),
        palette=list(data.get("palette", []) or []),
        prompt_prefix=str(data.get("prompt_prefix", "") or ""),
        prompt_suffix=str(data.get("prompt_suffix", "") or ""),
        negative=str(data.get("negative", "") or ""),
        defaults=_sub(Defaults, data, "defaults"),
        logo=_sub(Logo, data, "logo"),
        lora=_sub(Lora, data, "lora"),
        ip_adapter=_sub(IpAdapter, data, "ip_adapter"),
        watermark=_sub(Watermark, data, "watermark"),
        video=_sub(Video, data, "video"),
        audio=_sub(Audio, data, "audio"),
        threed=_sub(Threed, data, "threed"),
        root=path.parent,
    )
