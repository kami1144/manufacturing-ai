"""
AI报价系统 API

功能：
- 上传图纸用于报价
- 报价计算（mock实现）
- 生成完整报价单
"""

from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List
import uuid

router = APIRouter()

# ── Request/Response Models ──────────────────────────────


class ProcessCategory:
    """工艺分类枚举"""
    CNC_MACHINING = "cnc_machining"           # CNC加工
    SHEET_METAL = "sheet_metal"               # 钣金
    CASTING = "casting"                       # 铸造
    FORGING = "forging"                      # 锻造
    SURFACE_TREATMENT = "surface_treatment"   # 表面处理
    ASSEMBLY = "assembly"                      # 组装
    INSPECTION = "inspection"                 # 检测


class ProcessStep(BaseModel):
    """工序明细"""
    step: str              # 工序名称
    process_type: str       # 工艺类型
    estimated_hours: float  # 估算工时（小时）
    material_cost: float    # 材料成本（日元）
    labor_cost: float       # 人工成本（日元）


class QuoteResponse(BaseModel):
    """报价响应"""
    quote_id: str
    filename: str
    material: str
    process_category: str
    process_steps: List[ProcessStep]
    total_material_cost: float
    total_labor_cost: float
    total_hours: float
    estimated_price: float   # 预估报价（日元，含利润）
    lead_time_days: int      # 交期（天）
    notes: str


class GenerateQuoteRequest(BaseModel):
    """生成报价请求"""
    filename: Optional[str] = "blueprint.pdf"
    material: Optional[str] = "SUS304"
    weight_kg: Optional[float] = 1.0
    surface_area: Optional[float] = None
    tolerance: Optional[str] = "normal"
    quantity: Optional[int] = 1
    delivery: Optional[str] = "standard"


# ── Mock报价规则 ────────────────────────────────────────


PROCESS_RULES = {
    "cnc_machining": {
        "base_rate": 8000,      # 每小时日元
        "complexity_multiplier": 1.5,
        "lead_time_base": 5,
    },
    "sheet_metal": {
        "base_rate": 6000,
        "complexity_multiplier": 1.2,
        "lead_time_base": 3,
    },
    "surface_treatment": {
        "base_rate": 3000,
        "complexity_multiplier": 1.0,
        "lead_time_base": 2,
    },
    "die_casting": {
        "base_rate": 10000,
        "complexity_multiplier": 1.3,
        "lead_time_base": 10,
    },
}

SAMPLE_QUOTE = {
    "material": "SUS304 Stainless Steel",
    "process_category": "cnc_machining",
    "process_steps": [
        {"step": "原材料切割", "process_type": "cutting", "estimated_hours": 0.5, "material_cost": 2500, "labor_cost": 4000},
        {"step": "CNC粗加工", "process_type": "cnc_rough", "estimated_hours": 2.0, "material_cost": 0, "labor_cost": 16000},
        {"step": "CNC精加工", "process_type": "cnc_finish", "estimated_hours": 3.0, "material_cost": 0, "labor_cost": 24000},
        {"step": "去毛刺", "process_type": "deburr", "estimated_hours": 0.5, "material_cost": 0, "labor_cost": 4000},
        {"step": "质量检测", "process_type": "qc", "estimated_hours": 0.5, "material_cost": 0, "labor_cost": 4000},
    ],
    "total_material_cost": 2500,
    "total_labor_cost": 52000,
    "total_hours": 6.5,
    "estimated_price": 62000,   # 含15%利润
    "lead_time_days": 7,
    "notes": "以上为参考报价，实际价格根据图纸复杂度和数量调整。"
}


# ── API Endpoints ───────────────────────────────────────


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "quote"}


@router.post("/upload")
async def upload_for_quote(file: UploadFile = File(...)):
    """
    上传图纸用于报价，返回quote_id
    """
    quote_id = str(uuid.uuid4())
    return {
        "quote_id": quote_id,
        "filename": file.filename,
        "status": "uploaded",
        "message": "图纸已上传，请提交报价信息"
    }


@router.post("/calculate", response_model=QuoteResponse)
async def calculate_quote(req: Optional[dict] = None):
    """
    报价计算（mock实现）

    实际流程：
    1. 提取图纸信息（材质/尺寸/工艺）
    2. 分类工艺类型
    3. 估算工时
    4. 计算材料+人工+利润
    5. 生成报价单
    """
    # Mock数据返回
    return QuoteResponse(
        quote_id=str(uuid.uuid4()),
        filename=req.get("filename", "blueprint.pdf") if req else "blueprint.pdf",
        **SAMPLE_QUOTE
    )


@router.post("/generate")
async def generate_quote(blueprint_data: Optional[dict] = None):
    """
    生成完整报价单（mock）

    blueprint_data 包含：
    - material: 材质
    - weight_kg: 重量(kg)
    - surface_area: 表面积(cm2)
    - tolerance: 公差要求
    - quantity: 数量
    - delivery: 交期要求
    """
    filename = blueprint_data.get("filename", "blueprint.pdf") if blueprint_data else "blueprint.pdf"
    material = blueprint_data.get("material", "SUS304") if blueprint_data else "SUS304"

    # 根据材质判断工艺类型
    material_upper = material.upper()
    if "SUS" in material_upper or "304" in material_upper or "316" in material_upper:
        process_category = "cnc_machining"
        base_rate = 8000
        lead_time = 7
    elif "SECC" in material_upper or "SPCC" in material_upper or "SGCC" in material_upper:
        process_category = "sheet_metal"
        base_rate = 6000
        lead_time = 5
    elif "ADC" in material_upper or "A383" in material_upper:
        process_category = "die_casting"
        base_rate = 10000
        lead_time = 14
    else:
        process_category = "cnc_machining"
        base_rate = 8000
        lead_time = 7

    quantity = blueprint_data.get("quantity", 1) if blueprint_data else 1
    weight = blueprint_data.get("weight_kg", 1.0) if blueprint_data else 1.0

    # 计算成本
    material_cost = int(2500 * quantity)
    labor_cost = int(52000 * quantity)
    management_fee = int(4000 * quantity)

    subtotal = material_cost + labor_cost + management_fee
    unit_price = int(subtotal * 1.15 / 1000) * 1000  # 含15%利润

    return {
        "quote_id": str(uuid.uuid4()),
        "filename": filename,
        "process_category": process_category,
        "pricing": {
            "unit_price": unit_price,
            "moq_price": int(unit_price * 0.9),      # 批量起始价（10%折扣）
            "mass_production_price": int(unit_price * 0.75),  # 量产价（25%折���）
            "currency": "JPY",
        },
        "breakdown": {
            "material": material_cost,
            "processing": labor_cost,
            "management": management_fee,
            "subtotal": subtotal,
            "profit_margin": 0.15,
        },
        "validity_days": 30,
        "payment_terms": "出货后30日付款",
        "lead_time_days": lead_time,
        "sample_production_days": lead_time * 2,
    }