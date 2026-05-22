"""
Quote helper functions for manufacturing workflow.
Step 5 (Rule Engine) and Step 6 (Quote API) logic.
"""

from typing import Dict, Any, Optional
import httpx


# ── Step 5: Rule Engine - Hours Estimation ────────────────────────────────

def estimate_hours(
    material: str,
    quantity: int,
    weight_kg: float,
    process_type: str,
    features: Dict[str, Any],
) -> str:
    """
    Step 5: Estimate manufacturing hours based on rules.
    
    Logic (from line_module.py _estimate_hours):
    - Base hours per process type
    - Material difficulty factor
    - Quantity batch discount factor
    - Hole count complexity factor
    
    Args:
        material: Material code (e.g. "SUS304")
        quantity: Order quantity (pieces)
        weight_kg: Weight in kg
        process_type: "CNC加工" | "钣金加工" | "压铸铸造"
        features: BlueprintFeatures dict (for hole_count, etc.)
    
    Returns:
        Formatted estimation text
    """
    # Base hours per process (single unit)
    base_hours = {
        "CNC加工": 2.0,
        "钣金加工": 1.5,
        "压铸铸造": 3.0,
        "表面处理": 1.0,
    }
    
    # Material difficulty multiplier
    material_factor = {
        "SUS304": 1.3,
        "SUS303": 1.2,
        "SUS316": 1.4,
        "AL5052": 1.0,
        "ADC12": 1.1,
        "A383": 1.1,
        "SECC": 1.0,
        "SPCC": 0.9,
        "其他": 1.2,
    }
    
    # Get factors
    base = base_hours.get(process_type, 2.0)
    factor = material_factor.get(material.upper(), 1.0)
    
    # Quantity batch discount
    if quantity <= 10:
        qty_factor = 1.0
    elif quantity <= 50:
        qty_factor = 0.85
    elif quantity <= 100:
        qty_factor = 0.75
    else:
        qty_factor = 0.65
    
    # Hole count complexity
    hole_count = features.get("hole_count", 0) if isinstance(features, dict) else 0
    hole_factor = 1.0 + (hole_count * 0.05) if hole_count > 0 else 1.0
    
    # Calculate total
    estimated_hours = base * factor * qty_factor * hole_factor
    
    return (
        f"预估工时：{estimated_hours:.1f}小时/件\n"
        f"- 基础工时：{base}小时\n"
        f"- 材质系数：{factor} ({material})\n"
        f"- 批量系数：{qty_factor} (x{quantity}件)\n"
        f"- 孔数系数：{hole_factor:.2f} ({hole_count}个孔)"
    )


# ── Step 6: Quote Generation ─────────────────────────────────────────────

async def generate_quote(
    material: str,
    quantity: int,
    weight_kg: float,
    process_category: str,
    base_url: str = "http://localhost:8000",
    lead_time_days: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Step 6: Call quote API to generate a formal quote.
    
    Args:
        material: Material code
        quantity: Order quantity
        weight_kg: Weight in kg
        process_category: Process type string
        base_url: API base URL
        lead_time_days: Optional delivery requirement
    
    Returns:
        Quote API response dict (raw)
    """
    payload = {
        "material": material,
        "quantity": quantity,
        "weight_kg": weight_kg,
        "process_category": process_category,
    }
    if lead_time_days:
        payload["lead_time_days"] = lead_time_days
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base_url}/api/quote/generate",
                json=payload,
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        # Return empty dict on failure — caller handles
        return {}
    
    return {}
