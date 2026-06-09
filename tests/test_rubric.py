from __future__ import annotations
from scripts.brandkit.manifest import BrandManifest
from scripts.agent.rubric import Rubric, build_rubric


def _m() -> BrandManifest:
    return BrandManifest(
        name="ACME",
        style="rugged tactical",
        palette=["#1c1f22", "#c8442e"],
        negative="blurry, cartoonish",
    )


def test_build_rubric_covers_subject_style_palette_quality_negative():
    r = build_rubric(_m(), "rover")
    assert isinstance(r, Rubric)
    assert r.subject == "rover"
    joined = " ".join(r.criteria).lower()
    assert "rover" in joined                       # subject
    assert "rugged tactical" in joined             # style text
    assert "palette" in joined or "#1c1f22" in joined  # palette criterion
    assert "high quality" in joined                # quality criterion
    assert "blurry, cartoonish" in joined          # negative traits


def test_as_prompt_is_numbered_checklist_with_pass_fail_and_score():
    r = build_rubric(_m(), "rover")
    p = r.as_prompt()
    assert "1." in p and "2." in p                 # numbered checklist
    assert "rover" in p
    assert "PASS" in p and "FAIL" in p
    assert "score" in p.lower()
    # strict pass: the judge must require EVERY criterion met (overall PASS only if all MET),
    # so the loop actually enforces the rubric instead of a lenient holistic pass
    assert "every criterion" in p.lower() and "pass only" in p.lower()
    # the judge is asked for a structured, actionable fix on NOT-MET criteria (add/avoid), which the
    # expander applies to the next render
    assert "fix:" in p.lower() and "add" in p.lower() and "avoid" in p.lower()


def test_rubric_defaults_do_not_share_list():
    a, b = Rubric(subject="x"), Rubric(subject="y")
    a.criteria.append("mutated")
    assert b.criteria == []                         # no shared mutable default


def test_build_rubric_omits_absent_style_and_palette_and_negative():
    m = BrandManifest(name="Bare")
    r = build_rubric(m, "a fox")
    joined = " ".join(r.criteria).lower()
    assert "a fox" in joined
    assert "high quality" in joined
    assert "palette" not in joined
    assert "style matches" not in joined
    assert "avoids these traits" not in joined
