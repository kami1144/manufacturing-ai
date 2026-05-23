"""
LINE API - FastAPI 路由

功能：
- LINE Webhook 端点
- LINE Bot 健康检查
- 多工厂支持
"""

import os
import json
from fastapi import APIRouter, Request, HTTPException, Response
from typing import Optional

from app.modules.line_module import line_bot, LINEWebhookHandler
from app.line_config import line_config

router = APIRouter(prefix="/line", tags=["line"])


@router.get("/webhook")
async def line_webhook_verify(request: Request):
    """LINE Webhook 验证（LINE 平台用 GET 请求验证）"""
    challenge = request.query_params.get("challenge", "")
    if challenge:
        return Response(content=challenge, media_type="text/plain")
    return {"status": "ok"}


@router.post("/webhook")
async def line_webhook(request: Request):
    """LINE Webhook 端点

    处理 LINE 平台发送的 Webhook 事件：
    - 制造业 Bot（LINE_CHANNEL_SECRET）
    - 不动产 Bot（REALESTATE_LINE_CHANNEL_SECRET）
    """
    # 获取请求体
    body = await request.body()
    body_json = json.loads(body) if body else {}

    # 获取签名
    signature = request.headers.get("X-Line-Signature", "")

    # 根据签名判断是哪个 Bot
    import hmac, hashlib
    manufacturing_secret = os.getenv("LINE_CHANNEL_SECRET", "")
    realestate_secret = os.getenv("REALESTATE_LINE_CHANNEL_SECRET", "")

    bot_type = None
    if manufacturing_secret and signature:
        key = manufacturing_secret.encode()
        expected = hmac.new(key, body, hashlib.sha256).digest()
        if hmac.compare_digest(expected, bytes.fromhex(signature)):
            bot_type = "manufacturing"

    if not bot_type and realestate_secret and signature:
        key = realestate_secret.encode()
        expected = hmac.new(key, body, hashlib.sha256).digest()
        if hmac.compare_digest(expected, bytes.fromhex(signature)):
            bot_type = "realestate"

    # 开发环境跳过签名验证
    if not signature or bot_type is None:
        if line_config.is_development:
            # 开发环境：检查 events 判断类型
            events = body_json.get("events", [])
            if events and not bot_type:
                bot_type = "manufacturing"  # default
        else:
            raise HTTPException(status_code=401, detail="Invalid signature")

    # ── 路由到对应 Bot ───────────────────────────────────
    if bot_type == "realestate":
        return await _handle_realestate_webhook(body, body_json, signature)
    else:
        return await _handle_manufacturing_webhook(body, body_json, signature)


async def _handle_manufacturing_webhook(body: bytes, body_json: dict, signature: str):
    """处理制造业 Bot 事件"""
    webhook_handler = LINEWebhookHandler()
    if signature and not webhook_handler.verify_signature(body, signature):
        print("[WARN] Invalid LINE signature (manufacturing)")
        if not line_config.is_development:
            raise HTTPException(status_code=401, detail="Invalid signature")

    events = webhook_handler.parse_events(body_json)
    if not events:
        return {"status": "ok", "message": "No events"}

    results = []
    for event in events:
        event_type = webhook_handler.get_event_type(event)
        if event_type != "message":
            results.append({"type": event_type, "handled": False})
            continue

        user_id = webhook_handler.extract_user_id(event)
        reply_token = webhook_handler.get_reply_token(event)
        if not user_id or not reply_token:
            results.append({"type": "message", "handled": False})
            continue

        message_type = event.get("message", {}).get("type", "")

        if message_type == "text":
            text = webhook_handler.extract_message_text(event)
            if text:
                response = await line_bot.process_message(user_id, text, reply_token)
                if isinstance(response, dict):
                    await line_bot.reply_message(reply_token, [response])
                else:
                    await line_bot.reply_message(
                        reply_token,
                        [{"type": "text", "text": str(response)}],
                    )
                results.append({"type": "message", "message_type": "text", "user_id": user_id, "handled": True})

        elif message_type == "image":
            message_id = webhook_handler.extract_message_id(event)
            if message_id:
                try:
                    image_data = await line_bot.download_line_image(message_id)
                    msg = await line_bot.process_blueprint_image(image_data)
                    await line_bot.reply_message(reply_token, [msg])
                    results.append({"type": "message", "message_type": "image", "user_id": user_id, "handled": True})
                except Exception as e:
                    print(f"[ERROR] Image quote error: {e}")
                    await line_bot.reply_message(reply_token, [{"type": "text", "text": "⚠️ 图片处理失败，请稍后再试。"}])
                    results.append({"type": "message", "message_type": "image", "handled": False, "error": str(e)})
        else:
            results.append({"type": "message", "message_type": message_type, "handled": False})

    return {"status": "ok", "results": results}


async def _handle_realestate_webhook(body: bytes, body_json: dict, signature: str):
    """处理不动产 Bot 事件"""
    from app.modules.realestate.line_module import handle_line_event, reply_message as realestate_reply

    events = body_json.get("events", [])
    for event_data in events:
        try:
            class Event:
                def __init__(self, data):
                    self.type = data.get("type")
                    self.reply_token = data.get("replyToken")
                    self.source = data.get("source", {})
                    if data.get("message"):
                        self.message = type("Message", (), data.get("message", {}))()

            event = Event(event_data)
            response_text = handle_line_event(event)
            if response_text and event.reply_token:
                try:
                    realestate_reply(event.reply_token, response_text)
                except Exception as e:
                    print(f"[WARN] Realestate reply failed: {e}")
        except Exception as e:
            print(f"[WARN] Realestate event error: {e}")

    return {"status": "ok"}


@router.get("/health")
async def line_health():
    """LINE Bot 健康检查"""
    return {
        "status": "ok",
        "service": "line",
        "configured": line_config.is_configured,
        "environment": line_config.ENVIRONMENT,
    }


@router.get("/config")
async def line_config_info():
    """获取 LINE 配置信息"""
    return line_config.get_safe_config()


@router.post("/reply")
async def send_line_message(message: dict):
    """主动发送消息给用户（需要 user_id）"""
    user_id = message.get("user_id")
    text = message.get("text")

    if not user_id or not text:
        raise HTTPException(status_code=400, detail="user_id and text required")

    if not line_config.LINE_CHANNEL_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="LINE not configured")

    # 使用 LINE Push API 发送消息
    import httpx
    url = "https://api.line.me/v2/bot/message/push"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {line_config.LINE_CHANNEL_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "to": user_id,
                    "messages": [{"type": "text", "text": text}],
                },
            )
            response.raise_for_status()
            return {"status": "ok", "sent": True}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=500, detail=f"LINE API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))