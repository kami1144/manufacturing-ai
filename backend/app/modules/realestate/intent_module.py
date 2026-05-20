"""
Intent 模块 - 房产意图分类

功能：
- 5个房产意图类别
- LLM 意图识别（替代关键词匹配）
- 可回退到关键词匹配

依赖：
- MINIMAX_API_KEY（从 .env 读取）
"""

import asyncio
import os
import re
from typing import Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

# ── 意图类别定义 ─────────────────────────────────────────

class IntentType:
    """意图类型枚举"""
    PROPERTY_INQUIRY = "property_inquiry"  # 房源咨询
    COST_EXPLANATION = "cost_explanation"   # 费用说明
    RULES_EXPLANATION = "rules_explanation" # 规则说明
    DOCUMENT_REQUEST = "document_request"   # 要资料
    GENERAL = "general"                      # 通用问题


INTENT_CATEGORIES = [
    IntentType.PROPERTY_INQUIRY,   # 房源咨询（区域/价格/收益率）
    IntentType.COST_EXPLANATION,   # 费用说明（初期费用/管理费/修缮费/贷款）
    IntentType.RULES_EXPLANATION,  # 规则说明（永住/签证/民宿合法/外国人贷款）
    IntentType.DOCUMENT_REQUEST,  # 要资料/户型图/PDF
    IntentType.GENERAL,           # 通用问题 → MiniMax AI
]

# 意图关键词（回退用）
INTENT_KEYWORDS = {
    IntentType.PROPERTY_INQUIRY: [
        "房源", "房子", "买房", "投资", "收益率", "利回り", "回报率",
        "价格", "租金", "租", "区域", " Tokyo", "大阪", "名古屋",
        "物业", "不动产", "物件", "一户建", "公寓", "MANSION",
        "新建", "中古", "築年数", "徒步", "駅", "学区"
    ],
    IntentType.COST_EXPLANATION: [
        "费用", "管理费", "修缮费", "积立金", "初期费用", "登录许可证",
        "固定資産税", "都市計画税", "火灾保险", "地震保险", "贷款", "按揭",
        "头金", "礼金", "敷金", "押金", "中介手续费", "佣金",
        "共益费", "管理会社", "修缮", "贷款"
    ],
    IntentType.RULES_EXPLANATION: [
        "永住", "签证", "在留资格", "民宿", "合法", "许可", "特区民宿",
        "外国人", "海外", "投资", "贷款条件", "税务", "所得税",
        "住民税", "申报", "节税", "水滴", "空家", "租赁",
        "条件", "申请", "资格"
    ],
    IntentType.DOCUMENT_REQUEST: [
        "资料", "户型图", "PDF", "文件", "发送", "邮箱", "-mail",
        "平面图", "内部", "照片", "我要", "提供", "样本", "报告",
        "分析", "数据", "详情", "详细"
    ],
    IntentType.GENERAL: [
        "什么", "如何", "怎样", "哪个", "可以", "应该", "为什么",
        "请问", "咨询", "了解", "知道", "询问", "帮助"
    ],
}

# LLM 意图分类 System Prompt
INTENT_SYSTEM_PROMPT = """你是日本房产意图分类器。请根据用户消息判断意图类别。

意图类别：
- property_inquiry: 房源咨询（问区域、房价、收益率、投资回报）
- cost_explanation: 费用说明（问管理费、修缮费、初期费用、贷款费用）
- rules_explanation: 规则说明（问永住、签证、民宿合法、外国人贷款条件）
- document_request: 要资料（要户型图、PDF、报告、发送到邮箱）
- general: 通用问题（其他问题，使用AI回答）

只返回意图名称，不要其他内容。"""

# LLM 意图分类 User Prompt 模板
INTENT_USER_PROMPT = """用户消息：{message}

意图类别："""


class IntentClassifier:
    """LLM 意图分类器"""

    def __init__(self):
        self.api_key = os.getenv("MINIMAX_API_KEY", "")
        self.model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
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
        return IntentType.GENERAL  # 默认


# 全局实例
intent_classifier = IntentClassifier()


def classify_intent(text: str) -> str:
    """便捷函数：同步分类意图

    Args:
        text: 用户消息

    Returns:
        意图类别
    """
    return intent_classifier.classify_sync(text)