"""
YAML-driven Workflow Runner for Manufacturing AI.

Loads a workflow definition from ~/.hermes/workflows/{name}.yaml
and executes steps sequentially with gate-based branching.

Usage:
    runner = WorkflowRunner.from_yaml("manufacturing-blueprint")
    result = await runner.execute(image_bytes=bytes, user_id="xxx")
    msg = runner.render_line_message(result)
"""

import asyncio
import importlib
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)

WORKFLOWS_DIR = Path.home() / ".hermes" / "workflows"


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class GateResult:
    passed: bool
    reason: str
    gate_id: str = ""


@dataclass
class StepResult:
    step_id: str
    name: str
    output: Any = None
    error_msg: Optional[str] = None
    gate: Optional[GateResult] = None
    skipped: bool = False
    skipped_reason: str = ""
    executed: bool = False

    @property
    def success(self) -> bool:
        return self.executed and self.output is not None and self.error_msg is None


@dataclass
class WorkflowResult:
    workflow_id: str
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    final_output: Any = None
    run_error: Optional[str] = None

    def is_complete(self) -> bool:
        return self.final_output is not None and self.run_error is None


# ── Workflow Runner ──────────────────────────────────────────────────────────

class WorkflowRunner:
    """
    YAML-driven workflow orchestrator.

    Loads workflow from YAML → executes steps sequentially →
    evaluates gates → skips or continues based on gate results.

    Key concepts:
    - requires_gate: a step can be marked as requiring a prior gate to pass
    - on_fail modes: error (hard stop), skip_remaining, fallback
    - output_schema: validated with Pydantic after step execution
    """

    _cache: Dict[str, dict] = {}

    def __init__(self, workflow_def: dict, name: str):
        self.workflow_def = workflow_def
        self.name = name
        self.config = workflow_def.get("config", {})
        self.steps: List[dict] = workflow_def.get("steps", [])
        self.output_def = workflow_def.get("output", {})
        self._gate_cache: Dict[str, callable] = {}

    @classmethod
    def from_yaml(cls, name: str) -> "WorkflowRunner":
        """Load workflow from ~/.hermes/workflows/{name}.yaml"""
        if name in cls._cache:
            logger.debug(f"Using cached workflow: {name}")
            def_dict = cls._cache[name]
        else:
            path = WORKFLOWS_DIR / f"{name}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"Workflow not found: {path}")
            with open(path, encoding="utf-8") as f:
                def_dict = yaml.safe_load(f)
            cls._cache[name] = def_dict
        return cls(def_dict, name)

    async def execute(self, **context) -> WorkflowResult:
        """
        Execute the full workflow with given context.

        Context keys vary by workflow, e.g.:
            image_bytes: raw image bytes
            image_b64: base64-encoded image
            user_id: LINE user ID

        Returns WorkflowResult with all step outputs and final rendered output.
        """
        result = WorkflowResult(workflow_id=self.name)
        stopped = False
        stopped_reason = ""

        for step_def in self.steps:
            step_id = step_def["id"]

            if stopped:
                result.step_results[step_id] = StepResult(
                    step_id=step_id,
                    name=step_def.get("name", step_id),
                    skipped=True,
                    skipped_reason=f"Workflow stopped: {stopped_reason}",
                )
                continue

            requires_gate = step_def.get("requires_gate")
            if requires_gate:
                prior = result.step_results.get(requires_gate)
                if prior and prior.gate and not prior.gate.passed:
                    result.step_results[step_id] = StepResult(
                        step_id=step_id,
                        name=step_def.get("name", step_id),
                        skipped=True,
                        skipped_reason=f"Blocked by gate '{prior.gate.gate_id}' ({prior.gate.reason})",
                    )
                    continue

            step_result = await self._execute_step(step_def, context, result)
            result.step_results[step_id] = step_result

            gate_def = step_def.get("gate")
            if gate_def:
                gate_result = self._run_gate(gate_def, step_result)
                step_result.gate = gate_result

                if not gate_result.passed:
                    on_fail = gate_def.get("on_fail", "error")
                    if on_fail == "error":
                        stopped = True
                        stopped_reason = f"Gate '{gate_def['id']}' failed: {gate_result.reason}"
                    elif on_fail == "skip_remaining":
                        logger.warning(
                            f"Gate '{gate_def['id']}' failed for step '{step_id}': {gate_result.reason}. "
                            f"Remaining gated steps will be skipped."
                        )

        try:
            result.final_output = self._render_output(result, context)
        except Exception as e:
            result.run_error = f"Output rendering failed: {e}"

        return result

    async def _execute_step(
        self,
        step_def: dict,
        context: dict,
        workflow_result: WorkflowResult,
    ) -> StepResult:
        """Execute a single step: resolve args → call module.method → validate schema."""
        step_id = step_def["id"]
        name = step_def.get("name", step_id)
        step_result = StepResult(step_id=step_id, name=name)

        try:
            resolved_args = self._resolve_args(step_def.get("args", {}), context, workflow_result)

            module_name = step_def["module"]
            method_name = step_def["method"]

            output = await self._call_method(module_name, method_name, resolved_args)
            step_result.output = output
            step_result.executed = True

            schema_path = step_def.get("output_schema")
            if schema_path and output is not None:
                validated = self._validate_schema(schema_path, output)
                step_result.output = validated

        except Exception as e:
            logger.error(f"Step '{step_id}' failed: {e}")
            step_result.error_msg = str(e)
            step_result.executed = True

        return step_result

    def _resolve_args(
        self,
        args: dict,
        context: dict,
        workflow_result: WorkflowResult,
    ) -> dict:
        """
        Resolve {placeholder} strings in args.

        Patterns:
            "{image_b64}"              → context["image_b64"]
            "{step_1_vision.output}"   → workflow_result.step_results["step_1_vision"].output
            "{step_1_vision.raw_text}" → special: access .raw_text on VisionResult
        """
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_placeholder(value, context, workflow_result)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_args(value, context, workflow_result)
            else:
                resolved[key] = value
        return resolved

    def _resolve_placeholder(
        self,
        value: str,
        context: dict,
        workflow_result: WorkflowResult,
    ) -> Any:
        """Resolve placeholder(s) in a string value.

        Supports two forms:
          - Single: "{step_x.output.field}"
          - Multi:  "{step_x.output.field1} {step_x.output.field2}"
        """
        if not isinstance(value, str):
            return value

        # Short-circuit if no braces at all
        if "{" not in value:
            return value

        # Multi-placeholder: "{a} {b}" — resolve each segment
        if value.startswith("{"):
            # Check if there are multiple placeholders by looking for whitespace between braces
            # e.g. "{step_2.output.material} {step_2.output.dimensions}"
            import re
            # Match each {placeholder} segment
            pattern = r"\{[^}]+\}"
            segments = re.split(pattern, value)
            matches = re.findall(pattern, value)

            if len(matches) > 1:
                # Multiple placeholders — resolve each and rebuild the string
                import re
                result = value
                for ph in matches:
                    resolved = self._resolve_single(ph.strip(), context, workflow_result)
                    resolved_str = str(resolved) if resolved is not None else ph
                    result = result.replace(ph, resolved_str, 1)
                return result

            # Single placeholder
            return self._resolve_single(value, context, workflow_result)

        # No braces — return as-is
        return value

    def _resolve_single(
        self,
        value: str,
        context: dict,
        workflow_result: WorkflowResult,
    ) -> Any:
        """Resolve a single placeholder string (must start with '{')."""
        if not isinstance(value, str) or not value.startswith("{"):
            return value

        path = value.strip().strip("{}")
        parts = path.split(".")

        if len(parts) == 1:
            return context.get(parts[0], value)

        if len(parts) >= 2 and parts[0].startswith("step_"):
            step_id = parts[0]
            step_result = workflow_result.step_results.get(step_id)
            if step_result is None:
                return value

            # parts[1] is the attribute on StepResult (e.g. 'output', 'error_msg')
            # Note: StepResult.output IS the actual data (dict/Pydantic model), not a nested wrapper
            attr = parts[1]
            if attr == "output":
                obj = step_result.output
            else:
                obj = getattr(step_result, attr, None)

            # If there are further parts (e.g. 'step_2.output.material'), traverse
            for a in parts[2:]:
                if obj is None:
                    return None
                if isinstance(obj, dict):
                    obj = obj.get(a)
                else:
                    obj = getattr(obj, a, None)
            return obj if obj is not None else value

        return context.get(parts[-1], value)

    async def _call_method(self, module_name: str, method_name: str, args: dict) -> Any:
        """Import module and call method, passing args as kwargs."""
        if "app." in module_name:
            backend_path = str(Path(__file__).parent.parent.parent)
            if backend_path not in sys.path:
                sys.path.insert(0, backend_path)

        module = importlib.import_module(module_name)
        method = getattr(module, method_name)

        if asyncio.iscoroutinefunction(method):
            return await method(**args)
        else:
            return method(**args)

    def _validate_schema(self, schema_path: str, output: Any) -> Any:
        """Validate output against a Pydantic schema path."""
        try:
            backend_path = str(Path(__file__).parent.parent.parent)
            if backend_path not in sys.path:
                sys.path.insert(0, backend_path)

            parts = schema_path.split(".")
            module_parts = parts[:-1]
            class_name = parts[-1]

            if module_parts[0] == "builtin":
                return output

            module = importlib.import_module(".".join(module_parts))
            schema_cls = getattr(module, class_name)

            if isinstance(output, dict):
                return schema_cls(**output)
            else:
                return schema_cls.model_validate(output)
        except Exception as e:
            logger.warning(f"Schema validation failed for {schema_path}: {e}")
            return output

    def _run_gate(self, gate_def: dict, step_result: StepResult) -> GateResult:
        """Run a verification gate on a step's output."""
        gate_id = gate_def["id"]
        module_name = gate_def["module"]

        if gate_id not in self._gate_cache:
            backend_path = str(Path(__file__).parent.parent.parent)
            if backend_path not in sys.path:
                sys.path.insert(0, backend_path)

            module = importlib.import_module(module_name)
            self._gate_cache[gate_id] = getattr(module, gate_id)

        gate_fn = self._gate_cache[gate_id]
        output = step_result.output

        # Pass optional gate params from YAML (e.g., score_threshold for KB gate)
        gate_params = gate_def.get("params", {})

        try:
            if gate_params:
                passed, reason = gate_fn(output, **gate_params)
            else:
                passed, reason = gate_fn(output)
        except Exception as e:
            passed, reason = False, f"Gate execution error: {e}"

        return GateResult(passed=passed, reason=reason, gate_id=gate_id)

    def _render_output(
        self,
        result: WorkflowResult,
        context: dict,
    ) -> dict:
        """
        Render the final LINE message from step outputs.

        Uses the output.template in the YAML to build the final response.
        Supports conditional 'if/then/else' clauses.
        """
        template = self.output_def.get("template", [])
        output_type = self.output_def.get("type", "text")

        if not template:
            return {"type": "text", "text": "Workflow completed with no output template."}

        lines = []
        for item in template:
            if isinstance(item, str):
                rendered = self._substitute_template(item, result, context)
                lines.append(rendered)
            elif isinstance(item, dict):
                condition = item.get("if", "")
                then_val = item.get("then", "")
                else_val = item.get("else", "")

                if self._eval_condition(condition, result):
                    rendered = self._substitute_template(then_val, result, context)
                    if rendered:
                        lines.append(rendered)
                else:
                    rendered = self._substitute_template(else_val, result, context)
                    if rendered:
                        lines.append(rendered)

        full_text = "\n".join(lines)

        if output_type == "flex":
            step_6 = result.step_results.get("step_6_quote")
            if step_6 and step_6.output:
                try:
                    return step_6.output.to_line_message()
                except Exception:
                    pass
            return {"type": "text", "text": full_text}

        return {"type": "text", "text": full_text}

    def _substitute_template(self, template_str: str, result: WorkflowResult, context: dict) -> str:
        """Substitute {placeholders} in a template string."""
        def replacer(match):
            path = match.group(1).strip()
            value = self._resolve_placeholder("{" + path + "}", context, result)
            if value is None:
                return ""
            if isinstance(value, float):
                return f"{value:.2f}"
            return str(value)

        return re.sub(r"\{([^}]+)\}", replacer, template_str)

    def _eval_condition(self, condition: str, result: WorkflowResult) -> bool:
        """Evaluate a simple condition like 'step_5_rule_engine.executed'."""
        condition = condition.strip()
        if not condition:
            return True

        if condition.endswith(".executed"):
            step_id = condition.replace(".executed", "").strip()
            step = result.step_results.get(step_id)
            return step is not None and step.executed

        if condition.startswith("not "):
            step_id = condition.replace("not ", "").replace(".executed", "").strip()
            step = result.step_results.get(step_id)
            return step is None or not step.executed

        if ".gate.passed" in condition:
            step_id = condition.split(".gate.passed")[0].strip()
            step = result.step_results.get(step_id)
            return step is not None and step.gate is not None and step.gate.passed

        return True

    def render_line_message(self, result: WorkflowResult) -> dict:
        """Public API: render a LINE-ready message dict from a completed workflow result."""
        if result.run_error:
            return {
                "type": "text",
                "text": f"⚠️ Workflow error: {result.run_error}",
                "quickReply": {
                    "items": [
                        {"type": "action", "action": {"type": "message", "label": "查询报价", "text": "我想查询报价"}},
                        {"type": "action", "action": {"type": "message", "label": "联系客服", "text": "人工报价"}},
                    ]
                }
            }
        return result.final_output or {"type": "text", "text": "Workflow completed."}
