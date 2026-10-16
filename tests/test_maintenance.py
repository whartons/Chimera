"""The maintenance automation (docs/MAINTENANCE.md): the workflows, the checklist templates and Dependabot."""
from __future__ import annotations
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(path):
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    d["on"] = d.pop(True, d.get("on"))   # YAML 1.1 reads the bare key `on` as True
    return d


def test_every_action_is_pinned_by_commit_sha():
    # STACK.md §6: actions are pinned by SHA (Dependabot keeps the pins current); a tag can be moved
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        for ref in re.findall(r"uses:\s*(\S+)", wf.read_text(encoding="utf-8")):
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{wf.name}: {ref}"


def test_ci_keeps_the_required_check_names_and_runs_weekly():
    ci = _load(WORKFLOWS / "ci.yml")
    assert "schedule" in ci["on"] and "pull_request" in ci["on"]
    test = ci["jobs"]["test"]
    assert test["name"] == "${{ matrix.os }} · py${{ matrix.python-version }}"
    m = test["strategy"]["matrix"]
    # the base matrix gives the two required checks, 'ubuntu-latest · py3.12' and 'windows-latest · py3.12'
    assert m["os"] == ["ubuntu-latest", "windows-latest"] and m["python-version"] == ["3.12"]
    newer = {(i["os"], i["python-version"]) for i in m["include"]}
    assert newer == {("ubuntu-latest", "3.13"), ("ubuntu-latest", "3.14")}
    keep = next(s for s in test["steps"] if s.get("name") == "Keep the coverage report for the upload job")
    assert "matrix.python-version == '3.12'" in keep["if"]   # one coverage artifact, not one per Linux job


def test_the_checklist_workflow_has_a_template_for_each_kind():
    wf = _load(WORKFLOWS / "maintenance.yml")
    assert wf["on"]["schedule"] == [{"cron": "0 14 1 * *"}]
    kinds = wf["on"]["workflow_dispatch"]["inputs"]["kind"]["options"]
    assert kinds == ["monthly", "quarterly"]
    script = wf["jobs"]["open"]["steps"][-1]["run"]
    assert "01|04|07|10" in script                          # the quarterly review opens with January's window
    assert "${{" not in script                              # inputs come through the environment only
    for kind in kinds:
        assert f"{kind})" in script
        body = (ROOT / ".github" / "maintenance" / f"{kind}.md").read_text(encoding="utf-8")
        assert "{{repo}}" in body and "- [ ]" in body       # linked to the repo it runs in, and a checklist
        assert "docs/MAINTENANCE.md" in body


def test_dependabot_watches_pip_actions_and_pre_commit():
    d = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    eco = {u["package-ecosystem"]: u for u in d["updates"]}
    assert set(eco) == {"pip", "github-actions", "pre-commit"}
    assert "groups" in eco["github-actions"] and "groups" in eco["pre-commit"] and "groups" not in eco["pip"]


def test_the_maintenance_doc_covers_each_cadence():
    doc = (ROOT / "docs" / "MAINTENANCE.md").read_text(encoding="utf-8")
    for heading in ("## Weekly", "## Monthly", "## Quarterly", "## Event-driven"):
        assert heading in doc, heading
