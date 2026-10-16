"""Migration guard for the Qwen3 agent upgrade: the orchestrator carries no stale Qwen2.5 or machine-specific
model references, and it documents the Ollama Qwen3-VL judge path (the judge's local default; any other
endpoint or model comes from config)."""
from __future__ import annotations
import importlib
import sys


def test_agent_layer_does_not_import_the_cli_module():
    # layering: the agent layer must not drag the 900-line CLI entrypoint (argparse + every
    # modality filler) into its import graph just for the provenance helper
    saved = {m: mod for m, mod in sys.modules.items() if m.startswith("scripts")}
    try:
        for m in list(sys.modules):
            if m.startswith("scripts"):
                del sys.modules[m]
        importlib.import_module("scripts.agent.auto_generate")
        importlib.import_module("scripts.agent.finalize")
        assert "scripts.generate" not in sys.modules
    finally:
        sys.modules.update(saved)
import inspect
import re

ag = importlib.import_module("scripts.agent.auto_generate")


def test_orchestrator_has_no_stale_or_machine_specific_refs():
    src = inspect.getsource(ag)
    low = src.lower()
    assert "qwen2.5" not in low                       # migrated to Qwen3
    assert not re.search(r"\b[a-z]:[\\/]", low)       # no local absolute path (a drive letter)


def test_orchestrator_documents_ollama_qwen3_recommendation():
    # The api/Ollama Qwen3-VL path is the documented recommendation in the CLI help/docstring.
    low = inspect.getsource(ag).lower()
    assert "qwen3-vl" in low and "ollama" in low
