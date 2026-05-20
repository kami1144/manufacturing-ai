"""
Knowledge Base - 房源知识库

功能：
- 结构化房源数据（非向量）
- 包含房源基本信息、费用计算器、收益率计算

数据结构：
- 房源列表
- 费用计算
- 收益率计算
"""

from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Property:
    """房源信息"""
    id: str
    name: str
    address: str
    area: float  # 面积（坪）
    price: int  # 价格（万円）
    yield_percent: float  # 利回り（%）
    management_fee: int  # 管理费（月额，円）
    repair_cost: int  # 修缮积立金（月额，円）
    station: str  # 最近车站
    walk_minutes: int  # 徒步分钟
    build_year: int  # 建成年份
    property_type: str  # 类型：公寓/一户建/MANSION


@dataclass
class PropertyFee:
    """费用明细"""
    price: int  # 房价（万円）
    deposit: int  # 敷金（万円）
    key_money: int  # 礼金（万円）
    management_fee: int  # 管理费（月额，円）
    repair_reserve: int  # 修缮积立金（月额，円）
    fire_insurance: int  # 火灾保险（年额，円）
    earthquake_insurance: int  # 地震保险（年额，円）
    fixed_asset_tax: int  # 固定资产税（年额，円）
    city_planning_tax: int  # 都市计划税（年额，円）


# 示例房源数据
SAMPLE_PROPERTIES = [
    Property(
        id="prop_001",
        name="新宿物件",
        address="东京都新宿区西新宿1-1-1",
        area=25.0,
        price=3500,
        yield_percent=5.2,
        management_fee=8500,
        repair_cost=3200,
        station="JR新宿站",
        walk_minutes=5,
        build_year=2015,
        property_type="MANSION"
    ),
    Property(
        id="prop_002",
        name="涩谷物件",
        address="东京都涩谷区涩谷2-2-2",
        area=20.0,
        price=4200,
        yield_percent=4.8,
        management_fee=7200,
        repair_cost=2800,
        station="JR涩谷站",
        walk_minutes=8,
        build_year=2018,
        property_type="MANSION"
    ),
    Property(
        id="prop_003",
        name="大阪难波物件",
        address="大阪府大阪市中央区难波3-3-3",
        area=30.0,
        price=2800,
        yield_percent=6.1,
        management_fee=6200,
        repair_cost=2500,
        station="Osaka Metro 难波站",
        walk_minutes=3,
        build_year=2010,
        property_type="公寓"
    ),
]


def get_property(property_id: str) -> Optional[Property]:
    """
    获取房源

    Args:
        property_id: 房源 ID

    Returns:
        房源信息，或 None
    """
    for prop in SAMPLE_PROPERTIES:
        if prop.id == property_id:
            return prop
    return None


def search_properties(
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    min_yield: Optional[float] = None,
    area: Optional[str] = None,
) -> List[Property]:
    """
    搜索房源

    Args:
        min_price: 最低价格（万円）
        max_price: 最高价格（万円）
        min_yield: 最低利回り（%）
        area: 区域（东京/大阪）

    Returns:
        匹配的房源列表
    """
    results = SAMPLE_PROPERTIES

    if min_price is not None:
        results = [p for p in results if p.price >= min_price]

    if max_price is not None:
        results = [p for p in results if p.price <= max_price]

    if min_yield is not None:
        results = [p for p in results if p.yield_percent >= min_yield]

    if area:
        area_lower = area.lower()
        results = [
            p for p in results
            if area_lower in p.address.lower()
        ]

    return results


def calculate_total_income(property_id: str) -> Optional[Dict]:
    """
    计算年收入

    Args:
        property_id: 房源 ID

    Returns:
        收入明细
    """
    prop = get_property(property_id)
    if not prop:
        return None

    # 月租金
    monthly_rent = int(prop.price * prop.yield_percent / 100 / 12)

    # 年租金
    annual_rent = monthly_rent * 12

    # 费用
    annual_mgmt = prop.management_fee * 12
    annual_repair = prop.repair_cost * 12

    # 实际收入
    actual_income = annual_rent - annual_mgmt - annual_repair

    # 实质利回り
    actual_yield = (actual_income / prop.price / 10000) * 100 if prop.price > 0 else 0

    return {
        "property_id": property_id,
        "monthly_rent": monthly_rent,
        "annual_rent": annual_rent,
        "annual_mgmt_fee": annual_mgmt,
        "annual_repair": annual_repair,
        "actual_income": actual_income,
        "actual_yield": round(actual_yield, 2),
    }


def calculate_initial_cost(price: int, deposit_months: int = 1, key_money_months: int = 1) -> PropertyFee:
    """
    计算初期费用

    Args:
        price: 房价（万円）
        deposit_months: 敷金月数
        key_money_months: 礼金月数

    Returns:
        费用明细
    """
    # 估算月租金（简单按 5% 利回り）
    monthly_rent = int(price * 5 / 100 / 12)

    return PropertyFee(
        price=price,
        deposit=monthly_rent * deposit_months,
        key_money=monthly_rent * key_money_months,
        management_fee=int(monthly_rent * 0.1) if monthly_rent > 0 else 5000,
        repair_reserve=int(monthly_rent * 0.05) if monthly_rent > 0 else 2000,
        fire_insurance=20000,
        earthquake_insurance=15000,
        fixed_asset_tax=int(price * 0.14 / 100),  # 固定资产税估算
        city_planning_tax=int(price * 0.03 / 100),  # 都市计划税估算
    )


def format_property_for_line(prop: Property) -> str:
    """
    格式化为 LINE 消息

    Args:
        prop: 房源信息

    Returns:
        格式化的消息
    """
    lines = [
        f"📍 {prop.name}",
        f"  地址：{prop.address}",
        f"  面积：{prop.area} 坪",
        f"  价格：{prop.price} 万円",
        f"  利回り：{prop.yield_percent}%",
        f"  管理费：{prop.management_fee:,} 円/月",
        f"  修缮费：{prop.repair_cost:,} 円/月",
        f"  最近站：{prop.station}（徒步{prop.walk_minutes}分钟）",
        f"  房龄：{datetime.now().year - prop.build_year}年",
    ]
    return "\n".join(lines)


def get_all_properties() -> List[Property]:
    """
    获取所有房源

    Returns:
        房源列表
    """
    return SAMPLE_PROPERTIES