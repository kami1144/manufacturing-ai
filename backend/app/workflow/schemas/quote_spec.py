"""
Schemas for Quote workflow step output.
Step 6 of the 6-step pipeline.
"""

from pydantic import BaseModel, field_validator
from typing import List, Optional


class PricingTiers(BaseModel):
    """阶梯价格体系"""
    unit_price: int       # 单价（日元）
    moq_price: int        # 批量起始价
    mass_production_price: int  # 量产价
    currency: str = "JPY"


class CostBreakdown(BaseModel):
    """成本结构"""
    material: int        # 材料费
    processing: int       # 加工费
    management: int      # 管理费
    subtotal: int
    profit_margin: float  # 利润率，如 0.15


class QuoteSpec(BaseModel):
    """Step 6: Complete quote specification."""
    quote_id: str
    filename: str
    material: str
    process_category: str        # 工艺类型: cnc_machining / sheet_metal / casting

    # 价格信息
    pricing: PricingTiers
    breakdown: CostBreakdown

    # 交付信息
    lead_time_days: int
    sample_production_days: Optional[int] = None
    validity_days: int = 30
    payment_terms: str = "出货后30日付款"

    # 状态标记
    has_quote: bool = True
    currency: str = "JPY"

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v):
        # 强制检查货币单位
        allowed = {"JPY", "USD", "CNY", "EUR"}
        if v.upper() not in allowed:
            raise ValueError(f"Currency must be one of {allowed}, got {v}")
        return v.upper()

    @field_validator("lead_time_days")
    @classmethod
    def validate_lead_time(cls, v):
        if v <= 0:
            raise ValueError("lead_time_days must be positive")
        if v > 365:
            raise ValueError("lead_time_days seems unrealistic (>365)")
        return v

    @field_validator("pricing", "breakdown")
    @classmethod
    def validate_positive_prices(cls, v, info):
        # 检查所有价格字段都是正数
        for field_name, field_value in v.model_dump().items():
            if isinstance(field_value, (int, float)) and field_value < 0:
                raise ValueError(f"{info.field_name}.{field_name} must be positive, got {field_value}")
        return v

    def to_line_message(self) -> dict:
        """转换为 LINE Flex Message 格式"""
        pricing = self.pricing
        return {
            "type": "flex",
            "altText": "报价结果",
            "contents": {
                "type": "bubble",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "📋 报价单", "weight": "bold", "size": "lg"}
                    ]
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": f"材质：{self.material}", "wrap": True},
                        {"type": "text", "text": f"工艺：{self.process_category}"},
                        {"type": "separator"},
                        {"type": "text", "text": f"💰 单价：¥{pricing.unit_price:,}/件"},
                        {"type": "text", "text": f"📦 批量价：¥{pricing.moq_price:,}/件 起"},
                        {"type": "text", "text": f"🏭 量产价：¥{pricing.mass_production_price:,}/件"},
                        {"type": "separator"},
                        {"type": "text", "text": f"📅 交期：{self.lead_time_days} 天"},
                        {"type": "text", "text": f"💳 付款：{self.payment_terms}"},
                        {"type": "text", "text": f"⏱️ 有效期：{self.validity_days} 天"},
                        {"type": "separator"},
                        {"type": "text", "text": f"💵 成本明细", "weight": "bold"},
                        {"type": "text", "text": f"材料费：¥{self.breakdown.material:,}"},
                        {"type": "text", "text": f"加工费：¥{self.breakdown.processing:,}"},
                        {"type": "text", "text": f"管理费：¥{self.breakdown.management:,}"},
                    ]
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "⚠️ 此报价为估算值，实际价格可能因图纸复杂度调整", "size": "sm", "color": "#999999", "wrap": True}
                    ]
                }
            }
        }
