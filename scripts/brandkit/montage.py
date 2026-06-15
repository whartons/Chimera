"""Host-side contact sheet: tile N render stills into one PNG for the VLM judge to read in a
single pass (so it sees front/side/back, not just one hero angle). Pillow-only and imported
lazily, so modules that reference montage import fine without the optional [images] extra."""
from __future__ import annotations
from pathlib import Path


def contact_sheet(paths, out_path, *, cols=2) -> Path:
    """Tile `paths` into a `cols`-wide grid PNG at `out_path`; return the path. Cells are sized
    to the largest input; shorter rows are left blank on a dark background."""
    # Validate args before touching the optional dep, so a misuse fails as ValueError
    # regardless of whether Pillow is installed.
    paths = [Path(p) for p in paths]
    if not paths:
        raise ValueError("contact_sheet needs at least one image")
    try:
        from PIL import Image
    except ImportError as e:  # optional dep — fail loudly only when actually called
        raise RuntimeError("contact_sheet needs Pillow (pip install -e '.[images]')") from e
    imgs = []
    try:
        for p in paths:  # incremental so finally closes any already-opened handles on a mid-list error
            imgs.append(Image.open(str(p)).convert("RGB"))
        cw = max(i.width for i in imgs)
        ch = max(i.height for i in imgs)
        rows = (len(imgs) + cols - 1) // cols
        sheet = Image.new("RGB", (cw * cols, ch * rows), (20, 20, 24))
        for idx, im in enumerate(imgs):
            r, c = divmod(idx, cols)
            sheet.paste(im, (c * cw, r * ch))
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(str(out_path))
        return out_path
    finally:
        for im in imgs:
            im.close()
