"""
Schemas for Blueprint Analysis workflow (vision + feature extraction)
Step 1-2 of the 6-step pipeline.
"""

from pydantic import BaseModel, field_validator
from typing import Optional


class VisionResult(BaseModel):
    """Step 1: Raw OCR/Vision output (flexible, handles imperfect AI output)."""
    材质: str = "未标注"
    数量: str = "1"
    主要尺寸: str = "未标注"
    重量kg: str = "未标注"
    板厚mm: str = "未标注"
    孔数量: str = "0"
    对称性: str = "未标注"
    结构类型: str = "未标注"
    工艺要求: str = "未标注"
    公差要求: str = "未标注"
    表面处理: str = "未标注"

    @field_validator("数量", "孔数量", mode="before")
    @classmethod
    def coerce_numeric(cls, v):
        if isinstance(v, (int, float)):
            return str(v)
        return v or "0"

    @field_validator("重量kg", mode="before")
    @classmethod
    def coerce_float(cls, v):
        if isinstance(v, (int, float)):
            return str(v)
        return v or "0"


class BlueprintFeatures(BaseModel):
    """Step 2: Structured feature extraction (cleaned, typed)."""
    material: str          # 材质，如 "SUS304"
    quantity: int           # 数量（件）
    dimensions: str         # 主要尺寸，如 "150x80x50mm"
    weight_kg: float        # 重量 kg
    tolerance: str          # 公差要求
    surface: str            # 表面处理
    thickness: str          # 板厚
    hole_count: int         # 孔数量
    symmetry: str           # 对称性
    structure_type: str     # 结构类型

    # 原始数据溯源
    raw_vision: Optional[dict] = None  # 原始 VisionResult


class BlueprintSpec(BaseModel):
    """Complete blueprint specification after Step 1-2."""
    vision: VisionResult
    features: BlueprintFeatures
    ocr_confidence: float = 0.0
    ocr_language: str = "unknown"
