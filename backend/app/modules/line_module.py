"""
LINE 模块 - 制造业 AI 报价系统

功能：
- LINE Webhook 处理（签名验证、事件解析）
- 制造业场景对话处理（图纸查询、报价咨询、知识库搜索）
- 调用后端 API 获取结果
- LINE 消息格式化（文字、Flex Message、QuickReply）

依赖：
- httpx（已有）
- ai-line-solution 核心模式
"""

import base64
import hashlib
import hmac
import json
import os
from typing import Any, Optional, List
import httpx

from app.line_config import line_config


# ── 常量定义 ─────────────────────────────────────────

# 制造业场景关键词
SCENE_KEYWORDS = {
    "quote": ["报价", "价格", "多少钱", "cost", "price", "見積もり"],
    "material": ["材质", "材料", "SUS", "SECC", "SPCC", "material"],
    "process": ["工艺", "工序", "加工", "CNC", "钣金", "process"],
    "blueprint": ["图纸", "图纸", "CAD", "blueprint"],
    "delivery": ["交期", "交验", "lead time", "納期"],
    "knowledge": ["知识", "规格", "标准", "spec"],
}


# ── LINE Webhook handler ─────────────────────────────────

class LINEWebhookHandler:
    """LINE Webhook 处理器"""

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """验证 LINE 签名

        Args:
            body: Raw request body bytes
            signature: LINE signature header

        Returns:
            True if signature is valid
        """
        if not line_config.LINE_CHANNEL_SECRET:
            print("[WARN] LINE_CHANNEL_SECRET not configured, skipping signature verification")
            return True

        key = line_config.LINE_CHANNEL_SECRET.encode()
        expected = hmac.new(key, body, hashlib.sha256).hexdigest()

        return hmac.compare_digest(expected, signature)

    def parse_events(self, body: dict) -> List[dict]:
        """解析 Webhook 事件

        Args:
            body: Parsed JSON body

        Returns:
            List of events
        """
        return body.get("events", [])

    def extract_message_text(self, event: dict) -> Optional[str]:
        """从消息事件提取文本

        Args:
            event: LINE Webhook event

        Returns:
            Text content or None
        """
        message = event.get("message", {})
        if message.get("type") == "text":
            return message.get("text")
        return None

    def extract_message_id(self, event: dict) -> Optional[str]:
        """从图片/视频/音频消息提取消息ID

        Args:
            event: LINE Webhook event

        Returns:
            Message ID or None
        """
        message = event.get("message", {})
        if message.get("type") in ("image", "video", "audio"):
            return message.get("id")
        return None

    def extract_user_id(self, event: dict) -> Optional[str]:
        """从事件提取用户ID

        Args:
            event: LINE Webhook event

        Returns:
            User ID or None
        """
        source = event.get("source", {})
        return source.get("userId")

    def get_reply_token(self, event: dict) -> Optional[str]:
        """获取回复令牌

        Args:
            event: LINE Webhook event

        Returns:
            Reply token or None
        """
        return event.get("replyToken")

    def get_event_type(self, event: dict) -> str:
        """获取事件类型

        Args:
            event: LINE Webhook event

        Returns:
            Event type string
        """
        return event.get("type", "")


# ── Manufacturing LINE Bot ────────────────────────────

class ManufacturingLINEBot:
    """制造业 LINE Bot

    处理：
    - 图纸查询（调用 OCR 模块）
    - 报价咨询（调用报价 API）
    - 知识库搜索（RAG）
    - 工艺类型查询
    """

    def __init__(self):
        self.webhook_handler = LINEWebhookHandler()
        self._base_url = os.getenv("API_BASE_URL", "http://localhost:8000")

    async def download_line_image(self, message_id: str) -> bytes:
        """从 LINE 服务器下载图片

        Args:
            message_id: LINE message ID

        Returns:
            Image binary data
        """
        if not line_config.LINE_CHANNEL_ACCESS_TOKEN:
            raise ValueError("LINE_CHANNEL_ACCESS_TOKEN not configured")

        url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {line_config.LINE_CHANNEL_ACCESS_TOKEN}",
                    },
                )
                response.raise_for_status()
                return response.content
        except httpx.TimeoutException:
            raise TimeoutError("LINE image download timed out")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"LINE image download HTTP error: {e}")
        except Exception as e:
            raise RuntimeError(f"LINE image download error: {str(e)}")

    async def reply_message(self, reply_token: str, messages: List[dict]) -> bool:
        """回复 LINE 用户消息

        Args:
            reply_token: LINE reply token
            messages: List of message objects

        Returns:
            True if successful
        """
        if not line_config.LINE_CHANNEL_ACCESS_TOKEN:
            print("[ERROR] LINE_CHANNEL_ACCESS_TOKEN not configured")
            return False

        url = "https://api.line.me/v2/bot/message/reply"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {line_config.LINE_CHANNEL_ACCESS_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "replyToken": reply_token,
                        "messages": messages,
                    },
                )
                response.raise_for_status()
                print(f"[INFO] Replied to user with {len(messages)} message(s)")
                return True
        except httpx.HTTPStatusError as e:
            print(f"[ERROR] LINE reply HTTP error: {e.response.status_code}")
            return False
        except Exception as e:
            print(f"[ERROR] LINE reply error: {str(e)}")
            return False

    def detect_scene(self, text: str) -> str:
        """检测用户意图场景

        Args:
            text: User message text

        Returns:
            Scene type: quote/material/process/blueprint/delivery/knowledge/general
        """
        text_lower = text.lower()
        for scene, keywords in SCENE_KEYWORDS.items():
            if any(kw.lower() in text_lower for kw in keywords):
                return scene
        return "general"

    async def process_message(
        self,
        user_id: str,
        text: str,
        reply_token: str,
    ) -> str:
        """处理用户消息

        Args:
            user_id: LINE user ID
            text: User message text
            reply_token: LINE reply token

        Returns:
            AI response text
        """
        scene = self.detect_scene(text)
        print(f"[DEBUG] Detected scene: {scene} for user {user_id}")

        # 根据场景调用不同 API
        if scene == "quote":
            result = await self._handle_quote(text, reply_token)
        elif scene == "material":
            result = await self._handle_material(text, reply_token)
        elif scene == "process":
            result = await self._handle_process(text, reply_token)
        elif scene == "blueprint":
            result = await self._handle_blueprint(text, reply_token)
        elif scene == "delivery":
            result = await self._handle_delivery(text, reply_token)
        elif scene == "knowledge":
            result = await self._handle_knowledge(text, reply_token)
        else:
            result = await self._handle_general(text, reply_token)

        return result

    async def _handle_quote(self, text: str, reply_token: str) -> str:
        """处理报价咨询"""
        # 提取材质信息
        import re
        material_match = re.search(r"(SUS\d+|SECC|SPCC|ADC\d+)", text.upper())
        material = material_match.group(0) if material_match else "SUS304"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/quote/generate",
                    json={
                        "material": material,
                        "quantity": 1,
                        "weight_kg": 1.0,
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    return self._format_quote_reply(data)
                else:
                    return "抱歉，报价服务暂不可用，请稍后再试。"
        except Exception as e:
            print(f"[ERROR] Quote API error: {e}")
            return f"报价查询失败：{str(e)}"

    async def _handle_material(self, text: str, reply_token: str) -> str:
        """处理材质查询"""
        # 从知识库查询材质价格
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/blueprint/search",
                    json={"query": text, "top_k": 3},
                )
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    if results:
                        return self._format_knowledge_reply(results)
                    else:
                        return "未找到相关材质信息。"
                else:
                    return "知识库查询失败，请稍后再试。"
        except Exception as e:
            print(f"[ERROR] Knowledge API error: {e}")
            return f"材质查询失败：{str(e)}"

    async def _handle_process(self, text: str, reply_token: str) -> str:
        """处理工艺查询"""
        process_list = """���持���工艺类型：

1. CNC加工 (CNC Machining)
   - 粗加工/精加工
   - 3轴/5轴联动

2. 钣金加工 (Sheet Metal)
   - 折弯/冲孔/激光切割
   - SUS/SECC/SPCC

3. 表面处理
   - 抛光/电镀/喷涂
   - 阳极氧化

4. 铸造
   - 压铸/低压铸造
   - ADC12/A383

5. 组装
   - 螺钉组装/焊接
   - 功能测试"""
        return process_list

    async def _handle_blueprint(self, text: str, reply_token: str) -> str:
        """处理图纸查询"""
        return """请发送图纸图片，我会帮您：
1. 识别图纸中的材质/工艺
2. 提取关键尺寸
3. 估算报价

支持的格式：PDF, JPG, PNG"""

    async def _handle_delivery(self, text: str, reply_token: str) -> str:
        """处理交期查询"""
        return """标准交期参考：

- CNC加工：7-10天
- 钣金：5-7天
- 表面处理：2-3天
- 压铸：14-21天
- 组装：视具体复杂度

加急服务可谈。"""

    async def _handle_knowledge(self, text: str, reply_token: str) -> str:
        """处理知识库搜索"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/blueprint/search",
                    json={"query": text, "top_k": 5},
                )
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    if results:
                        return self._format_knowledge_reply(results)
                    else:
                        return "未找到相关知识，请尝试其他关键词。"
                else:
                    return "知识库暂不可用。"
        except Exception as e:
            print(f"[ERROR] Knowledge search error: {e}")
            return f"知识库查询失败：{str(e)}"

    async def _handle_general(self, text: str, reply_token: str) -> str:
        """处理通用消息 → 调 AI 回复"""
        from app.modules.ai_module import ai_manufacturing
        try:
            answer = await ai_manufacturing.chat(text)
            return answer
        except Exception as e:
            print(f"[ERROR] AI chat error: {e}")
            return """您好！我是制造业AI助手，可以帮您：

📋 查询报价 - "CNC加工报价"
📦 查询材质 - "SUS304价格"
🔧 查询工艺 - "有哪些工艺"
📅 查询交期 - "交期多久"
📚 知识库 - "查一下XXX规格"

或直接发送图纸图片获取自动报价。"""

    def _format_quote_reply(self, data: dict) -> str:
        """格式化报价回复"""
        pricing = data.get("pricing", {})
        breakdown = data.get("breakdown", {})

        return f"""📝 报价单

材质：{data.get('process_category', 'N/A')}
工艺类型：{data.get('process_category', 'N/A')}

💰 价格：
- 单价：¥{pricing.get('unit_price', 'N/A'):,}
- 批量价：¥{pricing.get('moq_price', 'N/A'):,}
- 量产价：¥{pricing.get('mass_production_price', 'N/A'):,}

📦 成本明细：
- 材料：¥{breakdown.get('material', 0):,}
- 加工：¥{breakdown.get('processing', 0):,}
- 管理：¥{breakdown.get('management', 0):,}

📅 交期：{data.get('lead_time_days', 'N/A')}天
📌 有效期：{data.get('validity_days', 30)}天

*实际价格根据图纸复杂度确定"""

    def _format_knowledge_reply(self, results: List[dict]) -> str:
        """格式化知识库回复"""
        lines = ["📚 搜索结果：\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "N/A")
            content = r.get("content", "")[:100]
            lines.append(f"{i}. {title}\n{content}...")
        return "\n".join(lines)

    def create_quick_reply(self) -> dict:
        """创建 Quick Reply 消息"""
        return {
            "type": "text",
            "text": "请选择服务：",
            "quickReply": {
                "items": [
                    {
                        "type": "action",
                        "action": {
                            "type": "message",
                            "label": "📝 报价查询",
                            "text": "报价查询",
                        },
                    },
                    {
                        "type": "action",
                        "action": {
                            "type": "message",
                            "label": "📦 材质价格",
                            "text": "材质价格",
                        },
                    },
                    {
                        "type": "action",
                        "action": {
                            "type": "message",
                            "label": "🔧 工艺类型",
                            "text": "工艺类型",
                        },
                    },
                    {
                        "type": "action",
                        "action": {
                            "type": "message",
                            "label": "📚 知识库",
                            "text": "知识库搜索",
                        },
                    },
                ]
            },
        }

    def create_quote_flex_message(self, data: dict) -> dict:
        """创建 Flex Message 报价单"""
        pricing = data.get("pricing", {})
        return {
            "type": "flex",
            "altText": "报价单",
            "contents": {
                "type": "bubble",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": "📝 报价单",
                            "weight": "bold",
                            "size": "lg",
                        }
                    ],
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"单价：¥{pricing.get('unit_price', 0):,}",
                        },
                        {
                            "type": "text",
                            "text": f"批量价：¥{pricing.get('moq_price', 0):,}",
                        },
                        {
                            "type": "text",
                            "text": f"交期：{data.get('lead_time_days', 0)}天",
                        },
                    ],
                },
            },
        }


# ── 全局实例 ────────────────────────────────────────

line_bot = ManufacturingLINEBot()