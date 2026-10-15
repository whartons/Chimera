"""Derive a judge-facing rubric (checklist) from a brand manifest + subject."""
from __future__ import annotations
from dataclasses import dataclass, field


# The 3D/CAD judge is shown a multi-view CONTACT SHEET (render_generate montages 4 orbit stills into
# a 2x2 grid). A VLM that isn't told the layout reads the N panels as N separate objects and fails
# 'a single ...' on every criterion (verified: qwen3-vl scored a perfect cylinder 0.0 "four cylinders,
# not one"; the same image with this preamble scored 1.0). Count-agnostic so it survives a view-count
# change. Prepended to the 3D rubric prompt only — the 2D image path judges a single image.
CONTACT_SHEET_PREAMBLE = (
    "IMPORTANT: The image is a CONTACT SHEET — ONE single 3D model shown from multiple orbit "
    "(turntable) camera angles arranged in a grid. Every panel depicts the SAME one model from a "
    "different viewpoint; the panels are NOT multiple or separate objects. Count and judge only the "
    "single model shown."
)


@dataclass
class Rubric:
    """A scorable checklist a VLM judge marks met/not-met, then scores 0-1."""
    subject: str
    criteria: list = field(default_factory=list)
    noun: str = "image"  # what the judge is looking at: "image" or "3D render"
    preamble: str = ""    # optional context prepended before the checklist (e.g. contact-sheet layout)

    def as_prompt(self) -> str:
        """Render a numbered checklist instructing the judge how to respond."""
        lines = []
        if self.preamble:
            lines.append(self.preamble + "\n")
        lines += [
            f"Evaluate the {self.noun} against this rubric for: {self.subject}.",
            "For each numbered criterion, state MET or NOT-MET with a one-line reason. For any "
            "NOT-MET criterion, append on the SAME line a concrete fix in this exact format: "
            "'FIX: add <comma-separated visual elements to include>; avoid <comma-separated traits "
            "to remove>'. A fix must satisfy every criterion at once: never add a trait another "
            "criterion says to avoid, and never avoid a trait another criterion requires.",
        ]
        for i, c in enumerate(self.criteria, 1):
            lines.append(f"{i}. {c}")
        lines.append(
            "Be strict: mark a criterion NOT-MET unless it is clearly and fully satisfied. "
            "Then, on its own line, give the overall verdict: PASS only if EVERY criterion above is "
            "MET, otherwise FAIL. On a separate line give a score from 0 to 1 (e.g. 'score: 0.82')."
        )
        return "\n".join(lines)


_HUES = ((15, "red"), (40, "orange"), (65, "yellow"), (165, "green"), (200, "teal"), (255, "blue"),
         (290, "purple"), (345, "pink"), (360, "red"))


def color_words(hex_color) -> str:
    """'#c8442e' -> 'red (#c8442e)': a plain color name for the judge. A small VLM can't read hex codes
    as colors; on a correct near-black/slate/steel render it failed the palette criterion as
    'monochromatic, not the brand palette' (2026-10). Non-hex entries pass through unchanged."""
    import colorsys
    import re
    h = str(hex_color).strip()
    if not re.fullmatch(r"#?[0-9a-fA-F]{6}", h):
        return h
    r, g, b = (int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    if sat < 0.2 or light < 0.12:
        name = ("near-black" if light < 0.15 else "dark grey" if light < 0.35 else "grey" if light < 0.65
                else "light grey" if light < 0.9 else "near-white")
    else:
        base = next(n for limit, n in _HUES if hue * 360 < limit)
        name = ("dark " if light < 0.3 else "light " if light > 0.75 else "") + base
    return f"{name} ({h})"


def _palette_criterion(manifest, lead):
    return (f"{lead} " + ", ".join(color_words(c) for c in manifest.palette)
            + "; a scheme built from only some of these colors is on-palette.")


def _subject_criterion(noun, subject, manifest) -> str:
    """'Clearly depicts' the subject. With brand traits it judges the object itself and lets the brand
    win: a subject such as 'a glossy candy-red toy rover' under a gunmetal brand otherwise has the
    judge demand the candy colors here and forbid them in the brand criteria, and its FIX directives
    invert the correction (2026-10, Qwen3-VL-8B)."""
    base = f"The {noun} clearly depicts: {subject}."
    if not (manifest.style or manifest.palette or manifest.negative):
        return base
    return (base + " Judge the object itself (what it is, its parts and their count); where the subject's "
            "styling words conflict with the brand criteria below, the brand wins.")


def build_rubric(manifest, subject: str, *, modality: str = "image", textured: bool = False) -> Rubric:
    """Compose criteria from the subject + whichever brand traits are present.

    modality='3d' scores FORM on a grey clay render (Hunyuan3D output is untextured): no color/
    palette criteria; the noun becomes '3D render'. modality='3d', textured=True (Phase 4a) ADDS
    color criteria worded to accept a plain/palette-filled back (the front bake is faithful, the
    back is a flat fill) so the loop never chases back texture it cannot produce. `textured` has no
    effect unless modality='3d'. modality='image' is the original 2D path."""
    if modality not in ("image", "3d"):
        raise ValueError(f"modality must be 'image' or '3d', got {modality!r}")
    if modality == "3d":
        noun = "textured 3D render" if textured else "3D render"
        # No 'high quality (sharp, well-composed)' criterion: an untextured clay render's sharpness
        # is a renderer/camera property, not a fact about the model's geometry.
        criteria = [
            _subject_criterion(noun, subject, manifest),
            f"Proportions and silhouette are correct for {subject} "
            "(no stretched, melted, or collapsed regions).",
            "The model is complete — no missing, broken, or fused limbs/parts.",
            "The surface is clean — no holes, spikes, or floating disconnected bits.",
        ]
        if textured:
            criteria.append(
                f"The model's front and visible surfaces are colored consistent with {subject} — "
                "a plain or palette-filled back/underside is acceptable."
            )
            if manifest.palette:
                criteria.append(_palette_criterion(manifest, "The coloring stays within the brand palette:"))
        # style/negative apply to both textured and untextured 3d — phrased via `noun` (DRY)
        if manifest.style:
            criteria.append(f"The form's style matches: {manifest.style}.")
        if manifest.negative:
            criteria.append(f"The {noun} avoids these traits: {manifest.negative}.")
        # the 3D path judges a multi-view contact sheet — tell the judge so it doesn't read the
        # N orbit panels as N separate objects (see CONTACT_SHEET_PREAMBLE).
        return Rubric(subject=subject, criteria=criteria, noun=noun, preamble=CONTACT_SHEET_PREAMBLE)

    criteria = [_subject_criterion("image", subject, manifest)]
    if manifest.style:
        criteria.append(f"The visual style matches: {manifest.style}.")
    if manifest.palette:
        criteria.append(_palette_criterion(manifest, "The image's colors stay within the brand palette:"))
    criteria.append(
        "The image is high quality (sharp, well-composed, no obvious artifacts)."
    )
    if manifest.negative:
        criteria.append(f"The image avoids these traits: {manifest.negative}.")
    return Rubric(subject=subject, criteria=criteria)
