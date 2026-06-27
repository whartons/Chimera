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
            "to remove>'.",
        ]
        for i, c in enumerate(self.criteria, 1):
            lines.append(f"{i}. {c}")
        lines.append(
            "Be strict: mark a criterion NOT-MET unless it is clearly and fully satisfied. "
            "Then, on its own line, give the overall verdict: PASS only if EVERY criterion above is "
            "MET, otherwise FAIL. On a separate line give a score from 0 to 1 (e.g. 'score: 0.82')."
        )
        return "\n".join(lines)


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
            f"The {noun} clearly depicts: {subject}.",
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
                criteria.append(
                    "The coloring uses the brand palette: "
                    + ", ".join(str(c) for c in manifest.palette) + "."
                )
        # style/negative apply to both textured and untextured 3d — phrased via `noun` (DRY)
        if manifest.style:
            criteria.append(f"The form's style matches: {manifest.style}.")
        if manifest.negative:
            criteria.append(f"The {noun} avoids these traits: {manifest.negative}.")
        # the 3D path judges a multi-view contact sheet — tell the judge so it doesn't read the
        # N orbit panels as N separate objects (see CONTACT_SHEET_PREAMBLE).
        return Rubric(subject=subject, criteria=criteria, noun=noun, preamble=CONTACT_SHEET_PREAMBLE)

    criteria = [f"The image clearly depicts: {subject}."]
    if manifest.style:
        criteria.append(f"The visual style matches: {manifest.style}.")
    if manifest.palette:
        criteria.append(
            "The brand color palette is present/dominant: "
            + ", ".join(str(c) for c in manifest.palette)
            + "."
        )
    criteria.append(
        "The image is high quality (sharp, well-composed, no obvious artifacts)."
    )
    if manifest.negative:
        criteria.append(f"The image avoids these traits: {manifest.negative}.")
    return Rubric(subject=subject, criteria=criteria)
