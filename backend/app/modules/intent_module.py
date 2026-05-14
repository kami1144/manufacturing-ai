"""
Intent 模块 - LLM 意图分类

功能：
- 8个制造业意图类别
- LLM 意图识别（替代关键词匹配）
- 可回退到关键词匹配

依赖：
- AI_API_KEY（从 .env 读取）
"""

import asyncio
import os
import re
from typing import Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

# ── 意图类别定义 ─────────────────────────────────────────

INTENT_CATEGORIES = [
    "quote",      # 报价咨询
    "material",   # 材质咨询
    "process",   # 工艺咨询
    "blueprint", # 图纸查询
    "delivery",  # 交期查询
    "knowledge", # 知识库搜索
    "sample",    # 样品请求（新增）
    "complaint", # 投诉/售后（新增）
]

# 意图关键词（回退用）
INTENT_KEYWORDS = {
    "quote": ["报价", "价格", "多少钱", "cost", "price", "見積もり", "报价单", "核算"],
    "material": ["材质", "材料", "SUS", "SECC", "SPCC", "material", "铝合金", "钛合金"],
    "process": ["工艺", "工序", "加工", "CNC", "钣金", "process", "冲压", "铸造", "表面处理"],
    "blueprint": ["图纸", "CAD", "blueprint", "图", "公差", "尺寸"],
    "delivery": ["交期", "交验", "lead time", "納期", "货期", "何时"],
    "knowledge": ["知识", "规格", "标准", "spec", "什么是", "如何"],
    "sample": ["样品", "sample", "打样", "样件", "试件", "件"],
    "complaint": ["投诉", "抱怨", "质量", "问题", "售后", "退货", "索赔"],
}

# LLM 意图分类 System Prompt
INTENT_SYSTEM_PROMPT = """你是制造业意图分类器。请根据用户消息判断意图类别。

意图类别：
- quote: 报价咨询（问价格、报价、多少钱）
- material: 材质咨询（问材料、材质、选型）
- process: 工艺咨询（问工艺、加工方法、工序）
- blueprint: 图纸查询（问图纸、CAD、尺寸、公差）
- delivery: 交期查询（问交期、货期、何时交货）
- knowledge: 知识库搜索（问知识、规格、标准）
- sample: 样品请求（要样品、打样、试件）
- complaint: 投诉/售后（投诉、质量问题、售后）

只返回意图名称，不要其他内容。"""

# LLM 意图分类 User Prompt 模板
INTENT_USER_PROMPT = """用户消息：{message}

意图类别："""


class IntentClassifier:
    """LLM 意图分类器"""

    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY", "")
        self.model = os.getenv("AI_MODEL", "MiniMax-M2.7")
        self.base_url = "https://api.minimax.chat/v1"
        self.timeout = 15.0

    async def classify(self, text: str) -> str:
        """使用 LLM 分类意图

        Args:
            text: 用户消息

        Returns:
            意图类别
        """
        if not self.api_key:
            # 回退到关键词匹配
            return self._keyword_fallback(text)

        try:
            result = await self._llm_classify(text)
            if result:
                return result
            # LLM 失败，回退
            return self._keyword_fallback(text)
        except Exception as e:
            print(f"[WARN] Intent LLM failed: {e}, using keyword fallback")
            return self._keyword_fallback(text)

    async def _llm_classify(self, text: str) -> Optional[str]:
        """调用 LLM 分类

        Args:
            text: 用户消息

        Returns:
            意图类别 或 None
        """
        messages = [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": INTENT_USER_PROMPT.format(message=text)},
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
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
            data = response.json()
            base = data.get("base_resp", {})
            if base.get("status_code") and base.get("status_code") != 0:
                return None
            content = data["choices"][0]["message"]["content"]
            # 提取意图
            for intent in INTENT_CATEGORIES:
                if intent in content.lower():
                    return intent
            return None

    def classify_sync(self, text: str) -> str:
        """同步调用 classify（供同步上下文使用）。

        在已有事件循环中调用时用 asyncio.get_running_loop()；
        否则创建新循环。
        """
        try:
            loop = asyncio.get_running_loop()
            # 已在事件循环中：创建 task 在当前循环执行
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.classify(text))
                return future.result()
        except RuntimeError:
            # 没有运行中的事件循环
            return asyncio.run(self.classify(text))

    def _keyword_fallback(self, text: str) -> str:
        """关键词回退

        Args:
            text: 用户消息

        Returns:
            意图类别
        """
        text_lower = text.lower()
        for intent, keywords in INTENT_KEYWORDS.items():
            if any(kw.lower() in text_lower for kw in keywords):
                return intent
        return "knowledge"  # 默认


# 全局实例
intent_classifier = IntentClassifier()