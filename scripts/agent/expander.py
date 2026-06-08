"""Expand a subject into a brand-aware (positive, negative) prompt pair.

The expander is the refinement hinge: prior unmet-criterion issues fed back from
the judge are appended to the positive so the next render corrects them.
"""
from __future__ import annotations
from abc import ABC, abstractmethod

from scripts.brandkit.prompt import build_prompt


class PromptExpander(ABC):
    """Turns a subject + manifest (+ optional prior issues) into prompts."""

    @abstractmethod
    def expand(self, subject, manifest, prior_issues=None) -> tuple[str, str]:
        """Return (positive, negative)."""
        raise NotImplementedError


class TemplatedExpander(PromptExpander):
    """Brand-aware expander built on build_prompt; appends refinement hints."""

    def expand(self, subject, manifest, prior_issues=None) -> tuple[str, str]:
        pos, neg = build_prompt(manifest, subject)
        if prior_issues:
            pos = pos + f". Emphasize and correct: {'; '.join(prior_issues)}"
        return pos, neg
