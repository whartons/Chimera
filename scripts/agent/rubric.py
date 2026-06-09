"""Derive a judge-facing rubric (checklist) from a brand manifest + subject."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Rubric:
    """A scorable checklist a VLM judge marks met/not-met, then scores 0-1."""
    subject: str
    criteria: list = field(default_factory=list)

    def as_prompt(self) -> str:
        """Render a numbered checklist instructing the judge how to respond."""
        lines = [
            f"Evaluate the image against this rubric for: {self.subject}.",
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


def build_rubric(manifest, subject: str) -> Rubric:
    """Compose criteria from the subject + whichever brand traits are present."""
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
