import json, pathlib

SETTINGS = pathlib.Path(__file__).resolve().parents[1] / ".claude" / "settings.json"

# Tier-1 RCE / code-exec DCC tools that MUST require per-call approval (Phase-1 spec).
REQUIRED_GATED = {
    "mcp__blender__execute_blender_code",
    "mcp__blender__execute_blender_code_for_cli",
    "mcp__freecad__execute_code",
    "mcp__freecad__execute_code_async",
    "mcp__freecad__execute_code_headless",   # v0.1.25+: model Python in a freecadcmd subprocess
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


# Install-, download- and config-changing comfyui-mcp tools (pinned 0.18.0). The 2026-10 audit found these
# ungated although the docs said so: downloads into models/, Manager security level, extra model paths,
# scaffolding a custom node (code ComfyUI executes), node-pack bisects, paid API nodes, issue reports.
COMFYUI_INSTALL_CHANGING = {
    "mcp__comfyui__install_custom_node", "mcp__comfyui__update_custom_node", "mcp__comfyui__reinstall_custom_node",
    "mcp__comfyui__fix_custom_node", "mcp__comfyui__sync_node_dependencies",
    "mcp__comfyui__install_workflow_dependencies", "mcp__comfyui__install_comfyui", "mcp__comfyui__apply_manifest",
    "mcp__comfyui__restore_node_snapshot", "mcp__comfyui__update_comfyui", "mcp__comfyui__update_all",
    "mcp__comfyui__publish_custom_node", "mcp__comfyui__remove_model", "mcp__comfyui__download_model",
    "mcp__comfyui__download_civitai_model", "mcp__comfyui__configure_manager", "mcp__comfyui__add_extra_path",
    "mcp__comfyui__remove_extra_path", "mcp__comfyui__scaffold_custom_node", "mcp__comfyui__generate_node_skill",
    "mcp__comfyui__bisect_start", "mcp__comfyui__bisect_good", "mcp__comfyui__bisect_bad",
    "mcp__comfyui__bisect_reset", "mcp__comfyui__generate_with_api_node", "mcp__comfyui__report_issue",
    # files and settings that persist: save_workflow overwrites without asking
    "mcp__comfyui__save_workflow", "mcp__comfyui__lock_workflow", "mcp__comfyui__save_node_snapshot",
    "mcp__comfyui__set_defaults", "mcp__comfyui__set_default_workspace",
}


def test_comfyui_install_download_and_config_tools_are_gated():
    missing = COMFYUI_INSTALL_CHANGING - _ask_list()
    assert not missing, f"un-gated install/download/config-changing comfyui tools: {sorted(missing)}"


def test_freecad_reload_document_is_gated():
    # it closes and reopens the document, discarding unsaved edits: not read-only (2026-10 audit)
    assert "mcp__freecad__reload_document" in _ask_list()
