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


def test_build_rubric_3d_form_criteria_and_noun():
    from scripts.agent.rubric import build_rubric
    from scripts.brandkit.manifest import default_manifest
    r = build_rubric(default_manifest(), "an armored knight", modality="3d")
    assert r.noun == "3D render"
    joined = " ".join(r.criteria).lower()
    assert "clearly depicts: an armored knight" in joined
    assert "proportions and silhouette" in joined
    assert "no missing, broken, or fused" in joined
    assert "holes, spikes, or floating" in joined
    # grey clay: no color/palette criterion for 3d
    assert "palette" not in joined


def test_3d_rubric_prompt_keeps_verdict_tokens_and_3d_noun():
    from scripts.agent.rubric import build_rubric
    from scripts.brandkit.manifest import default_manifest
    prompt = build_rubric(default_manifest(), "a rover", modality="3d").as_prompt()
    assert "Evaluate the 3D render against this rubric" in prompt
    assert "PASS" in prompt and "FAIL" in prompt and "FIX:" in prompt


def test_image_rubric_unchanged_default():
    from scripts.agent.rubric import build_rubric
    from scripts.brandkit.manifest import default_manifest
    r = build_rubric(default_manifest(), "a rover")
    assert r.noun == "image"
    assert r.as_prompt().startswith("Evaluate the image against this rubric")


def test_3d_rubric_includes_style_and_negative_when_present():
    r = build_rubric(_m(), "a knight", modality="3d")
    joined = " ".join(r.criteria).lower()
    assert "form's style matches: rugged tactical" in joined
    assert "avoids these traits: blurry, cartoonish" in joined
    assert "palette" not in joined  # still no color criterion for grey clay


def test_unknown_modality_raises():
    import pytest
    with pytest.raises(ValueError, match="modality"):
        build_rubric(_m(), "a knight", modality="3D")  # capital D is not a valid modality


def test_3d_textured_rubric_adds_satisfiable_color_criteria():
    r = build_rubric(_m(), "a knight", modality="3d", textured=True)
    assert r.noun == "textured 3D render"
    joined = " ".join(r.criteria).lower()
    assert "proportions and silhouette" in joined
    assert "colored consistent with" in joined
    assert "a plain or palette-filled back/underside is acceptable" in joined
    assert "brand palette" in joined


def test_3d_textured_prompt_keeps_tokens():
    p = build_rubric(_m(), "a rover", modality="3d", textured=True).as_prompt()
    assert "Evaluate the textured 3D render against this rubric" in p
    assert "PASS" in p and "FAIL" in p and "FIX:" in p


def test_3d_untextured_unchanged_when_textured_false():
    r = build_rubric(_m(), "a rover", modality="3d")
    assert r.noun == "3D render"
    joined = " ".join(r.criteria).lower()
    assert "back/underside is acceptable" not in joined
    assert "brand palette" not in joined


def test_3d_textured_brandless_has_color_but_no_palette_criterion():
    from scripts.brandkit.manifest import BrandManifest
    r = build_rubric(BrandManifest(name="Bare"), "a fox", modality="3d", textured=True)
    joined = " ".join(r.criteria).lower()
    assert "colored consistent with" in joined   # color criterion still added
    assert "brand palette" not in joined          # but no palette criterion (empty palette)
    assert "avoids these traits" not in joined    # and no negative criterion


def test_3d_rubric_prompt_explains_contact_sheet_layout():
    """The 3D/CAD judge is shown a multi-view CONTACT SHEET (4 orbit stills in a grid, see
    render_generate). Without telling the VLM the panels are ONE model from N angles, it miscounts
    them as N separate objects and fails 'a single ...'. The prompt MUST explain the layout."""
    from scripts.brandkit.manifest import default_manifest
    p = build_rubric(default_manifest(), "a single cylinder", modality="3d").as_prompt().lower()
    assert "contact sheet" in p                       # names the layout
    assert "same" in p                                # ...same model
    assert "separate" in p or "multiple" in p         # ...NOT separate/multiple objects
    # still a numbered checklist with verdict tokens
    assert "evaluate the 3d render" in p and "pass" in p and "fail" in p


def test_3d_textured_prompt_also_explains_contact_sheet():
    from scripts.brandkit.manifest import default_manifest
    p = build_rubric(default_manifest(), "a rover", modality="3d", textured=True).as_prompt().lower()
    assert "contact sheet" in p


def test_image_rubric_has_no_contact_sheet_preamble():
    """The 2D image path judges a SINGLE image, not a contact sheet — adding the preamble there would
    confuse the judge. Only the multi-view 3D path gets it."""
    from scripts.brandkit.manifest import default_manifest
    p = build_rubric(default_manifest(), "a rover").as_prompt().lower()
    assert "contact sheet" not in p
