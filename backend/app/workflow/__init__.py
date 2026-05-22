"""Manufacturing AI Workflow - Verification Gates + YAML Workflow Runner

Modules:
    schemas/   - Pydantic models for each step's output
    gates/     - Verification gates that validate step outputs
    workflow_runner.py - YAML-driven workflow orchestrator
"""

from pathlib import Path

WORKFLOW_DIR = Path(__file__).parent
SCHEMAS_DIR = WORKFLOW_DIR / "schemas"
GATES_DIR = WORKFLOW_DIR / "gates"
WORKFLOWS_DIR = Path.home() / ".hermes" / "workflows"

__all__ = ["schemas", "gates", "workflow_runner", "SCHEMAS_DIR", "GATES_DIR"]
