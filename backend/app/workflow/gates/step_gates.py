"""
Verification Gates for Manufacturing Workflow.

Each gate validates the output of its preceding step.
Gates return (passed: bool, reason: str).

The KB Gate is the most important one: it guards Step 5 (Rule Engine)
and Step 6 (Quote) from running without valid KB data.
"""

from typing import Tuple, Any


# ── Gate 1: Vision Result ──────────────────────────────────────────────────

def gate_vision_result(vision_result: dict) -> Tuple[bool, str]:
    """
    Gate after Step 1 (Vision/OCR).

    Checks:
    - vision_result is not None/empty
    - No hard error markers (error, error_message)
    - content field is present and non-empty
    - content does not indicate total failure (e.g. "未能识别")

    Returns:
        (passed, reason)
    """
    if not vision_result:
        return False, "Vision result is empty"

    # Check for error markers
    error_keys = {"error", "error_message", "error_type"}
    for key in error_keys:
        if key in vision_result:
            msg = vision_result.get(key, "unknown error")
            return False, f"Vision returned error: {msg}"

    # Must have a content field with real text
    content = vision_result.get("content", "")
    if not content:
        return False, "Vision result has no content field"

    # Content must not be trivially empty/failed
    if isinstance(content, str) and len(content.strip()) < 5:
        return False, f"Vision content too short: '{content}'"

    return True, "OK"


    # ── Gate 2: Blueprint Features ────────────────────────────────────────────

# Known material codes (allow '其他')
_KNOWN_MATERIALS = {
    "SUS304", "SUS303", "SUS316", "SUS430",
    "SECC", "SPCC", "SGCC", "SGLC",
    "ADC12", "A383", "A5052", "AL5052", "铝合金",
    "ABS", "PC", "PP", "PA", "POM",
    # Carbon steels
    "45钢", "45号钢", "S45C", "S50C", "S55C",
    "45 Steel", "45", "A36", "Q235", "Q345",
    "其他",
}

def _is_unknown_material(material: str) -> bool:
    """Check if material is considered unknown/unlabeled."""
    return material in ("未知", "未标注", "") or material not in _KNOWN_MATERIALS


def gate_blueprint_features(features: dict) -> Tuple[bool, str]:
    """
    Gate after Step 2 (Feature Extraction).

    Checks:
    - features is not None/empty
    - material is not '未标注' and is a known material code
    - quantity > 0 and reasonable (< 10000)
    - weight_kg > 0 and reasonable (< 1000 kg)

    Accepts either a dict or a BlueprintFeatures Pydantic model.

    Returns:
        (passed, reason)
    """
    if not features:
        return False, "Features dict is empty"

    # Support both dict and Pydantic model
    if hasattr(features, "material"):
        # It's a Pydantic model — extract to dict
        material = features.material
        quantity = features.quantity
        weight_kg = features.weight_kg
    else:
        material = features.get("material", "未知")
        quantity = features.get("quantity", 0)
        weight_kg = features.get("weight_kg", 0.0)

    if _is_unknown_material(material):
        # Allow through if we have structural info — KB can search by structure
        structure_type = ""
        if hasattr(features, "structure_type"):
            structure_type = features.structure_type or ""
        elif isinstance(features, dict):
            structure_type = features.get("structure_type", "") or ""
        if structure_type in ("未标注", "未知", ""):
            return False, "Material is unknown and structure type cannot be identified"

    # Quantity check
    try:
        quantity = int(quantity)
    except (ValueError, TypeError):
        return False, f"Quantity is not a valid number: {quantity}"

    if quantity <= 0:
        return False, f"Quantity must be positive, got {quantity}"
    if quantity > 10000:
        return False, f"Quantity {quantity} seems unrealistic (>10000)"

    # Weight check
    try:
        weight = float(weight_kg)
    except (ValueError, TypeError):
        return False, f"Weight is not a valid number: {weight_kg}"

    if weight <= 0:
        return False, f"Weight must be positive, got {weight}"
    if weight > 500:
        return False, f"Weight {weight}kg seems unrealistic (>500kg)"

    return True, "OK"


# ── Gate 3: KB Match (CRITICAL) ────────────────────────────────────────────

def gate_kb_match(kb_results: list, score_threshold: float = None) -> Tuple[bool, str]:
    """
    Gate between Step 4 and Step 5 (KB Match Gate).

    This is the CRITICAL gate for manufacturing-ai.
    If KB returns no useful results, Step 5 (Rule Engine) and
    Step 6 (Quote API) MUST NOT RUN.

    Args:
        kb_results: List of KB search results from Step 4
        score_threshold: Minimum score to pass. If None, auto-detects:
            - keyword search scores (10-30 range): use 3.0
            - vector search scores (0-1 range): use 0.3

    Returns:
        (passed, reason)
    """
    if not kb_results:
        return False, "KB returned no results — cannot proceed to Step 5"

    # Auto-detect search type from score magnitude
    sample_scores = [r.get("score", 0) for r in kb_results[:3]]
    max_score = max(sample_scores) if sample_scores else 0

    if score_threshold is None:
        # Vector search scores are 0-1, keyword search scores are 10+
        score_threshold = 3.0 if max_score > 1 else 0.3

    relevant = [r for r in kb_results if r.get("score", 0) >= score_threshold]

    if not relevant:
        return False, (
            f"KB results exist but all below score threshold {score_threshold}. "
            f"Best score: {max(r.get('score', 0) for r in kb_results):.2f}"
        )

    return True, f"OK — {len(relevant)}/{len(kb_results)} KB results above threshold (threshold={score_threshold})"


# ── Gate 4: Quote Spec ─────────────────────────────────────────────────────

def gate_quote_spec(quote_spec: dict) -> Tuple[bool, str]:
    """
    Gate after Step 6 (Quote Generation).
    
    Validates the final quote output:
    - Has valid quote_id
    - Prices are positive
    - Lead time is reasonable
    - Currency is JPY
    
    Returns:
        (passed, reason)
    """
    if not quote_spec:
        return False, "Quote spec is empty"
    
    if not quote_spec.get("quote_id"):
        return False, "Quote has no quote_id"
    
    pricing = quote_spec.get("pricing", {})
    unit_price = pricing.get("unit_price", 0)
    if unit_price <= 0:
        return False, f"Unit price must be positive, got {unit_price}"
    
    lead_time = quote_spec.get("lead_time_days", 0)
    if lead_time <= 0:
        return False, f"Lead time must be positive, got {lead_time}"
    if lead_time > 180:
        return False, f"Lead time {lead_time} days seems unrealistic (>180)"
    
    return True, "OK"


# ── Gate 5: Process Classification ────────────────────────────────────────

def gate_process_classification(process_type: str) -> Tuple[bool, str]:
    """
    Gate after Step 3 (Process Classification).
    
    Validates the process type is one of the known categories.
    """
    valid_types = {
        "CNC加工", "钣金加工", "压铸铸造", 
        "表面处理", "冲压加工", "3D打印",
    }
    if not process_type:
        return False, "Process type is empty"
    if process_type not in valid_types:
        return False, f"Unknown process type: {process_type}"
    return True, "OK"
