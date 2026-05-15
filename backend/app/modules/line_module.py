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
from app.modules.blueprint_parser import BlueprintParser


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

# 报价流程 QuickReply 选项
QUOTE_MATERIAL_OPTIONS = ["SUS304", "SUS303", "SECC", "SPCC", "ADC12", "A5052", "其他材质"]
QUOTE_QUANTITY_OPTIONS = ["1-10件", "11-50件", "51-100件", "100+件"]
QUOTE_PROCESS_OPTIONS = ["CNC加工", "钣金加工", "压铸铸造", "表面处理"]


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

        import base64
        key = line_config.LINE_CHANNEL_SECRET.encode()
        expected = hmac.new(key, body, hashlib.sha256).digest()
        signature_bytes = base64.b64decode(signature)

        return hmac.compare_digest(expected, signature_bytes)

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


# ── 用户报价状态管理 ────────────────────────────────

class UserQuoteState:
    """用户报价状态管理器

    用于暂存用户报价流程中收集的参数，
    支持分阶段收集：材质 → 数量 → 工艺 → 报价
    """

    def __init__(self):
        # user_id -> {material, quantity, process}
        self._states: dict = {}

    def get_state(self, user_id: str) -> dict:
        """获取用户状态"""
        return self._states.get(user_id, {})

    def update_state(self, user_id: str, **kwargs) -> dict:
        """更新用户状态"""
        if user_id not in self._states:
            self._states[user_id] = {}
        self._states[user_id].update(kwargs)
        return self._states[user_id]

    def clear_state(self, user_id: str) -> None:
        """清除用户状态"""
        if user_id in self._states:
            del self._states[user_id]

    def is_complete(self, user_id: str) -> bool:
        """检查参数是否完整（材质+数量+工艺）"""
        state = self._states.get(user_id, {})
        return bool(state.get("material") and state.get("quantity") and state.get("process"))


# 全局实例
user_quote_state = UserQuoteState()


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
        self._state = user_quote_state  # 引用全局状态管理器

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
            result = await self._handle_quote(text, reply_token, user_id)
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

    async def _handle_quote(self, text: str, reply_token: str, user_id: str) -> str:
        """处理报价咨询 - 分阶段需求收集"""
        import re

        # 获取当前状态
        state = self._state.get_state(user_id)

        # ── 优先处理 QuickReply 按钮回复 ──
        # 检查是否回复了材质
        for mat in QUOTE_MATERIAL_OPTIONS:
            if mat in text or (mat == "其他材质" and "材质" in text):
                state = self._state.update_state(user_id, material=mat if mat != "其他材质" else "其他")
                break

        # 检查是否回复了数量
        for qty_opt in QUOTE_QUANTITY_OPTIONS:
            if qty_opt in text:
                # 转换为数值范围
                if qty_opt == "1-10件":
                    quantity = 5
                elif qty_opt == "11-50件":
                    quantity = 30
                elif qty_opt == "51-100件":
                    quantity = 75
                else:  # 100+件
                    quantity = 100
                state = self._state.update_state(user_id, quantity=quantity, quantity_raw=qty_opt)
                break

        # 检查是否回复了工艺
        for proc in QUOTE_PROCESS_OPTIONS:
            if proc in text:
                state = self._state.update_state(user_id, process=proc)
                break

        # ── 从文本提取已有关键信息（优先于 QuickReply） ──
        # 材质
        material_match = re.search(r"(SUS\d+|SECC|SPCC|ADC\d+|A5052)", text.upper())
        if material_match and not state.get("material"):
            state = self._state.update_state(user_id, material=material_match.group(0))

        # 数量
        qty_match = re.search(r"(\d+)\s*(?:个|件|pcs|pieces|個|枚)", text)
        if qty_match and not state.get("quantity"):
            state = self._state.update_state(
                user_id,
                quantity=int(qty_match.group(1)),
                quantity_raw=f"{qty_match.group(1)}件",
            )

        # 工艺
        for proc in QUOTE_PROCESS_OPTIONS:
            if proc.replace("处理", "").replace("加工", "").replace("铸造", "") in text:
                state = self._state.update_state(user_id, process=proc)
                break

        # ── 检查缺少什么参数 ──
        missing = []
        if not state.get("material"):
            missing.append("material")
        if not state.get("quantity"):
            missing.append("quantity")
        if not state.get("process"):
            missing.append("process")

        # ── 参数齐全 → 调用报价 API ──
        if not missing:
            return await self._call_quote_api(user_id, state)

        # ── 参数不全 → 用 QuickReply 询问 ──
        return self._create_quote_ask_message(state, missing)

    async def _call_quote_api(self, user_id: str, state: dict) -> str:
        """调用报价 API"""
        # 清理状态
        self._state.clear_state(user_id)

        material = state.get("material", "SUS304")
        quantity = state.get("quantity", 1)
        process = state.get("process", "CNC加工")

        # 提取交期（如果有）
        lead_time = None
        lead_match = re.search(r"(\d+)\s*(?:天|days?|週間)", state.get("_last_text", ""))
        if lead_match:
            lead_time = int(lead_match.group(1))

        try:
            payload = {
                "material": material,
                "quantity": quantity,
                "weight_kg": 1.0,
                "process_category": process,
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
                    return self.create_quote_flex_message(data)
                else:
                    return {"type": "text", "text": "抱歉，报价服务暂不可用，请稍后再试。"}
        except Exception as e:
            print(f"[ERROR] Quote API error: {e}")
            return f"报价查询失败：{str(e)}"

    def _create_quote_ask_message(self, state: dict, missing: list) -> dict:
        """创建报价询问消息（带 QuickReply）"""
        # 构建问题文本
        parts = []
        if "material" in missing:
            parts.append("请选择或输入材质（如 SUS304、SECC 等）")
        if "quantity" in missing:
            parts.append("请选择数量范围")
        if "process" in missing:
            parts.append("请选择加工工艺")

        question = "，".join(parts)
        text = f"📋 为了给您准确报价，请提供以下信息：\n{question}"

        # 构建 QuickReply
        quick_reply_items = []

        if "material" in missing:
            for mat in QUOTE_MATERIAL_OPTIONS:
                quick_reply_items.append({
                    "type": "action",
                    "action": {
                        "type": "message",
                        "label": mat,
                        "text": mat,
                    },
                })

        if "quantity" in missing:
            for qty in QUOTE_QUANTITY_OPTIONS:
                quick_reply_items.append({
                    "type": "action",
                    "action": {
                        "type": "message",
                        "label": qty,
                        "text": qty,
                    },
                })

        if "process" in missing:
            for proc in QUOTE_PROCESS_OPTIONS:
                quick_reply_items.append({
                    "type": "action",
                    "action": {
                        "type": "message",
                        "label": proc,
                        "text": proc,
                    },
                })

        return {
            "type": "text",
            "text": text,
            "quickReply": {"items": quick_reply_items[:13]},  # LINE 限制13个按钮
        }

    async def process_blueprint_image(self, image_bytes: bytes) -> dict:
        """对图纸图片进行OCR → KB匹配 → 报价 → 回复用户

        Args:
            image_bytes: 图片二进制数据

        Returns:
            LINE 消息 dict
        """
        from app.modules.ai_module import ai_manufacturing
        # 优先用 MiniMax 多模态理解图纸（PaddleOCR 不可用时）
        import base64
        image_b64 = base64.b64encode(image_bytes).decode()
        ai_text = await ai_manufacturing.vision(
            image_b64,
            "请仔细描述这张制造业图纸的内容，包括：材质、尺寸、数量、工艺要求等所有可见信息。如果有日语或英语的技术标注也请标注。"
        )
        if not ai_text:
            return {
                "type": "text",
                "text": "⚠️ 图纸识别服务暂时不可用，请稍后再试，或联系客服手动报价。",
                "quickReply": {
                    "items": [
                        {"type": "action", "action": {"type": "message", "label": "查询报价", "text": "我想查询报价"}},
                        {"type": "action", "action": {"type": "message", "label": "联系客服", "text": "人工报价"}},
                    ]
                }
            }
        recognized_text = f"[图纸解析]\n{ai_text}"
        print(f"[DEBUG] Blueprint vision result: {recognized_text[:300]}")

        # 2. BlueprintParser 解析结构化参数
        parser = BlueprintParser()
        spec = parser.parse(recognized_text)
        print(f"[DEBUG] Parsed spec: material={spec.material}, quantity={spec.quantity}, "
              f"dimensions={spec.dimensions}, weight_kg={spec.weight_kg}, "
              f"tolerance={spec.tolerance}, surface={spec.surface}")

        # 3. KB 匹配 — 用识别出的文字去知识库查（向量语义搜索）
        kb_results = []
        try:
            from app.modules.kb_module import get_kb
            kb = get_kb()
            kb_results = kb.vector_search(recognized_text, top_k=3)
            print(f"[DEBUG] KB vector search matched {len(kb_results)} entries")
        except Exception as kb_err:
            print(f"[WARN] KB search failed: {kb_err}")

        # 4. 用解析结果调用报价 API（weight_kg 用解析值）
        material = spec.material or "SUS304"
        quantity = spec.quantity if spec.quantity > 0 else 1
        weight_kg = spec.weight_kg if spec.weight_kg else 1.0

        quote_data = None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/quote/generate",
                    json={
                        "material": material,
                        "quantity": quantity,
                        "weight_kg": weight_kg,
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
            spec=spec,
        )

    def _build_blueprint_response(
        self,
        recognized_text: str,
        kb_results: list,
        material: str,
        quantity: int,
        quote_data: dict,
        spec=None,
    ) -> dict:
        """组合 KB 匹配结果 + 报价 → LINE Flex Message"""
        # 安全获取 spec 属性
        def safe_get(attr, default=""):
            return getattr(spec, attr, default) or default

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
                            {"type": "text", "text": f"材质：{material}", "weight": "bold"},
                            {"type": "text", "text": f"数量：{quantity}件"},
                            {"type": "text", "text": f"尺寸：{safe_get('dimensions')}"},
                            {"type": "text", "text": f"公差：{safe_get('tolerance')}"},
                            {"type": "text", "text": f"表面：{safe_get('surface')}"},
                            {"type": "text", "text": f"重量：{safe_get('weight_kg')}kg"},
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
            "text": f"已收到图纸，识别材质：{material}，数量：{quantity}件。\n尺寸：{safe_get('dimensions')}\n重量：{safe_get('weight_kg')}kg\n\n暂未匹配到相关知识库内容，请联系客服补充资料。"
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
                        # KB 无结果 → 走 AI fallback
                        return await self._handle_ai_fallback(text)
                else:
                    return "知识库查询失败，请稍后再试。"
        except Exception as e:
            print(f"[ERROR] Knowledge API error: {e}")
            return "⚠️ 材质查询失败，请稍后再试。"

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
                        # KB 无结果 → 走 AI fallback
                        return await self._handle_ai_fallback(text)
                else:
                    return "知识库查询失败，请稍后再试。"
        except Exception as e:
            print(f"[ERROR] Knowledge search error: {e}")
            return "⚠️ 知识库查询失败，请稍后再试。"

    async def _handle_general(self, text: str, reply_token: str) -> str:
        """处理通用消息 → 不搜 KB，直接走 AI 判断是否在制造业范围内"""
        return await self._handle_ai_fallback(text)

    async def _handle_ai_fallback(self, text: str) -> str:
        """KB 无结果时调用 AI（带回答范围约束）"""
        from app.modules.ai_module import ai_manufacturing
        return await ai_manufacturing.chat(text)

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