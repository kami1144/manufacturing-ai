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
import re
from typing import Any, Optional, List
import httpx

from app.bot_provider import LINEBot
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

class ManufacturingLINEBot(LINEBot):
    """制造业 LINE Bot

    处理：
    - 图纸查询（调用 OCR 模块）
    - 报价咨询（调用报价 API）
    - 知识库搜索（RAG）
    - 工艺类型查询

    继承 LINEBot，复用 send_message/download_media 等基础设施，
    添加制造业特定业务逻辑方法。
    """

    def __init__(self):
        super().__init__()
        self.webhook_handler = LINEWebhookHandler()
        self._base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
        self._state = user_quote_state  # 引用全局状态管理器

    # 适配：download_line_image 是 download_media 的别名
    async def download_line_image(self, message_id: str) -> bytes:
        """从 LINE 服务器下载图片（适配方法）"""
        return await self.download_media(message_id)

    # 覆盖：使用原有实现（支持多消息列表）
    async def reply_message(self, reply_token: str, messages: List[dict]) -> bool:
        """回复 LINE 用户消息（支持多消息）"""
        if not self.token:
            print("[ERROR] LINE_CHANNEL_ACCESS_TOKEN not configured")
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

    # 适配：format_flex_message -> create_quote_flex_message
    def format_flex_message(self, data: dict) -> dict:
        """创建 Flex Message（适配方法）"""
        return self.create_quote_flex_message(data)

    # 适配：format_quick_reply -> create_quick_reply
    def format_quick_reply(self, options: list[str]) -> dict:
        """创建 Quick Reply（适配方法）"""
        if not options:
            return self.create_quick_reply()
        items = []
        for opt in options[:13]:
            items.append({
                "type": "action",
                "action": {"type": "message", "label": opt, "text": opt},
            })
        return {
            "type": "text",
            "text": "请选择：",
            "quickReply": {"items": items},
        }

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
        """Handle quote inquiries - multi-stage requirements collection"""
        # Get current state
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
        """对图纸图片进行结构化分析 → 6步流程输出（YAML Workflow 驱动）

        完整流水线：文件 → OCR识别 → 结构化解析 → 返回参数
        """
        import base64

        # ── 1. 执行 YAML Workflow ────────────────────────────────
        image_b64 = base64.b64encode(image_bytes).decode()

        try:
            from app.workflow.workflow_runner import WorkflowRunner

            runner = WorkflowRunner.from_yaml("manufacturing-blueprint")
            workflow_result = await runner.execute(
                image_b64=image_b64,
            )
        except Exception as wf_err:
            print(f"[ERROR] Workflow execution failed: {wf_err}")
            return {
                "type": "text",
                "text": "⚠️ 图纸分析服务暂时不可用，请稍后再试，或联系客服手动报价。",
                "quickReply": {
                    "items": [
                        {"type": "action", "action": {"type": "message", "label": "查询报价", "text": "我想查询报价"}},
                        {"type": "action", "action": {"type": "message", "label": "联系客服", "text": "人工报价"}},
                    ]
                }
            }

        # ── 2. 渲染 LINE 消息 ─────────────────────────────────
        msg = runner.render_line_message(workflow_result)

        # ── 3. 补充 QuickReply（根据执行结果决定按钮）────────────
        step_5 = workflow_result.step_results.get("step_5_rule_engine")
        step_6 = workflow_result.step_results.get("step_6_quote")
        kb_gate_passed = workflow_result.step_results.get("step_4_kb_search") and \
            workflow_result.step_results["step_4_kb_search"].gate and \
            workflow_result.step_results["step_4_kb_search"].gate.passed

        # 已有 quickReply（来自 render_line_message 的 error case）
        if "quickReply" in msg:
            return msg

        # Step 6 成功执行 → 报价到手，提供确认/修改按钮
        if step_6 and step_6.executed and step_6.output:
            msg["quickReply"] = {
                "items": [
                    {"type": "action", "action": {"type": "message", "label": "📝 确认报价", "text": "确认报价"}},
                    {"type": "action", "action": {"type": "message", "label": "🔧 修改参数", "text": "修改参数"}},
                    {"type": "action", "action": {"type": "message", "label": "📞 联系客服", "text": "人工报价"}},
                ]
            }
            return msg

        # KB Gate 失败（Step 5/6 跳过）→ 引导联系客服
        if step_5 and step_5.skipped:
            msg["quickReply"] = {
                "items": [
                    {"type": "action", "action": {"type": "message", "label": "📞 联系客服", "text": "人工报价"}},
                    {"type": "action", "action": {"type": "message", "label": "📋 重新上传", "text": "上传图纸"}},
                ]
            }
            return msg

        # 通用 fallback
        msg["quickReply"] = {
            "items": [
                {"type": "action", "action": {"type": "message", "label": "查询报价", "text": "我想查询报价"}},
                {"type": "action", "action": {"type": "message", "label": "联系客服", "text": "人工报价"}},
            ]
        }
        return msg

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

    # ── 6步流程辅助方法 ─────────────────────────────────────

    def _classify_process(self, features: dict, vision_result: str) -> str:
        """Step 3: 判断加工工艺类型（铸造/CNC/板金）

        Args:
            features: 提取的特征字典
            vision_result: 原始 vision 结果

        Returns:
            工艺类型字符串
        """
        material = features.get("material", "").upper()
        structure_type = features.get("structure_type", "")
        vision_lower = vision_result.lower()

        # 判断逻辑
        # 1. 铸造判断：铝合金/锌合金、压铸/低压
        if any(m in material for m in ["ADC", "A383", "锌", "ZAMAK"]):
            return "压铸铸造"
        if "铸造" in vision_result or "铸" in vision_lower:
            return "压铸铸造"

        # 2. 板金判断：薄板材料
        if any(m in material for m in ["SECC", "SPCC", "AL5052", "铝合金"]) and features.get("thickness", "未知") != "未知":
            return "钣金加工"
        if any(w in vision_lower for w in ["折弯", "钣金", "冲孔", "激光切割", "sheet metal"]):
            return "钣金加工"

        # 3. 默认 CNC
        return "CNC加工"

    def _estimate_hours(
        self,
        material: str,
        quantity: int,
        weight_kg: float,
        process_type: str,
        features: dict,
    ) -> str:
        """Step 5: 基于规则的工时估算

        Args:
            material: 材质
            quantity: 数量
            weight_kg: 重量 kg
            process_type: 工艺类型
            features: 特征字典

        Returns:
            工时估算文本
        """
        # 基础工时（单机加工）
        base_hours = {
            "CNC加工": 2.0,
            "钣金加工": 1.5,
            "压铸铸造": 3.0,
        }

        # 材质系数（难度）
        material_factor = {
            "SUS304": 1.3,
            "SUS303": 1.2,
            "AL5052": 1.0,
            "ADC12": 1.1,
            "SECC": 1.0,
            "SPCC": 0.9,
        }

        # 获取基础工时和材质系数
        base = base_hours.get(process_type, 2.0)
        factor = material_factor.get(material.upper(), 1.0)

        # 数量系数（批量优惠）
        if quantity <= 10:
            qty_factor = 1.0
        elif quantity <= 50:
            qty_factor = 0.85
        elif quantity <= 100:
            qty_factor = 0.75
        else:
            qty_factor = 0.65

        # 孔数系数（有孔更复杂）
        hole_count = features.get("hole_count", 0)
        hole_factor = 1.0 + (hole_count * 0.05) if hole_count > 0 else 1.0

        # 计算总工时
        estimated_hours = base * factor * qty_factor * hole_factor

        # 格式化输出
        return (
            f"预估工时：{estimated_hours:.1f}小时/件\n"
            f"- 基础工时：{base}小时\n"
            f"- 材质系数：{factor} ({material})\n"
            f"- 批量系数：{qty_factor} (x{quantity}件)\n"
            f"- 孔数系数：{hole_factor} ({hole_count}个孔)"
        )

    def _build_step6_output(
        self,
        quote_data: dict,
        process_type: str,
        kb_results: list,
    ) -> dict:
        """Step 6: 构建最终报价输出

        Args:
            quote_data: 报价 API 返回数据
            process_type: 工艺类型
            kb_results: KB 匹配结果

        Returns:
            报价内容字典
        """
        if not quote_data:
            return {
                "text": "报价生成中，请联系客服确认最终价格。",
                "has_quote": False,
            }

        pricing = quote_data.get("pricing", {})
        return {
            "unit_price": pricing.get("unit_price", 0),
            "moq_price": pricing.get("moq_price", 0),
            "mass_price": pricing.get("mass_production_price", 0),
            "lead_time_days": quote_data.get("lead_time_days", 0),
            "process_type": process_type,
            "has_quote": True,
        }

    def _build_6step_response(
        self,
        steps_output: list,
        vision_result: str,
        features: dict,
        process_type: str,
        kb_text: str,
        hours_estimate: str,
        quote_data: dict,
        has_kb_data: bool = True,
    ) -> dict:
        """组合 6 步结构化输出 → LINE 消息

        Args:
            steps_output: 各步骤输出列表
            vision_result: Step 1 原始结果
            features: Step 2 特征
            process_type: Step 3 工艺类型
            kb_text: Step 4 KB 文本
            hours_estimate: Step 5 工时估算
            quote_data: Step 6 报价数据
            has_kb_data: KB 是否有真实匹配数据

        Returns:
            LINE 消息 dict
        """
        # 构建 6 步完整文字输出
        lines = [
            "📋 图纸分析报告（6步结构化）\n",
            "=" * 30,
            "",
            f"[Step 1] OCR/Vision 识别：",
            vision_result[:300] if len(vision_result) > 300 else vision_result,
            "",
            f"[Step 2] Feature Extraction：",
            f"- 材质: {features.get('material')}",
            f"- 数量: {features.get('quantity')}件",
            f"- 尺寸: {features.get('dimensions')}",
            f"- 重量: {features.get('weight_kg')}kg",
            f"- 板厚: {features.get('thickness')}",
            f"- 孔数: {features.get('hole_count')}个",
            f"- 对称性: {features.get('symmetry')}",
            f"- 结构类型: {features.get('structure_type')}",
            "",
            f"[Step 3] Process Classification：{process_type}",
            "",
            kb_text,
        ]

        # KB 有数据时才输出 Step 5 和 Step 6
        if has_kb_data and hours_estimate:
            lines.extend([
                "",
                f"[Step 5] Rule Engine 工时：",
                hours_estimate,
            ])

            # 添加 Step 6 报价（如有）
            if quote_data:
                pricing = quote_data.get("pricing", {})
                unit_price = pricing.get("unit_price", 0)
                lines.extend([
                    "",
                    f"[Step 6] LLM Output 报价：",
                    f"💰 参考单价：¥{unit_price:,}/件",
                    f"📅 预计交期：{quote_data.get('lead_time_days', 0)}天",
                ])
            else:
                lines.extend([
                    "",
                    "[Step 6] LLM Output：",
                    "⚠️ 报价生成中，请联系客服确认最终价格。",
                    "📎 风险提示：此报价仅为估算值，实际价格可能因图纸复杂度有所调整。",
                ])
        else:
            # KB 为空 → 跳过 Step 5 和 Step 6，提示联系客服
            lines.extend([
                "",
                f"[Step 5] Rule Engine 工时：",
                "⚠️ 跳过（KB无匹配数据）",
                "",
                "[Step 6] LLM Output：",
                "⚠️ 请联系客服获取准确报价",
            ])

        full_text = "\n".join(lines)

        # 检查文本长度，超长则用 Flex Message
        if len(full_text) > 2000:
            return self._create_6step_flex_message(
                steps_output=steps_output,
                features=features,
                process_type=process_type,
                quote_data=quote_data,
            )

        return {
            "type": "text",
            "text": full_text,
            "quickReply": {
                "items": [
                    {"type": "action", "action": {"type": "message", "label": "📝 确认报价", "text": "确认报价"}},
                    {"type": "action", "action": {"type": "message", "label": "🔧 修改参数", "text": "修改参数"}},
                    {"type": "action", "action": {"type": "message", "label": "📞 联系客服", "text": "人工报价"}},
                ]
            }
        }

    def _create_6step_flex_message(
        self,
        steps_output: list,
        features: dict,
        process_type: str,
        quote_data: dict,
    ) -> dict:
        """创建 6 步 Flex Message（文本过长时使用）"""
        # 提取关键信息
        material = features.get("material", "未知")
        quantity = features.get("quantity", 0)
        dimensions = features.get("dimensions", "未知")
        tolerance = features.get("tolerance", "普通")
        surface = features.get("surface", "无")
        weight_kg = features.get("weight_kg", 0)

        # 报价信息
        pricing_text = "报价生成中"
        lead_time_text = "待确认"
        if quote_data:
            pricing = quote_data.get("pricing", {})
            pricing_text = f"¥{pricing.get('unit_price', 0):,}/件"
            lead_time_text = f"{quote_data.get('lead_time_days', 0)}天"

        return {
            "type": "flex",
            "altText": "图纸分析报告",
            "contents": {
                "type": "carousel",
                "contents": [
                    {
                        "type": "bubble",
                        "header": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": "📋 图纸分析报告", "weight": "bold", "size": "lg"},
                                {"type": "text", "text": "6步结构化输出", "size": "sm", "color": "#888888"}
                            ]
                        },
                        "body": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": f"Step 1-2: 材质={material}, 数量={quantity}件", "wrap": True},
                                {"type": "text", "text": f"尺寸={dimensions}", "wrap": True},
                                {"type": "text", "text": f"板厚={features.get('thickness')}, 孔数={features.get('hole_count')}", "wrap": True},
                                {"type": "separator"},
                                {"type": "text", "text": f"Step 3: {process_type}", "weight": "bold"},
                                {"type": "text", "text": f"Step 4: KB相似搜索", "wrap": True},
                                {"type": "text", "text": f"Step 5: 工时估算", "wrap": True},
                            ]
                        },
                        "footer": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": f"💰 {pricing_text}", "weight": "bold", "color": "#FF0000"},
                                {"type": "text", "text": f"📅 交期: {lead_time_text}"},
                            ]
                        }
                    }
                ]
            }
        }

    async def _handle_material(self, text: str, reply_token: str) -> str:
        """处理材质查询"""
        # 从知识库查询材质价格
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/blueprint/agentic-search",
                    json={"query": text, "top_k": 3},
                )
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    if results:
                        return self._format_knowledge_reply(results, text)
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
        """Handle knowledge base search"""
        try:
            import httpx
            # Use HTTP API (reliable, already tested) instead of direct function call
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "http://127.0.0.1:8000/api/blueprint/agentic-search",
                    json={"query": text, "top_k": 5},
                )
                data = resp.json()
                results = data.get("results", [])
                if results:
                    return self._format_knowledge_reply(results, text)
            return await self._handle_ai_fallback(text)
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

    def _extract_section(self, content: str, keyword: str, context_chars: int = 600) -> str:
        """Extract paragraph block containing keyword (for precise answers)"""
        # Handle OR patterns (e.g. "検査対象製品|対象製品|品質検査")
        pattern = re.compile(keyword, re.IGNORECASE)
        match = pattern.search(content)
        if not match:
            return content[:400]
        # Find the nearest line boundary around the match
        start = max(0, match.start() - 100)
        end = min(len(content), match.end() + context_chars)
        # Adjust to nearest line break
        line_start = content.rfind('\n', 0, start) + 1
        line_end = content.find('\n', end)
        if line_end == -1:
            line_end = len(content)
        return content[line_start:line_end].strip()

    def _format_knowledge_reply(self, results: List[dict], user_query: str = "") -> str:
        """格式化知识库回复，精准提取相关内容"""
        if not results:
            return "📚 未找到相关内容"

        # 从用户查询中提取关键术语用于精确定位
        # 移除常见疑问词和助词，保留名词性关键词
        stop_words = {"の", "は", "が", "を", "に", "で", "と", "です", "ます", "か", "?", "？", "何", "什么", "哪些", "哪个"}
        query_terms = [t.strip() for t in re.split(r"[\s\?]", user_query) if t.strip() and t.strip() not in stop_words]
        # 取最后1-2个有实质意义的名词性词作为关键词（用户通常把核心问在后面）
        keyword = "|".join(query_terms[-2:]) if len(query_terms) >= 2 else (query_terms[0] if query_terms else "")

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "N/A")
            content = r.get("content", "")

            # 用用户查询词精准定位相关内容段落
            search_kw = keyword if keyword else "検査対象製品|対象製品|品質検査"
            # 缩小上下文，减少冗余表格/无关内容
            snippet = self._extract_section(content, search_kw, context_chars=200)

            lines.append(f"📋 {title}\n{snippet}\n")
            if i >= 2:
                break

        return "\n".join(lines) if lines else "📚 未找到相关内容"

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