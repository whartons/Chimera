"""Brand Kits — brand-aware ComfyUI generation."""
from pathlib import Path as _Path


def _version():
    """The checkout's pyproject version (Chimera runs from a checkout), else the installed metadata."""
    try:
        import tomllib
        pyproject = _Path(__file__).resolve().parents[2] / "pyproject.toml"
        return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, ValueError, ImportError):
        pass
    try:
        from importlib.metadata import version
        return version("chimera")
    except Exception:   # noqa: BLE001 - not installed either
        return "unknown"


__version__ = _version()   # it read "0.1.0" through every release until 0.6.0
