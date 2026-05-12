"""
报价模块 - 独立可复用

功能：
- 工艺分类
- 工时估算
- 成本计算
- 报价生成
"""

from typing import Optional
from dataclasses import dataclass


@dataclass
class ProcessStepData:
    """工序数据"""
    step: str
    process_type: str
    estimated_hours: float
    material_cost: float
    labor_cost: float


@dataclass
class QuoteResult:
    """报价结果"""
    material_cost: float
    labor_cost: float
    total_hours: float
    estimated_price: float
    lead_time_days: int


# ── 工艺分类器 ──────────────────────────────────────────


def classify_process(material: str, surface_area: float = None, tolerance: str = None) -> str:
    """
    根据材质和工艺要求分类工艺类型

    Args:
        material: 材质（如SUS304, SECC, ADC12）
        surface_area: 表面积(cm2)
        tolerance: 公差要求

    Returns:
        工艺类型字符串
    """
    material_upper = material.upper()

    if "SUS" in material_upper or "304" in material_upper or "316" in material_upper:
        return "cnc_machining"
    elif "SECC" in material_upper or "SPCC" in material_upper or "SGCC" in material_upper:
        return "sheet_metal"
    elif "ADC" in material_upper or "A383" in material_upper:
        return "die_casting"
    else:
        return "cnc_machining"  # 默认


# ── 工时估算 ──────────────────────────────────────────


def estimate_hours(process_type: str, weight_kg: float = None, surface_area: float = None) -> float:
    """
    估算加工工时（小时）
    """
    rates = {
        "cnc_machining": 0.05,   # 每kg
        "sheet_metal": 0.02,     # 每kg
        "die_casting": 0.08,      # 每kg
    }
    rate = rates.get(process_type, 0.05)
    base = weight_kg or 1.0
    return round(base * rate * 100) / 100


# ── 成本计算 ──────────────────────────────────────────


def calculate_cost(
    process_type: str,
    material_cost: float,
    total_hours: float,
    quantity: int = 1
) -> QuoteResult:
    """
    计算报价成本

    Args:
        process_type: 工艺类型
        material_cost: 材料成本
        total_hours: 总工时
        quantity: 数量

    Returns:
        QuoteResult: 报价结果
    """
    # 工时费率表（每小时日元）
    labor_rates = {
        "cnc_machining": 8000,
        "sheet_metal": 6000,
        "die_casting": 10000,
        "surface_treatment": 3000,
    }

    labor_rate = labor_rates.get(process_type, 8000)
    labor_cost = total_hours * labor_rate * quantity

    # 材料费乘以数量
    total_material = material_cost * quantity

    # 总成本
    subtotal = total_material + labor_cost

    # 含15%利润的报价
    estimated_price = round(subtotal * 1.15 / 1000) * 1000  # 四舍五入到千位

    # 交期估算
    lead_times = {
        "cnc_machining": 7,
        "sheet_metal": 5,
        "die_casting": 14,
    }
    lead_time = lead_times.get(process_type, 7)

    return QuoteResult(
        material_cost=total_material,
        labor_cost=labor_cost,
        total_hours=total_hours * quantity,
        estimated_price=estimated_price,
        lead_time_days=lead_time
    )


# ── 报价生成 ──────────────────────────────────────────


def generate_quote(
    material: str,
    weight_kg: float = 1.0,
    quantity: int = 1,
    tolerance: str = "normal"
) -> dict:
    """
    生成完整报价单

    Args:
        material: 材质
        weight_kg: 重量(kg)
        quantity: 数量
        tolerance: 公差要求

    Returns:
        dict: 完整报价单
    """
    # 工艺分类
    process_type = classify_process(material)

    # 工时估算
    total_hours = estimate_hours(process_type, weight_kg) * quantity

    # 材料成本估算（基于重量）
    material_cost_per_unit = int(weight_kg * 2500)

    # 成本计算
    result = calculate_cost(process_type, material_cost_per_unit, total_hours / quantity, quantity)

    # 工序明细
    process_steps = [
        ProcessStepData(
            "原材料切割",
            "cutting",
            0.5 * quantity,
            material_cost_per_unit,
            4000 * quantity
        ),
        ProcessStepData(
            "CNC粗加工",
            "cnc_rough",
            2.0 * quantity,
            0,
            16000 * quantity
        ),
        ProcessStepData(
            "CNC精加工",
            "cnc_finish",
            3.0 * quantity,
            0,
            24000 * quantity
        ),
        ProcessStepData(
            "去毛刺",
            "deburr",
            0.5 * quantity,
            0,
            4000 * quantity
        ),
        ProcessStepData(
            "质量检测",
            "qc",
            0.5 * quantity,
            0,
            4000 * quantity
        ),
    ]

    return {
        "material": material,
        "process_category": process_type,
        "process_steps": [vars(s) for s in process_steps],
        "total_material_cost": result.material_cost,
        "total_labor_cost": result.labor_cost,
        "total_hours": result.total_hours,
        "estimated_price": result.estimated_price,
        "lead_time_days": result.lead_time_days,
        "notes": "以上为参考报价，实际价格根据图纸复杂度和数量调整。"
    }