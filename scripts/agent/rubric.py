"""Derive a judge-facing rubric (checklist) from a brand manifest + subject."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Rubric:
    """A scorable checklist a VLM judge marks met/not-met, then scores 0-1."""
    subject: str
    criteria: list = field(default_factory=list)
    noun: str = "image"  # what the judge is looking at: "image" or "3D render"

    def as_prompt(self) -> str:
        """Render a numbered checklist instructing the judge how to respond."""
        lines = [
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


def build_rubric(manifest, subject: str, *, modality: str = "image") -> Rubric:
    """Compose criteria from the subject + whichever brand traits are present.

    modality='3d' scores FORM on a grey clay render (Hunyuan3D output is untextured): no color/
    palette criteria; the noun becomes '3D render'. modality='image' is the original 2D path."""
    if modality not in ("image", "3d"):
        raise ValueError(f"modality must be 'image' or '3d', got {modality!r}")
    if modality == "3d":
        # No 'high quality (sharp, well-composed)' criterion: an untextured clay render's sharpness
        # is a renderer/camera property, not a fact about the model's geometry.
        criteria = [
            f"The 3D render clearly depicts: {subject}.",
            f"Proportions and silhouette are correct for {subject} "
            "(no stretched, melted, or collapsed regions).",
            "The model is complete — no missing, broken, or fused limbs/parts.",
            "The surface is clean — no holes, spikes, or floating disconnected bits.",
        ]
        if manifest.style:
            criteria.append(f"The form's style matches: {manifest.style}.")
        if manifest.negative:
            criteria.append(f"The 3D render avoids these traits: {manifest.negative}.")
        return Rubric(subject=subject, criteria=criteria, noun="3D render")

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
