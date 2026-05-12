"""
AI 模块 - 制造业 AI 对话

功能：
- MiniMax AI 对话（文字）
- 非规则问题 → AI 回复
- 制造业场景 System Prompt

依赖：AI_API_KEY（从 .env 读取）
"""

import os
import asyncio
import json
import httpx
from typing import Optional

# 制造业 System Prompt
MANUFACTURING_SYSTEM_PROMPT = """你是制造业报价助手，熟悉以下领域：
- CNC加工、钣金、冲压、铸造、表面处理
- 材料选型（SUS304、SECC、铝合金等）
- 工艺流程、工时估算、成本计算
- 图纸识读、尺寸标注、公差分析

回答风格：专业、简洁、直接给答案，不废话。
如果不懂的问题，如实说不知道，不要编造。"""


class AIManufacturing:
    """制造业 AI 对话"""

    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY", "")
        self.model = os.getenv("AI_MODEL", "MiniMax-M2.7")
        self.base_url = "https://api.minimax.chat/v1"
        self.timeout = 30.0

    async def chat(self, message: str, history: list[dict] = None) -> str:
        """
        发送对话，获取 AI 回复

        Args:
            message: 用户消息
            history: 对话历史 [{"role": "user"/"assistant", "content": "..."}]

        Returns:
            AI 回复文本
        """
        if not self.api_key:
            return "⚠️ AI 未配置，请联系管理员。"

        messages = [
            {"role": "system", "content": MANUFACTURING_SYSTEM_PROMPT}
        ]

        # 加入历史
        if history:
            for h in history[-10:]:  # 最多10条历史
                messages.append(h)

        messages.append({"role": "user", "content": message})

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/text/chatcompletion_v2",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.7,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            return "⏳ AI 响应超时，请稍后再试。"
        except httpx.HTTPStatusError as e:
            return f"⚠️ AI 服务错误：{e.response.status_code}"
        except Exception as e:
            return f"⚠️ AI 异常：{str(e)}"


# 全局实例
ai_manufacturing = AIManufacturing()
