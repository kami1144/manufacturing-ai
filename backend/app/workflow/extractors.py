"""
Feature extractors for manufacturing workflow.
Step 2 and Step 3 logic extracted from line_module.py.
"""

from typing import Dict, Any
from app.workflow.schemas.blueprint_spec import VisionResult, BlueprintFeatures
from app.workflow.gates.step_gates import _KNOWN_MATERIALS


def extract_blueprint_features(vision_result: Dict[str, Any]) -> BlueprintFeatures:
    """
    Step 2: Convert raw vision output → typed BlueprintFeatures.

    ai_module.vision() returns: {"content": "raw text containing JSON", ...}
    We need to extract the JSON from the content first.

    Handles:
    - Type coercion (str → int, str → float)
    - '未标注' fallback values
    - Safe defaults for missing fields
    - JSON extraction from raw AI text

    Args:
        vision_result: Raw dict from Step 1 (vision model output)

    Returns:
        BlueprintFeatures with cleaned, typed fields
    """
    import json
    import re

    raw = vision_result if isinstance(vision_result, dict) else {}

    # Extract content (the raw text with embedded JSON or description)
    content = raw.get("content", "")

    # Try to find JSON in content
    struct_data = {}

    # Strip markdown code fences if present
    content_clean = re.sub(r'^```json[\s\n]*', '', content.strip())
    content_clean = re.sub(r'[\s\n]*```$', '', content_clean)
    # Strip markdown bold/italic markers that can break JSON extraction
    content_clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', content_clean)
    content_clean = re.sub(r'\*([^*]+)\*', r'\1', content_clean)

    if content_clean:
        # First: try direct JSON — use a less restrictive pattern that allows
        # any content between braces (including nested), then validate with json.loads
        json_match = re.search(r'\{[\s\S]*\}', content_clean)
        if json_match:
            try:
                struct_data = json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Second: if content is a JSON array (object detection output), extract labels
        if not struct_data and content_clean.startswith('['):
            try:
                detections = json.loads(content_clean)
                if isinstance(detections, list):
                    labels = [d.get('label', '') or d.get('description', '') for d in detections if isinstance(d, dict)]
                    desc_text = ' '.join(labels)

                    # Infer structure type from detection labels
                    label_lower = desc_text.lower()
                    if 'gear' in label_lower or '齿轮' in label_lower:
                        struct_data['结构类型'] = '齿轮组件'
                    elif 'shaft' in label_lower or '轴' in label_lower:
                        struct_data['结构类型'] = '轴类零件'
                    elif 'bracket' in label_lower or '支架' in label_lower:
                        struct_data['结构类型'] = '支架类'
                    elif 'housing' in label_lower or '箱体' in label_lower:
                        struct_data['结构类型'] = '箱体类'
                    elif 'plate' in label_lower or '板' in label_lower:
                        struct_data['结构类型'] = '板类零件'

                    # Store labels in content for fallback regex extraction
                    content_clean = desc_text
            except json.JSONDecodeError:
                pass

    # Third: extract from descriptive text — independent of JSON success/failure
        # Material extraction first (must run regardless of struct_data state)
    if content_clean:
        _CARBON_STEEL_CODES = {"45", "45C", "40", "40C", "50", "50C", "55", "55C", "A36", "1045"}
        _mat_patterns = [
            # English formats (common in technical drawings)
            r'material[:\s]+["\']?([A-Z0-9\s]+)["\']?\s*steel',  # Material: 45 Steel / Material: "45" steel
            r'material[:\s"]+([A-Z0-9]+)["\']?',                  # Material: "45"
            r'material[:\s]+([A-Z0-9]+)\s+steel',                 # Material: 45 Steel
            r'material\s*\(([^)]+\d[^)]*)\)',                     # Material (45 Steel)
            r'material:\s*"([A-Z0-9]+)"',                        # Material: "45"
            r'material:\s*([A-Z0-9]+)',                           # Material: 45
            r'material[^:\d]*(\d{2,3})\b',                        # material followed by 2-3 digit code anywhere
            # Chinese formats
            r'材质[:：]\s*([^\s，,]+)',                             # 材质: SUS304
            r'材料[:：]\s*([^\s，,]+)',                             # 材料: 45号钢
        ]
        print(f"[DEBUG] content_clean sample: {content_clean[:200]!r}")
        for p in _mat_patterns:
            m = re.search(p, content_clean, re.IGNORECASE)
            print(f"[DEBUG] Pattern {p!r} → {m.group(1) if m else 'NO MATCH'!r}")
            if m:
                found = m.group(1).strip().strip('"\' ')
                if found.upper() in _CARBON_STEEL_CODES or found.upper() in _KNOWN_MATERIALS:
                    if found.upper() in {"45", "45C"}:
                        struct_data['材质'] = "45号钢"
                    elif found.upper() in {"40", "40C"}:
                        struct_data['材质'] = "40号钢"
                    else:
                        struct_data['材质'] = found.upper()
                    print(f"[DEBUG] Set material to {struct_data['材质']!r} via pattern {p!r}")
                    break

        # Extract quantity
        qty_patterns = [
            r'(?:quantity|数量|pcs|pieces|个|件)[:\s=]*(\d+)',
            r'(\d+)\s*(?:pcs|pieces|个|件)',
        ]
        for pattern in qty_patterns:
            m = re.search(pattern, content_clean, re.IGNORECASE)
            if m:
                struct_data['数量'] = m.group(1)
                break

        # Extract dimensions (e.g. 100x80x50mm)
        dim_patterns = [
            r'(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*(?:mm|cm)?',
            r'(?:尺寸|dimensions)[:\s]*(\d+(?:\.\d+)?(?:\s*[xX×]\s*\d+(?:\.\d+)?){1,2})',
        ]
        for pattern in dim_patterns:
            m = re.search(pattern, content_clean)
            if m:
                if m.lastindex and m.lastindex >= 3:
                    struct_data['主要尺寸'] = f"{m.group(1)}x{m.group(2)}x{m.group(3)}mm"
                else:
                    struct_data['主要尺寸'] = m.group(1)
                break

        # Extract hole count
        hole_patterns = [
            r'(?:hole|孔)[:\s=]*(\d+)',
            r'(\d+)\s*(?:holes|孔)',
        ]
        for pattern in hole_patterns:
            m = re.search(pattern, content_clean, re.IGNORECASE)
            if m:
                struct_data['孔数量'] = m.group(1)
                break

        # Extract tolerance
        tol_patterns = [
            r'(?:tolerance|公差)[:\s]*(±?\d+(?:\.\d+)?\s*(?:mm|μm)?)',
        ]
        for pattern in tol_patterns:
            m = re.search(pattern, content_clean, re.IGNORECASE)
            if m:
                struct_data['公差要求'] = m.group(1)
                break

    # Fourth: infer structure type from description text (after material so we don't skip)
    if not struct_data.get('结构类型') and content_clean:
        desc_lower = content_clean.lower()
        if 'pump shaft' in desc_lower or '泵轴' in desc_lower:
            struct_data['结构类型'] = '轴类零件'
        elif 'shaft' in desc_lower or '轴' in desc_lower:
            struct_data['结构类型'] = '轴类零件'
        elif 'gear' in desc_lower or '齿轮' in desc_lower:
            struct_data['结构类型'] = '齿轮组件'
        elif 'bracket' in desc_lower or '支架' in desc_lower:
            struct_data['结构类型'] = '支架类'
        elif 'housing' in desc_lower or '箱体' in desc_lower:
            struct_data['结构类型'] = '箱体类'
        elif 'plate' in desc_lower or '板' in desc_lower:
            struct_data['结构类型'] = '板类零件'
        elif 'bearing' in desc_lower or '轴承' in desc_lower:
            struct_data['结构类型'] = '轴承组件'
        elif 'enclosure' in desc_lower or 'case' in desc_lower:
            struct_data['结构类型'] = '外壳类'

    # Fifth: fallback inference — mmx vision is non-deterministic, material may be missing
    # even when structure type is identified and "45" appears in the content
    if not struct_data.get('材质') and struct_data.get('结构类型') == '轴类零件' and content_clean:
        if re.search(r'\b45\b', content_clean, re.IGNORECASE):
            struct_data['材质'] = '45号钢'
        # Generic "steel" + shaft = likely carbon steel (most common for pump shafts)
        elif re.search(r'\bsteel\b', content_clean, re.IGNORECASE):
            struct_data['材质'] = '45号钢'

    # Fall back to raw dict if JSON extraction failed
    if not struct_data:
        struct_data = {k: v for k, v in raw.items() if k not in ("content", "raw", "error")}

    # Parse quantity
    qty_raw = struct_data.get("数量", "1")
    try:
        quantity = int(qty_raw)
    except (ValueError, TypeError):
        quantity = 1

    # Parse weight
    weight_raw = struct_data.get("重量kg", "1.0")
    try:
        weight_kg = float(str(weight_raw).replace("kg", "").strip())
    except (ValueError, TypeError):
        weight_kg = 1.0

    # Parse hole count
    hole_raw = struct_data.get("孔数量", "0")
    try:
        hole_count = int(hole_raw)
    except (ValueError, TypeError):
        hole_count = 0

    return BlueprintFeatures(
        material=struct_data.get("材质", "未标注"),
        quantity=quantity,
        dimensions=struct_data.get("主要尺寸", "未标注"),
        weight_kg=weight_kg,
        tolerance=struct_data.get("公差要求", "普通"),
        surface=struct_data.get("表面处理", "无特殊要求"),
        thickness=struct_data.get("板厚mm", "未标注"),
        hole_count=hole_count,
        symmetry=struct_data.get("对称性", "未标注"),
        structure_type=struct_data.get("结构类型", "未标注"),
        raw_vision=raw,
    )


def classify_process(features: BlueprintFeatures, vision_result: Dict[str, Any]) -> str:
    """
    Step 3: Classify manufacturing process type based on features.
    
    Logic (from line_module.py):
    - 压铸铸造: ADC/A383/zinc alloys
    - 钣金加工: SECC/SPCC/AL5052 + thin plate + sheet metal keywords
    - Default: CNC加工
    
    Args:
        features: Extracted blueprint features
        vision_result: Raw vision result (for keyword inspection)
    
    Returns:
        Process type string: "CNC加工" | "钣金加工" | "压铸铸造" | "表面处理"
    """
    material = features.material.upper()
    vision_text = str(vision_result).lower()
    
    # 1. Casting:铝合金/锌合金/压铸
    casting_materials = {"ADC", "A383", "ZAMAK", "锌"}
    if any(m in material for m in casting_materials):
        return "压铸铸造"
    if "铸造" in vision_text or "铸" in vision_text:
        return "压铸铸造"
    
    # 2. Sheet metal: thin plate + specific materials
    sheet_metal_materials = {"SECC", "SPCC", "AL5052", "铝合金"}
    if any(m in material for m in sheet_metal_materials):
        if features.thickness not in ("未标注", "未知", ""):
            return "钣金加工"
    if any(kw in vision_text for kw in ["折弯", "钣金", "冲孔", "激光切割", "sheet metal"]):
        return "钣金加工"
    
    # 3. Default to CNC
    return "CNC加工"
