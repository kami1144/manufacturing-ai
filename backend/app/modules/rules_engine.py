"""
报价规则引擎 - 可配置的规则驱动报价系统

功能：
- YAML规则文件加载
- 材料→工艺自动分类
- 工时估算（支持配置系数）
- 成本计算（含表面处理、公差、数量折扣）
- 报价生成
- 与现有 quote_module.py 兼容
"""

from dataclasses import dataclass
from typing import Optional, Dict, List
import yaml
from pathlib import Path


@dataclass
class PricingRules:
    """规则配置数据类"""
    material_process_map: Dict[str, str]
    labor_rates: Dict[str, int]
    material_rates: Dict[str, int]
    hour_coefficients: Dict[str, float]
    base_hours: Dict[str, float]
    surface_treatment_surcharge: Dict[str, int]
    tolerance_multipliers: Dict[str, float]
    lead_times: Dict[str, int]
    profit_margin: float
    volume_discounts: List[Dict[str, float]]


class RulesEngine:
    """规则引擎核心类"""

    def __init__(self, rules: Optional[PricingRules] = None):
        self.rules = rules or get_default_rules()

    @classmethod
    def load_rules(cls, yaml_path: str) -> 'RulesEngine':
        """从YAML文件加载规则，如果文件不存在则返回默认规则"""
        path = Path(yaml_path)
        if not path.exists():
            # 文件不存在，返回默认规则
            return cls(get_default_rules())

        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        rules = PricingRules(
            material_process_map=data.get('material_process_map', {}),
            labor_rates=data.get('labor_rates', {}),
            material_rates=data.get('material_rates', {}),
            hour_coefficients=data.get('hour_coefficients', {}),
            base_hours=data.get('base_hours', {}),
            surface_treatment_surcharge=data.get('surface_treatment_surcharge', {}),
            tolerance_multipliers=data.get('tolerance_multipliers', {}),
            lead_times=data.get('lead_times', {}),
            profit_margin=data.get('profit_margin', 0.15),
            volume_discounts=data.get('volume_discounts', [])
        )
        return cls(rules)

    def classify_process(self, material: str) -> str:
        """根据材料分类工艺类型"""
        return self.rules.material_process_map.get(material, 'cnc_machining')

    def estimate_hours(self, process_type: str, weight_kg: float, quantity: int) -> float:
        """估算工时

        计算公式：基础工时 + (重量 * 系数)
        然后乘以数量因子（批量生产有折扣）
        """
        base = sum(self.rules.base_hours.values())
        coefficient = self.rules.hour_coefficients.get(process_type, 0.05)
        hours = base + (weight_kg * coefficient)
        # 数量超过10台，考虑批量效率
        if quantity > 10:
            hours *= 0.9  # 10% 效率提升
        return hours

    def calculate_cost(
        self,
        process_type: str,
        material_cost: float,
        total_hours: float,
        quantity: int,
        surface_treatment: str = 'none',
        tolerance: str = 'normal'
    ) -> Dict[str, float]:
        """计算成本

        Returns:
            dict: 包含各项成本的字典
                - material_cost: 材料成本
                - labor_cost: 人工成本
                - surface_cost: 表面处理成本
                - tolerance_cost: 公差成本
                - subtotal: 小计
                - profit: 利润
                - total: 总计
        """
        # 材料成本
        mat_rate = self.rules.material_rates.get(process_type, 2000)
        m_cost = material_cost * mat_rate

        # 人工成本
        labor_rate = self.rules.labor_rates.get(process_type, 6000)
        l_cost = total_hours * labor_rate

        # 表面处理成本
        surf_rate = self.rules.surface_treatment_surcharge.get(surface_treatment, 0)
        s_cost = surf_rate * quantity

        # 公差成本
        tol_mult = self.rules.tolerance_multipliers.get(tolerance, 1.0)
        tol_cost = (m_cost + l_cost) * (tol_mult - 1.0)

        # 小计
        subtotal = m_cost + l_cost + s_cost + tol_cost

        # 利润
        profit = subtotal * self.rules.profit_margin

        # 总计
        total = subtotal + profit

        return {
            'material_cost': m_cost,
            'labor_cost': l_cost,
            'surface_cost': s_cost,
            'tolerance_cost': tol_cost,
            'subtotal': subtotal,
            'profit': profit,
            'total': total
        }

    def apply_discount(self, quantity: int, base_price: float) -> float:
        """应用数量折扣"""
        discount = 0.0
        for rule in sorted(self.rules.volume_discounts, key=lambda x: x['min_quantity']):
            if quantity >= rule['min_quantity']:
                discount = rule['discount']
        return base_price * (1.0 - discount)

    def generate_quote(
        self,
        material: str,
        weight_kg: float,
        quantity: int,
        surface_treatment: str = 'none',
        tolerance: str = 'normal'
    ) -> Dict:
        """生成完整报价"""
        # 1. 工艺分类
        process_type = self.classify_process(material)

        # 2. 估算工时
        total_hours = self.estimate_hours(process_type, weight_kg, quantity)

        # 3. 计算材料成本
        material_cost = weight_kg

        # 4. 计算各项成本
        costs = self.calculate_cost(
            process_type=process_type,
            material_cost=material_cost,
            total_hours=total_hours,
            quantity=quantity,
            surface_treatment=surface_treatment,
            tolerance=tolerance
        )

        # 5. 应用折扣
        final_price = self.apply_discount(quantity, costs['total'])

        # 6. 计算单价
        unit_price = final_price / quantity if quantity > 0 else final_price

        # 7. 交期
        lead_time = self.rules.lead_times.get(process_type, 7)

        return {
            'material': material,
            'process_type': process_type,
            'quantity': quantity,
            'weight_kg': weight_kg,
            'surface_treatment': surface_treatment,
            'tolerance': tolerance,
            'total_hours': total_hours,
            'lead_time_days': lead_time,
            'material_cost': costs['material_cost'],
            'labor_cost': costs['labor_cost'],
            'surface_cost': costs['surface_cost'],
            'tolerance_cost': costs['tolerance_cost'],
            'subtotal': costs['subtotal'],
            'profit': costs['profit'],
            'discount_rate': self._get_discount(quantity),  # 折扣率 0.1 = 10%
            'unit_price': unit_price,
            'total_price': final_price
        }

    def _get_discount(self, quantity: int) -> float:
        """获取当前数量的折扣率"""
        discount = 0.0
        for rule in sorted(self.rules.volume_discounts, key=lambda x: x['min_quantity']):
            if quantity >= rule['min_quantity']:
                discount = rule['discount']
        return discount

    def get_lead_time(self, process_type: str) -> int:
        """获取交期"""
        return self.rules.lead_times.get(process_type, 7)


def get_default_rules() -> PricingRules:
    """返回内置默认规则"""
    return PricingRules(
        material_process_map={
            'SUS304': 'cnc_machining',
            'SUS316': 'cnc_machining',
            'SECC': 'sheet_metal',
            'SPCC': 'sheet_metal',
            'SGCC': 'sheet_metal',
            'ADC12': 'die_casting',
            'A383': 'die_casting'
        },
        labor_rates={
            'cnc_machining': 8000,
            'sheet_metal': 6000,
            'die_casting': 10000,
            'surface_treatment': 3000
        },
        material_rates={
            'cnc_machining': 2500,
            'sheet_metal': 2000,
            'die_casting': 3000
        },
        hour_coefficients={
            'cnc_machining': 0.05,
            'sheet_metal': 0.02,
            'die_casting': 0.08
        },
        base_hours={
            'cutting': 0.5,
            'cnc_rough': 2.0,
            'cnc_finish': 3.0,
            'deburr': 0.5,
            'qc': 0.5
        },
        surface_treatment_surcharge={
            '研磨': 2000,
            '镀镍': 5000,
            '阳极氧化': 8000,
            '喷漆': 3000,
            'none': 0
        },
        tolerance_multipliers={
            'normal': 1.0,
            'high': 1.2,
            'ultra': 1.5
        },
        lead_times={
            'cnc_machining': 7,
            'sheet_metal': 5,
            'die_casting': 14
        },
        profit_margin=0.15,
        volume_discounts=[
            {'min_quantity': 100, 'discount': 0.10},
            {'min_quantity': 500, 'discount': 0.15},
            {'min_quantity': 1000, 'discount': 0.20}
        ]
    )


# 默认规则加载器
_default_rules: Optional[RulesEngine] = None


def get_rules_engine() -> RulesEngine:
    """获取默认规则引擎（单例）"""
    global _default_rules
    if _default_rules is None:
        _default_rules = RulesEngine(get_default_rules())
    return _default_rules