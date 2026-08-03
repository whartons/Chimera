"""Migration guard for the Qwen3 agent upgrade: the orchestrator carries no stale Qwen2.5 or personal
model references, and it documents the recommended Ollama Qwen3-VL judge path (delivered via .env/docs,
not hardcoded — llm.py stays default-free, so the actual endpoint/model live in config)."""
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

ag = importlib.import_module("scripts.agent.auto_generate")


def test_orchestrator_has_no_stale_qwen25_or_personal_refs():
    src = inspect.getsource(ag)
    low = src.lower()
    assert "qwen2.5" not in low                       # migrated to Qwen3
    assert "qwen-sports" not in low                   # never the personal Ollama tag
    assert "c:\\ai" not in low and "c:/ai" not in low  # never the personal model path


def test_orchestrator_documents_ollama_qwen3_recommendation():
    # The api/Ollama Qwen3-VL path is the documented recommendation in the CLI help/docstring.
    low = inspect.getsource(ag).lower()
    assert "qwen3-vl" in low and "ollama" in low
