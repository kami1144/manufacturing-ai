"""
Blueprint Parser Module - 蓝图解析模块
从 OCR 文字提取结构化参数，用于报价流程
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# =====================
# 常量定义
# =====================

# 材料密度表 (g/cm3)
MATERIAL_DENSITY = {
    "sus304": 7.93,
    "sus303": 7.93,
    "sus316": 7.93,
    "sec": 7.85,
    "secc": 7.85,
    "spcc": 7.85,
    "adc12": 2.74,
    "a5052": 2.68,
    "5052": 2.68,
    "6061": 2.70,
    "7075": 2.80,
}


# =====================
# Dataclass 定义
# =====================

@dataclass
class BlueprintSpec:
    """蓝图规格结构化数据"""
    material: str = ""           # 材质，如 SUS304
    quantity: int = 0           # 数量
    dimensions: str = ""        # 尺寸描述，如 Ø25×50mm
    tolerance: str = ""          # 公差，如 ±0.01mm
    surface: str = ""           # 表面处理/粗糙度，如 Ra0.8
    weight_kg: Optional[float] = None  # 重量
    process_type: Optional[str] = None # 工艺类型
    raw_text: str = ""          # 原始 OCR 文字


# =====================
# 解析函数
# =====================

def parse_material(text: str) -> str:
    """解析材质"""
    # 材质模式
    material_patterns = [
        r"SUS304",
        r"SUS303",
        r"SUS316",
        r"SUS201",
        r"SUS202",
        r"SECC",
        r"SPCC",
        r"ADC12",
        r"A5052",
        r"5052",
        r"6061",
        r"7075",
    ]

    for pattern in material_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            # 标准化材质名称
            upper = pattern.upper()
            if upper.startswith("SUS"):
                return upper
            elif upper in ("SECC", "SPCC"):
                return upper
            elif upper == "ADC12":
                return "ADC12"
            elif upper in ("A5052", "5052"):
                return "A5052"
            elif upper in ("6061", "7075"):
                return upper

    return ""


def parse_quantity(text: str) -> int:
    """解析数量"""
    # 匹配数字 + 单位
    patterns = [
        r"需要?\s*(\d+)\s*(?:個|个|件|pcs?|pieces?|枚|P)",
        r"(\d+)\s*(?:個|个|件|pcs?|pieces?|枚|P)",
        r"數量[：:]\s*(\d+)",
        r"QTY[：:]\s*(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))

    return 0


def parse_dimensions(text: str) -> str:
    """解析尺寸"""
    # 尺寸模式
    patterns = [
        r"Ø\s*(\d+(?:\.\d+)?)\s*(?:mm|m)?\s*[×xX]\s*(\d+(?:\.\d+)?)\s*(?:mm|m)?",  # Ø25×50mm
        r"(\d+(?:\.\d+)?)\s*[×xX]\s*(\d+(?:\.\d+)?)\s*[×xX]\s*(\d+(?:\.\d+)?)\s*(?:mm|m)?",  # 150×80×50mm
        r"L\s*(\d+(?:\.\d+)?)\s*[×xX]\s*W\s*(\d+(?:\.\d+)?)\s*[×xX]\s*H\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:mm|m)\s*[×xX]\s*(\d+(?:\.\d+)?)\s*(?:mm|m)",  # 30×30mm
        r"尺寸[为：]?\s*(\d+(?:\.\d+)?)\s*[×xX]\s*(\d+(?:\.\d+)?)\s*(?:mm|m)?",  # 尺寸为30×30mm
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            dims = match.groups()
            if len(dims) == 2:
                return f"{dims[0]}×{dims[1]}mm"
            elif len(dims) == 3:
                return f"{dims[0]}×{dims[1]}×{dims[2]}mm"

    return ""


def parse_tolerance(text: str) -> str:
    """解析公差"""
    pattern = r"±\s*(\d+(?:\.\d+)?)\s*(?:mm|m)?"
    match = re.search(pattern, text)
    if match:
        return f"±{match.group(1)}mm"
    return ""


def parse_surface(text: str) -> str:
    """解析表面粗糙度"""
    patterns = [
        r"Ra\s*(\d+(?:\.\d+)?)",
        r"Ry\s*(\d+(?:\.\d+)?)",
        r"Rz\s*(\d+(?:\.\d+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"Ra{match.group(1)}"

    return ""


def parse_weight(text: str) -> Optional[float]:
    """解析重量"""
    # kg 模式
    patterns = [
        r"(\d+(?:\.\d+)?)\s*kg",
        r"(\d+(?:\.\d+)?)\s*千克",
        r"(\d+)\s*g\s*$",  # 克
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            if "g" in pattern.lower() and "kg" not in pattern.lower():
                # 克转换为 kg
                return value / 1000
            return value

    return None


def infer_process_type(material: str) -> Optional[str]:
    """根据材质推断工艺类型"""
    if not material:
        return None

    upper = material.upper()

    if upper.startswith("SUS"):
        return "CNC加工"
    elif upper in ("SECC", "SPCC"):
        return "钣金加工"
    elif upper in ("ADC12", "A5052"):
        return "压铸"
    elif upper in ("6061", "7075"):
        return "CNC加工"

    return None


def estimate_weight(dimensions: str, material: str, raw_text: str = "") -> Optional[float]:
    """
    根据尺寸和材质估算重量
    dimensions: 尺寸字符串，如 "25×50mm" (from parse_dimensions output)
    material: 材质，如 "SUS304"
    raw_text: 原始 OCR 文字，用于检测圆柱符号 Ø
    """
    if not material:
        return None

    # 获取密度
    density = MATERIAL_DENSITY.get(material.lower())
    if not density:
        return None

    # 解析尺寸
    dims = re.findall(r"(\d+(?:\.\d+)?)", dimensions)
    if not dims:
        return None

    # 检测是否为圆柱体：检查原始文字中是否有 Ø
    is_cylinder = "Ø" in raw_text or "φ" in raw_text or "Φ" in raw_text

    # 计算体积 (cm3)
    # 假设圆柱体或长方体
    try:
        if is_cylinder and len(dims) >= 2:
            # 圆柱体: Ød×h（从 raw_text 检测）
            d = float(dims[0])  # 直径 mm
            h = float(dims[1])   # 高度 mm
            volume_cm3 = 3.14159 * (d / 10) ** 2 * (h / 10)  # cm3
        elif len(dims) >= 3:
            # 长方体: L×W×H
            l = float(dims[0])
            w = float(dims[1])
            h = float(dims[2])
            volume_cm3 = (l / 10) * (w / 10) * (h / 10)
        elif len(dims) >= 2:
            # 2D 薄板：假设默认厚度 5mm
            l = float(dims[0])
            w = float(dims[1])
            volume_cm3 = (l / 10) * (w / 10) * 0.5
        else:
            return None

        # 计算重量 (kg)
        weight_g = volume_cm3 * density
        return round(weight_g / 1000, 3)

    except (ValueError, IndexError):
        return None


# =====================
# 主解析器类
# =====================

class BlueprintParser:
    """蓝图解析器"""

    def parse(self, ocr_text: str) -> BlueprintSpec:
        """
        解析 OCR ���字��结构化参数

        Args:
            ocr_text: OCR 识别的原始文字

        Returns:
            BlueprintSpec: 结构化参数
        """
        text = ocr_text.strip()

        # 解析各字段
        material = parse_material(text)
        quantity = parse_quantity(text)
        dimensions = parse_dimensions(text)
        tolerance = parse_tolerance(text)
        surface = parse_surface(text)
        weight = parse_weight(text)

        # 推断工艺类型
        process_type = infer_process_type(material)

        # 如果没有解析到重量，尝试估算
        if weight is None and dimensions and material:
            weight = estimate_weight(dimensions, material, text)

        return BlueprintSpec(
            material=material,
            quantity=quantity,
            dimensions=dimensions,
            tolerance=tolerance,
            surface=surface,
            weight_kg=weight,
            process_type=process_type,
            raw_text=text,
        )


# =====================
# 测试代码
# =====================

if __name__ == "__main__":
    import json

    # 测试用例
    test_cases = [
        # 用例1: 完整信息
        """
        图纸内容：
        材质：SUS304
        数量：100個
        尺寸：Ø25×50mm
        公差：±0.01mm
        粗糙度：Ra0.8
        重量：1.2kg
        """,
        # 用例2: 只有尺寸和材质，无数量
        """
        材料：SECC
        规格：150×80×50mm
        QTY: 50
        """,
        # 用例3: 简单文字
        """
        需要100件，A5052材质，尺寸为30×30mm
        """,
    ]

    parser = BlueprintParser()

    print("=" * 60)
    print("Blueprint Parser 测试")
    print("=" * 60)

    for i, raw_text in enumerate(test_cases, 1):
        print(f"\n--- 测试用例 {i} ---")
        print(f"原始OCR文字:\n{raw_text.strip()}")

        spec = parser.parse(raw_text)

        print(f"\n解析结果:")
        print(f"  material: {spec.material}")
        print(f"  quantity: {spec.quantity}")
        print(f"  dimensions: {spec.dimensions}")
        print(f"  tolerance: {spec.tolerance}")
        print(f"  surface: {spec.surface}")
        print(f"  weight_kg: {spec.weight_kg}")
        print(f"  process_type: {spec.process_type}")

        print()

    print("=" * 60)
    print("测试完成")
    print("=" * 60)