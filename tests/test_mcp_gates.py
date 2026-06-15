import json, pathlib

SETTINGS = pathlib.Path(__file__).resolve().parents[1] / ".claude" / "settings.json"

# Tier-1 RCE / code-exec DCC tools that MUST require per-call approval (Phase-1 spec).
REQUIRED_GATED = {
    "mcp__blender__execute_blender_code",
    "mcp__blender__execute_blender_code_for_cli",
    "mcp__freecad__execute_code",
    "mcp__freecad__execute_code_async",
    "mcp__freecad__create_object",
    "mcp__freecad__edit_object",
    "mcp__freecad__delete_object",
}


def _ask_list():
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    return set(data.get("permissions", {}).get("ask", []))


def test_tier1_dcc_tools_are_gated():
    missing = REQUIRED_GATED - _ask_list()
    assert not missing, f"un-gated Tier-1 DCC tools: {sorted(missing)}"


def test_comfyui_exec_gates_still_present():
    # regression guard: broaden-to-hub must not drop existing comfyui gates
    ask = _ask_list()
    assert "mcp__comfyui__install_custom_node" in ask
    assert "mcp__comfyui__restart_comfyui" in ask
