"""
AI 模块 - MiniMax AI 对话

功能：
- 使用 MiniMax API 进行对话
- 认知翻译提示词

依赖：
- MINIMAX_API_KEY（从 .env 读取）
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

# System Prompt（认知翻译风格）
SYSTEM_PROMPT = """你是日本房产投资顾问助手，专门帮助中国投资者了解日本房产。

回答风格：
- 使用中文回答
- 日本房产术语使用认知翻译（类似中国概念解释）
- 例如：管理费=物业费，礼金=房东一次性好处费，利回り=投资回报率
- 简洁、专业、易懂

回答范围：
- 日本房源咨询（东京、大阪等主要城市）
- 费用说明（管理费、修缮费、固定资产税等）
- 投资规则（永住、签证、民宿合法、外国人贷款）
- 市场分析

注意：
- 只回答房产相关问题，非房产问题请礼貌拒绝"""


# User Prompt 前缀
USER_PROMPT_PREFIX = """用户问题："""


class AIClient:
    """MiniMax AI 客户端"""

    def __init__(self):
        self.api_key = os.getenv("MINIMAX_API_KEY", "")
        self.model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
        self.base_url = "https://api.minimax.chat/v1"
        self.timeout = 30.0

        if not self.api_key:
            print("[WARN] MINIMAX_API_KEY not set, AI will not work")

    def chat(self, message: str) -> str:
        """
        发送聊天消息

        Args:
            message: 用户消息

        Returns:
            AI 回复
        """
        if not self.api_key:
            return "抱歉，AI 服务暂时不可用。请稍后再试。"

        try:
            return self._call_api(message)
        except Exception as e:
            print(f"[ERROR] AI API failed: {e}")
            return "抱歉，AI 服务暂时不可用。请稍后再试。"

    def _call_api(self, message: str) -> str:
        """调用 MiniMax API"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_PREFIX + message},
        ]

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
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

            base = data.get("base_resp", {})
            if base.get("status_code") and base.get("status_code") != 0:
                return f"抱歉，AI 服务返回错误。请稍后再试。"

            content = data["choices"][0]["message"]["content"]
            return content

    async def chat_async(self, message: str) -> str:
        """
        异步聊天（供 FastAPI 路由使用）
        """
        if not self.api_key:
            return "抱歉，AI 服务暂时不可用。请稍后再试。"

        try:
            return await self._call_api_async(message)
        except Exception as e:
            print(f"[ERROR] AI API failed: {e}")
            return "抱歉，AI 服务暂时不可用。请稍后再试。"

    async def _call_api_async(self, message: str) -> str:
        """异步调用 MiniMax API"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_PREFIX + message},
        ]

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

            base = data.get("base_resp", {})
            if base.get("status_code") and base.get("status_code") != 0:
                return f"抱歉，AI 服务返回错误。请稍后再试。"

            content = data["choices"][0]["message"]["content"]
            return content


# 全局实例
ai_client = AIClient()


def call_ai(message: str) -> str:
    """
    便捷函数：调用 AI

    Args:
        message: 用户消息

    Returns:
        AI 回复
    """
    return ai_client.chat(message)


async def call_ai_async(message: str) -> str:
    """
    异步调用 AI

    Args:
        message: 用户消息

    Returns:
        AI 回复
    """
    return await ai_client.chat_async(message)