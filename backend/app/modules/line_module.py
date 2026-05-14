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
from app.modules.intent_module import intent_classifier


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

    async def detect_scene(self, text: str) -> str:
        """检测用户意图场景（LLM + 关键词回退）

        Args:
            text: User message text

        Returns:
            Scene type: quote/material/process/blueprint/delivery/knowledge/sample/complaint/general
        """
        # 调用同步方法 classify_sync
        intent = intent_classifier.classify_sync(text)
        # sample/complaint -> general（如果没有对应handler）
        if intent in ("sample", "complaint"):
            return intent  # 新增的意图
        if intent == "knowledge":
            return "knowledge"
        return intent

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
        scene = await self.detect_scene(text)
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
        elif scene == "complaint":
            result = await self._handle_complaint(text, reply_token)
        elif scene == "sample":
            result = await self._handle_sample(text, reply_token)
        else:
            result = await self._handle_general(text, reply_token)

        return result

    async def _handle_quote(self, text: str, reply_token: str) -> str:
        """处理报价咨询"""
        import re

        # 提取材质信息
        material_match = re.search(r"(SUS\d+|SECC|SPCC|ADC\d+)", text.upper())
        material = material_match.group(0) if material_match else "SUS304"

        # 提取数量
        qty_match = re.search(r"(\d+)\s*(?:个|件|pcs|pieces|個|枚)", text)
        quantity = int(qty_match.group(1)) if qty_match else 1

        # 提取交期
        delivery_match = re.search(r"(\d+)\s*(?:天|days?|週間)", text)
        lead_time = int(delivery_match.group(1)) if delivery_match else None

        # 调用报价 API
        try:
            payload = {
                "material": material,
                "quantity": quantity,
                "weight_kg": 1.0,
            }
            if lead_time:
                payload["lead_time_days"] = lead_time

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/quote/generate",
                    json=payload,
                )
                if response.status_code == 200:
                    data = response.json()
                    # 返回 Flex Message dict（由 line_api.py 负责发送）
                    return self.create_quote_flex_message(data)
                else:
                    return {"type": "text", "text": "抱歉，报价服务暂不可用，请稍后再试。"}
        except Exception as e:
            print(f"[ERROR] Quote API error: {e}")
            return f"报价查询失败：{str(e)}"

    async def process_blueprint_image(self, image_bytes: bytes) -> dict:
        """对图纸图片进行OCR → KB匹配 → 报价 → 回复用户

        Args:
            image_bytes: 图片二进制数据

        Returns:
            LINE 消息 dict
        """
        from app.modules.ocr_module import ocr_image, check_ocr_available

        if not check_ocr_available():
            return {
                "type": "text",
                "text": "⚠️ OCR服务暂不可用，请稍后再试。"
            }

        try:
            # 1. OCR 识别图纸内容
            ocr_result = await ocr_image(image_bytes)
            recognized_text = ocr_result.get("text", "")
            print(f"[DEBUG] OCR result: {recognized_text[:200]}")

            # 2. KB 匹配 — 用识别出的文字去知识库查（向量语义搜索）
            kb_results = []
            try:
                from app.modules.kb_module import get_kb
                kb = get_kb()
                kb_results = kb.vector_search(recognized_text, top_k=3)
                print(f"[DEBUG] KB vector search matched {len(kb_results)} entries")
            except Exception as kb_err:
                print(f"[WARN] KB search failed: {kb_err}")

            # 3. 提取材质和数量
            import re
            material_match = re.search(
                r"(SUS\d+|SECC|SPCC|ADC\d+|AISI\d+|JIS\s*\w+)",
                recognized_text.upper()
            )
            material = material_match.group(0) if material_match else "SUS304"

            qty_match = re.search(r"(\d+)\s*(?:個|个|件|pcs|pieces)", recognized_text)
            quantity = int(qty_match.group(1)) if qty_match else 1

            # 4. 调用报价 API
            quote_data = None
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        f"{self._base_url}/api/quote/generate",
                        json={
                            "material": material,
                            "quantity": quantity,
                            "weight_kg": 1.0,
                        },
                    )
                    if response.status_code == 200:
                        quote_data = response.json()
            except Exception as q_err:
                print(f"[WARN] Quote API failed: {q_err}")

            # 5. 组合回复 — 优先 KB 内容，再附报价
            return self._build_blueprint_response(
                recognized_text=recognized_text,
                kb_results=kb_results,
                material=material,
                quantity=quantity,
                quote_data=quote_data,
            )

        except Exception as e:
            print(f"[ERROR] Blueprint OCR error: {e}")
            return {
                "type": "text",
                "text": f"⚠️ 图片处理失败：{str(e)}"
            }

    def _build_blueprint_response(
        self,
        recognized_text: str,
        kb_results: list,
        material: str,
        quantity: int,
        quote_data: dict,
    ) -> dict:
        """组合 KB 匹配结果 + 报价 → LINE Flex Message"""
        # KB 有匹配 → 用 Flex Message 展示完整信息
        if kb_results:
            lines = []
            for r in kb_results[:3]:
                lines.append(f"📄 {r['title']}")
                lines.append(r['content'][:150] + "...")

            if quote_data:
                pricing = quote_data.get("pricing", {})
                unit = pricing.get("unit_price", 0)
                lines.append("")
                lines.append(f"💰 参考报价：¥{unit:,}/件 起")

            body_text = "\n".join(lines)
            return {
                "type": "flex",
                "altText": "图纸识别结果",
                "contents": {
                    "type": "bubble",
                    "header": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [{"type": "text", "text": "📋 图纸识别结果", "weight": "bold", "size": "lg"}],
                    },
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": f"识别材质：{material}", "weight": "bold"},
                            {"type": "text", "text": f"数量：{quantity}件", "weight": "bold"},
                            {"type": "separator"},
                            {"type": "text", "text": body_text[:500], "wrap": True},
                        ],
                    },
                },
            }

        # KB 无匹配但有报价 → 纯报价
        if quote_data:
            return self.create_quote_flex_message(quote_data)

        # 什么都没有 → 文字说明
        return {
            "type": "text",
            "text": f"已收到图纸，识别材质：{material}，数量：{quantity}件。\n\n暂未匹配到相关知识库内容，请联系客服补充资料。"
        }

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

    async def _handle_complaint(self, text: str, reply_token: str) -> str:
        """处理投诉/售后"""
        return (
            "非常抱歉给您带来不便，我们会第一时间处理您的问题。\n\n"
            "请提供以下信息：\n"
            "1. 订单号\n"
            "2. 具体问题描述\n"
            "3. 相关图片（如有）\n\n"
            "我们的客服团队会在24小时内联系您。"
        )

    async def _handle_sample(self, text: str, reply_token: str) -> str:
        """处理样品请求"""
        return (
            "了解您需要样品。\n\n"
            "样品流程：\n"
            "1. 提供图纸或规格要求\n"
            "2. 我们评估后报价\n"
            "3. 确认后安排打样（3-7天）\n\n"
            "请发送您的图纸或规格，我来帮您评估。"
        )

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
        """处理通用消息 → 纯 KB 向量检索，不用 AI"""
        try:
            from app.modules.kb_module import get_kb
            kb = get_kb()
            results = kb.vector_search(text, top_k=5)
            if results:
                # 优先取最高分，格式化输出
                best = results[0]
                content = best["content"]
                # 截取前 400 字，分段展示
                if len(content) > 400:
                    content = content[:400] + "..."

                lines = [
                    f"📄 {best['title']}",
                    f"",
                    content,
                ]
                # 如果有多个相关结果，追加
                if len(results) > 1:
                    lines.append("")
                    lines.append("━━━━━━━━━━━")
                    lines.append("相关条目：")
                    for r in results[1:4]:
                        lines.append(f"• {r['title']}")

                return "\n".join(lines)
            else:
                return """您好！我是制造业报价助手，可以帮您：

📋 查询报价 - "SUS304报价"
📦 查询材质 - "材质规格"
🔧 查询工艺 - "工艺类型"
📅 查询交期 - "交期多久"
📚 知识库 - "发送图纸图片自动识别"

请尝试以上方式，或直接发送图纸图片获取报价。"""
        except Exception as e:
            print(f"[ERROR] KB search error: {e}")
            return "⚠️ 知识库查询失败，请稍后再试。"

    def _format_quote_reply(self, data: dict) -> str:
        """格式化报价回复"""
        pricing = data.get("pricing", {})
        breakdown = data.get("breakdown", {})

        unit_price = pricing.get("unit_price") or 0
        moq_price = pricing.get("moq_price") or 0
        mass_price = pricing.get("mass_production_price") or 0

        return f"""📝 报价单

材质：{data.get('process_category', 'N/A')}
工艺类型：{data.get('process_category', 'N/A')}

💰 价格：
- 单价：¥{unit_price:,}
- 批量价：¥{moq_price:,}
- 量产价：¥{mass_price:,}

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