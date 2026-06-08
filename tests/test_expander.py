from __future__ import annotations
import pytest
from scripts.brandkit.manifest import BrandManifest
from scripts.agent.expander import PromptExpander, TemplatedExpander


def _m() -> BrandManifest:
    return BrandManifest(
        name="ACME",
        style="rugged tactical",
        palette=["#1c1f22", "#c8442e"],
        negative="blurry, cartoonish",
    )


def test_abc_cannot_instantiate():
    with pytest.raises(TypeError):
        PromptExpander()  # abstract


def test_templated_expand_injects_subject_and_brand_style():
    e = TemplatedExpander()
    pos, neg = e.expand("rover", _m())
    assert "rover" in pos                       # subject
    assert "rugged tactical" in pos             # brand style injected by build_prompt
    assert neg == "blurry, cartoonish"          # brand negative


def test_templated_expand_appends_prior_issues():
    e = TemplatedExpander()
    pos, neg = e.expand("rover", _m(), prior_issues=["palette not present", "too soft"])
    assert "rover" in pos
    assert "Emphasize and correct" in pos
    assert "palette not present" in pos
    assert "too soft" in pos
    assert neg == "blurry, cartoonish"          # negative unchanged by refinement


def test_templated_expand_empty_prior_issues_no_correction_clause():
    e = TemplatedExpander()
    pos, _ = e.expand("rover", _m(), prior_issues=[])
    assert "Emphasize and correct" not in pos
