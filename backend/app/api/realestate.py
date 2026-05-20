"""
Realestate API Router - FastAPI 路由

路由：
- /realestate/webhook - LINE Webhook
- /realestate/config - LINE 配置
- /realestate/health - 健康检查
- /realestate/api/property/* - 房源 API

NOTE: 使用 REALESTATE_LINE_* 环境变量，与制造业Bot分离。
"""

import json
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/realestate", tags=["realestate"])


# === LINE Webhook ===

@router.post("/webhook")
async def line_webhook(request: Request):
    """
    LINE Webhook Endpoint

    处理来自 LINE 平台的所有事件。
    """
    # 解析请求体
    body = await request.body()
    signature = request.headers.get("x-line-signature", "")

    # 解析 JSON
    try:
        body_json = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    events = body_json.get("events", [])

    # 处理事件
    for event_data in events:
        try:
            # 创建简单的 Event 对象
            class Event:
                def __init__(self, data):
                    self.type = data.get("type")
                    self.reply_token = data.get("replyToken")
                    self.source = data.get("source", {})
                    if data.get("message"):
                        self.message = type("Message", (), data.get("message", {}))()

            event = Event(event_data)

            # 动态导入避免循环依赖
            from app.modules.realestate.line_module import handle_line_event, reply_message
            response_text = handle_line_event(event)

            if response_text and event.reply_token:
                try:
                    reply_message(event.reply_token, response_text)
                except Exception as e:
                    print(f"[WARN] Failed to reply: {e}")
        except Exception as e:
            print(f"[WARN] Failed to handle event: {e}")

    return JSONResponse(content={"status": "ok"})


@router.get("/webhook")
async def line_webhook_get():
    """
    LINE Webhook GET (验证可用性)
    """
    return {"status": "ok", "message": "Realestate LINE Webhook is active"}


# === Health Check ===

@router.get("/health")
async def line_health():
    """
    LINE 健康检查

    Returns:
        健康状态
    """
    return {"status": "ok", "service": "realestate"}


# === LINE Config ===

@router.get("/config")
async def line_config():
    """
    LINE 配置信息

    Returns:
        LINE 配置
    """
    return {
        "channel_secret_set": bool(os.getenv("REALESTATE_LINE_CHANNEL_SECRET")),
        "channel_access_token_set": bool(os.getenv("REALESTATE_LINE_CHANNEL_ACCESS_TOKEN")),
    }


# === Property API ===

from app.modules.realestate.knowledge.kb import (
    get_property,
    search_properties,
    calculate_total_income,
    calculate_initial_cost,
    format_property_for_line,
    get_all_properties,
)


class PropertySearchRequest(BaseModel):
    """房源搜索请求"""
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_yield: Optional[float] = None
    area: Optional[str] = None


class CalculateCostRequest(BaseModel):
    """费用计算请��"""
    price: int
    deposit_months: int = 1
    key_money_months: int = 1


@router.get("/api/property/list")
async def property_list():
    """
    获取房源列表

    Returns:
        所有房源
    """
    properties = get_all_properties()
    return {
        "count": len(properties),
        "items": [
            {
                "id": p.id,
                "name": p.name,
                "address": p.address,
                "area": p.area,
                "price": p.price,
                "yield": p.yield_percent,
                "station": p.station,
            }
            for p in properties
        ],
    }


@router.get("/api/property/{property_id}")
async def property_detail(property_id: str):
    """
    获取房源详情

    Args:
        property_id: 房源 ID

    Returns:
        房源详情
    """
    prop = get_property(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    income = calculate_total_income(property_id)

    return {
        "id": prop.id,
        "name": prop.name,
        "address": prop.address,
        "area": prop.area,
        "price": prop.price,
        "yield": prop.yield_percent,
        "management_fee": prop.management_fee,
        "repair_cost": prop.repair_cost,
        "station": prop.station,
        "walk_minutes": prop.walk_minutes,
        "build_year": prop.build_year,
        "property_type": prop.property_type,
        "income": income,
    }


@router.post("/api/property/search")
async def property_search(request: PropertySearchRequest):
    """
    搜索房源

    Returns:
        匹配的房源列表
    """
    properties = search_properties(
        min_price=request.min_price,
        max_price=request.max_price,
        min_yield=request.min_yield,
        area=request.area,
    )

    return {
        "count": len(properties),
        "items": [
            {
                "id": p.id,
                "name": p.name,
                "address": p.address,
                "area": p.area,
                "price": p.price,
                "yield": p.yield_percent,
            }
            for p in properties
        ],
    }


@router.post("/api/property/calculate")
async def calculate(request: CalculateCostRequest):
    """
    计算初期费用和收益

    Returns:
        费用和收益明细
    """
    fee = calculate_initial_cost(
        price=request.price,
        deposit_months=request.deposit_months,
        key_money_months=request.key_money_months,
    )

    # 估算月租金
    monthly_rent = int(request.price * 5 / 100 / 12)
    annual_rent = monthly_rent * 12

    return {
        "price": request.price,
        "deposit": fee.deposit,
        "key_money": fee.key_money,
        "management_fee": fee.management_fee,
        "repair_reserve": fee.repair_reserve,
        "fire_insurance": fee.fire_insurance,
        "earthquake_insurance": fee.earthquake_insurance,
        "fixed_asset_tax": fee.fixed_asset_tax,
        "city_planning_tax": fee.city_planning_tax,
        "estimated_monthly_rent": monthly_rent,
        "estimated_annual_rent": annual_rent,
    }


@router.get("/api/property/line/{property_id}")
async def property_line(property_id: str):
    """
    获取 LINE 格式的房源信息

    Args:
        property_id: 房源 ID

    Returns:
        LINE 格式化消息
    """
    prop = get_property(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    return {"text": format_property_for_line(prop)}