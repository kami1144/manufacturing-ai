"""
Bot Provider 抽象接口

支持多平台 messaging：Bots (LINE, Slack, Discord, Teams, etc.)

设计：
- BaseBot 定义统一接口
- 各个平台实现具体逻辑
- 使用工厂模式创建 Bot 实例
"""

import abc
import os
from typing import Any, Optional


class BaseBot(abc.ABC):
    """Bot 抽象基类"""

    @abc.abstractmethod
    async def send_message(self, user_id: str, message: dict) -> bool:
        """发送消息给用户"""
        pass

    @abc.abstractmethod
    async def reply_message(self, reply_token: str, message: dict) -> bool:
        """回复消息"""
        pass

    @abc.abstractmethod
    async def download_media(self, media_id: str) -> bytes:
        """下载媒体文件"""
        pass

    @abc.abstractmethod
    def format_flex_message(self, data: dict) -> dict:
        """格式化 Flex Message"""
        pass

    @abc.abstractmethod
    def format_quick_reply(self, options: list[str]) -> dict:
        """格式化 Quick Reply 按钮"""
        pass


class LINEBot(BaseBot):
    """LINE Bot 实现"""

    def __init__(self):
        from app.line_config import line_config
        self.token = line_config.LINE_CHANNEL_ACCESS_TOKEN
        self.secret = line_config.LINE_CHANNEL_SECRET

    async def send_message(self, user_id: str, message: dict) -> bool:
        import httpx
        if not self.token:
            return False

        url = "https://api.line.me/v2/bot/message/push"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                    json={"to": user_id, "messages": [message]},
                )
                return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] LINE send_message: {e}")
            return False

    async def reply_message(self, reply_token: str, message: dict) -> bool:
        import httpx
        if not self.token:
            return False

        url = "https://api.line.me/v2/bot/message/reply"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                    json={"replyToken": reply_token, "messages": [message]},
                )
                return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] LINE reply_message: {e}")
            return False

    async def download_media(self, media_id: str) -> bytes:
        import httpx
        if not self.token:
            raise ValueError("TOKEN not configured")

        url = f"https://api-data.line.me/v2/bot/message/{media_id}/content"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                response.raise_for_status()
                return response.content
        except Exception as e:
            raise RuntimeError(f"Failed to download media: {e}")

    def format_flex_message(self, data: dict) -> dict:
        """创建 LINE Flex Message"""
        pricing = data.get("pricing", {})
        return {
            "type": "flex",
            "altText": "报价单",
            "contents": {
                "type": "bubble",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [{"type": "text", "text": "📝 报价单", "weight": "bold", "size": "lg"}],
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": f"单价：¥{pricing.get('unit_price', 0):,}"},
                        {"type": "text", "text": f"批量价：¥{pricing.get('moq_price', 0):,}"},
                        {"type": "text", "text": f"交期：{data.get('lead_time_days', 0)}天"},
                    ],
                },
            },
        }

    def format_quick_reply(self, options: list[str]) -> dict:
        """创建 Quick Reply 按钮"""
        items = []
        for opt in options[:13]:  # LINE 限制 13 个
            items.append({
                "type": "action",
                "action": {"type": "message", "label": opt, "text": opt},
            })
        return {
            "type": "text",
            "text": "请选择：",
            "quickReply": {"items": items},
        }


class SlackBot(BaseBot):
    """Slack Bot 实现"""

    def __init__(self):
        self.token = os.getenv("SLACK_BOT_TOKEN")

    async def send_message(self, user_id: str, message: dict) -> bool:
        import httpx
        if not self.token:
            return False

        url = "https://slack.com/api/chat.postMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                    json={"channel": user_id, "text": message.get("text", "")},
                )
                return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] Slack send_message: {e}")
            return False

    async def reply_message(self, reply_token: str, message: dict) -> bool:
        # Slack 没有 reply_token，用 channel ID
        return await self.send_message(reply_token, message)

    async def download_media(self, media_id: str) -> bytes:
        raise NotImplementedError("Slack media download not implemented")

    def format_flex_message(self, data: dict) -> dict:
        """Slack 使用 Block Kit，不是 Flex Message"""
        pricing = data.get("pricing", {})
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "📝 报价单"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*单价：* ¥{pricing.get('unit_price', 0):,}"},
                    {"type": "mrkdwn", "text": f"*批量价：* ¥{pricing.get('moq_price', 0):,}"},
                ]
            }
        ]
        return {"type": "section", "blocks": blocks}

    def format_quick_reply(self, options: list[str]) -> dict:
        """Slack 使用选择器"""
        from typing import Any
        elements = [{"type": "button", "text": {"type": "plain_text", "text": opt}, "value": opt} for opt in options[:5]]
        return {"type": "actions", "elements": elements}


class DiscordBot(BaseBot):
    """Discord Bot 实现"""

    def __init__(self):
        self.token = os.getenv("DISCORD_BOT_TOKEN")

    async def send_message(self, user_id: str, message: dict) -> bool:
        import httpx
        if not self.token:
            return False

        # Discord 用 webhook 或 REST API
        url = f"https://discord.com/api/v10/channels/{user_id}/messages"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bot {self.token}",
                        "Content-Type": "application/json",
                    },
                    json={"content": message.get("text", "")},
                )
                return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] Discord send_message: {e}")
            return False

    async def reply_message(self, reply_token: str, message: dict) -> bool:
        return await self.send_message(reply_token, message)

    async def download_media(self, media_id: str) -> bytes:
        raise NotImplementedError("Discord media download not implemented")

    def format_flex_message(self, data: dict) -> dict:
        """Discord 使用 Embed"""
        pricing = data.get("pricing", {})
        return {
            "embeds": [{
                "title": "📝 报价单",
                "fields": [
                    {"name": "单价", "value": f"¥{pricing.get('unit_price', 0):,}", "inline": True},
                    {"name": "批量价", "value": f"¥{pricing.get('moq_price', 0):,}", "inline": True},
                    {"name": "交期", "value": f"{data.get('lead_time_days', 0)}天", "inline": True},
                ]
            }]
        }

    def format_quick_reply(self, options: list[str]) -> dict:
        """Discord 使用组件按钮"""
        components = [{
            "type": 1,
            "components": [
                {"type": 2, "style": 1, "label": opt, "custom_id": opt}
                for opt in options[:5]
            ]
        }]
        return {"type": 4, "components": components}


# ── Bot Factory ─────────────────────────────────────────

BOT_REGISTRY = {
    "line": LINEBot,
    "slack": SlackBot,
    "discord": DiscordBot,
}


def create_bot(platform: str = None) -> BaseBot:
    """创建 Bot 实例（自动检测平台）"""
    if platform is None:
        # 自动检测
        if os.getenv("LINE_CHANNEL_ACCESS_TOKEN"):
            platform = "line"
        elif os.getenv("SLACK_BOT_TOKEN"):
            platform = "slack"
        elif os.getenv("DISCORD_BOT_TOKEN"):
            platform = "discord"
        else:
            platform = "line"  # 默认

    bot_class = BOT_REGISTRY.get(platform)
    if not bot_class:
        raise ValueError(f"Unknown platform: {platform}")

    return bot_class()


# ── 兼容性别名 ─────────────────────────────────────────

# 保持向后兼容，原有的导入方式仍然有效
def get_default_bot():
    """获取默认 Bot（向后兼容）"""
    from app.modules.line_module import line_bot
    return line_bot