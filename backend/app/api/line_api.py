"""
LINE API - FastAPI 路由

功能：
- LINE Webhook 端点
- LINE Bot 健康检查
- 多工厂支持
"""

import os
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
    - 文本消息
    - 图片消息（图纸）
    - 其他消息类型
    """
    # 获取请求体
    body = await request.body()
    body_json = await request.json()

    # 获取签名
    signature = request.headers.get("X-Line-Signature", "")

    # 验证签名
    webhook_handler = LINEWebhookHandler()
    if signature and not webhook_handler.verify_signature(body, signature):
        print("[WARN] Invalid LINE signature")
        # 开发环境下跳过验证
        if not line_config.is_development:
            raise HTTPException(status_code=401, detail="Invalid signature")

    # 解析事件
    events = webhook_handler.parse_events(body_json)
    if not events:
        return {"status": "ok", "message": "No events"}

    # 处理每个事件
    results = []
    for event in events:
        event_type = webhook_handler.get_event_type(event)

        # 忽略非消息事件
        if event_type != "message":
            results.append({"type": event_type, "handled": False})
            continue

        # 提取消息信息
        user_id = webhook_handler.extract_user_id(event)
        reply_token = webhook_handler.get_reply_token(event)

        if not user_id or not reply_token:
            results.append({"type": "message", "handled": False})
            continue

        message_type = event.get("message", {}).get("type", "")

        if message_type == "text":
            text = webhook_handler.extract_message_text(event)
            if text:
                # 处理文本消息
                response = await line_bot.process_message(user_id, text, reply_token)

                # 统一处理返回值：dict → 直接发，str → 包装成 text 消息
                if isinstance(response, dict):
                    await line_bot.reply_message(reply_token, [response])
                else:
                    await line_bot.reply_message(
                        reply_token,
                        [{"type": "text", "text": str(response)}],
                    )

                results.append({
                    "type": "message",
                    "message_type": "text",
                    "user_id": user_id,
                    "handled": True,
                })

        elif message_type == "image":
            message_id = webhook_handler.extract_message_id(event)
            if message_id:
                # 下载图片 → OCR → 提取材质 → 报价 → Flex Message 回复
                try:
                    image_data = await line_bot.download_line_image(message_id)

                    # process_blueprint_image 返回 LINE 消息 dict（直接发送）
                    msg = await line_bot.process_blueprint_image(image_data)
                    await line_bot.reply_message(reply_token, [msg])

                    results.append({
                        "type": "message",
                        "message_type": "image",
                        "user_id": user_id,
                        "handled": True,
                    })
                except Exception as e:
                    print(f"[ERROR] Image quote error: {e}")
                    await line_bot.reply_message(
                        reply_token,
                        [{"type": "text", "text": f"⚠️ 图片处理失败，请稍后再试。"}]
                    )
                    results.append({
                        "type": "message",
                        "message_type": "image",
                        "handled": False,
                        "error": str(e),
                    })
            else:
                results.append({
                    "type": "message",
                    "message_type": "image",
                    "handled": False,
                })

        else:
            results.append({
                "type": "message",
                "message_type": message_type,
                "handled": False,
            })

    return {"status": "ok", "results": results}


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