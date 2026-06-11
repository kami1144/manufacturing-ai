"""
Prompt Chain 管道 - 4步流水线

Step 1: Intent Classification → intent_module.IntentClassifier
Step 2: Retrieval → 根据intent选择检索策略
Step 3: Generation → AIManufacturing 生成回答
Step 4: Fact Check → fact_checker.FactChecker 校验

返回: {answer, intent, retrieved_docs, fact_check, needs_human, confidence}
confidence < 0.7 → needs_human=True
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from app.modules.intent_module import IntentClassifier, intent_classifier
from app.modules.kb_module import KnowledgeBase, get_kb
from app.modules.ai_module import AIManufacturing, ai_manufacturing


# ── FactChecker ─────────────────────────────────────────────────────────────

@dataclass
class FactCheckResult:
    """事实校验结果"""
    is_verified: bool       # 是否通过校验
    confidence: float       # 置信度 0.0-1.0
    warnings: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)


class FactChecker:
    """回答事实校验器"""

    def __init__(self):
        self.kb: KnowledgeBase = get_kb()

    async def check(self, question: str, answer: str, retrieved_docs: list[dict]) -> FactCheckResult:
        """
        校验回答的事实正确性

        Args:
            question: 用户问题
            answer: AI 生成的答案
            retrieved_docs: 检索到的参考文档

        Returns:
            FactCheckResult: 校验结果
        """
        if not answer or len(answer.strip()) < 5:
            return FactCheckResult(
                is_verified=False,
                confidence=0.0,
                warnings=["回答过短或为空"]
            )

        # 如果没有参考文档（retrieval 失败），降低置信度
        if not retrieved_docs:
            return FactCheckResult(
                is_verified=False,
                confidence=0.4,
                warnings=["未能检索到参考文档"]
            )

        # 基础校验：检查回答是否包含检索到的关键信息
        warnings = []
        corrections = []
        verified_facts = 0
        total_facts = len(retrieved_docs)

        for doc in retrieved_docs:
            doc_text = doc.get("content", "") or doc.get("text", "")
            doc_title = doc.get("title", "")

            # 检查回答是否引用了文档中的关键内容
            # 简单策略：提取文档中的数值/规格信息，检查是否出现在回答中
            import re
            # 提取可能的规格值（如：≥520 MPa, Ra1.6, ±0.05mm 等）
            specs = re.findall(r'[\d.]+\s*(?:MPa|mm|μm|g/cm³|°C|W/|HB|HV|kg|AQL|Ra)', doc_text)

            if specs:
                # 至少有一个规格出现在回答中，算验证通过
                found = any(spec in answer for spec in specs[:3])  # 最多检查前3个规格
                if found:
                    verified_facts += 1
                # else: 不警告，因为多文档检索时只匹配部分是正确的

        # 计算置信度：至少验证了一个就算通过
        if verified_facts > 0:
            base_confidence = 0.85  # 有验证通过，给较高置信度
        elif total_facts > 0:
            base_confidence = 0.5  # 有文档但没匹配到
        else:
            base_confidence = 0.5

        # 额外检查：回答长度是否合理
        if len(answer) < 50:
            base_confidence *= 0.7
            warnings.append("回答过短，可能不够详细")
        elif len(answer) > 2000:
            base_confidence *= 0.9  # 过长略降置信度

        # 检查回答是否包含"不知道"类表述
        uncertain_keywords = ["不知道", "不清楚", "无法确定", "暂无", "未找到", "无法回答"]
        if any(kw in answer for kw in uncertain_keywords):
            base_confidence *= 0.6
            warnings.append("回答包含不确定性表述")

        is_verified = base_confidence >= 0.7

        return FactCheckResult(
            is_verified=is_verified,
            confidence=round(base_confidence, 3),
            warnings=warnings,
            corrections=corrections
        )


# ── Retrieval Strategies ────────────────────────────────────────────────────

class RetrievalStrategy:
    """检索策略基类"""

    async def search(self, query: str, kb: KnowledgeBase, top_k: int = 5) -> list[dict]:
        raise NotImplementedError


class KnowledgeRetrieval(RetrievalStrategy):
    """知识库检索 - embedding向量化搜索"""

    async def search(self, query: str, kb: KnowledgeBase, top_k: int = 5) -> list[dict]:
        return kb.vector_search(query, top_k=top_k)


class KeywordRetrieval(RetrievalStrategy):
    """关键词检索 - 混合关键词+embedding"""

    async def search(self, query: str, kb: KnowledgeBase, top_k: int = 5) -> list[dict]:
        # 先关键词搜索
        keyword_results = kb.search(query, top_k=top_k)
        if keyword_results:
            return keyword_results
        # 回退到向量搜索
        return kb.vector_search(query, top_k=top_k)


class QuoteRetrieval(RetrievalStrategy):
    """报价检索 - 关键词+embedding混合"""

    async def search(self, query: str, kb: KnowledgeBase, top_k: int = 5) -> list[dict]:
        # 报价场景：先关键词匹配材质/工艺，再向量搜索
        keyword_results = kb.search(query, top_k=top_k)
        vector_results = kb.vector_search(query, top_k=top_k)

        # 合并去重，按分数排序
        seen = set()
        merged = []
        for r in keyword_results:
            key = r.get("title", "")
            if key not in seen:
                seen.add(key)
                r["score"] = r.get("score", 0) + 0.1  # 关键词匹配加分
                merged.append(r)
        for r in vector_results:
            key = r.get("title", "")
            if key not in seen:
                seen.add(key)
                merged.append(r)

        merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        return merged[:top_k]


# ── Intent → Retrieval Strategy 映射 ───────────────────────────────────────

INTENT_RETRIEVAL_MAP = {
    "quote": QuoteRetrieval,
    "material": KeywordRetrieval,
    "process": KeywordRetrieval,
    "blueprint": KeywordRetrieval,
    "delivery": KeywordRetrieval,
    "knowledge": KnowledgeRetrieval,
    "sample": KeywordRetrieval,
    "complaint": KeywordRetrieval,
}


# ── PromptChain 主类 ────────────────────────────────────────────────────────

@dataclass
class ChainResult:
    """管道返回结果"""
    answer: str
    intent: str
    retrieved_docs: list[dict]
    fact_check: FactCheckResult
    needs_human: bool
    confidence: float


# 别名（兼容测试）
PromptChainResult = ChainResult
ChainResult = ChainResult  # 兼容测试文件


class PromptChain:
    """
    4步 Prompt Chain 管道

    Step 1: Intent Classification
    Step 2: Retrieval (intent-dependent strategy)
    Step 3: Generation (AIManufacturing)
    Step 4: Fact Check
    """

    def __init__(
        self,
        intent_classifier: IntentClassifier = None,
        ai_client: AIManufacturing = None,
        fact_checker: FactChecker = None,
    ):
        self.intent_classifier = intent_classifier or IntentClassifier()
        self.ai_client = ai_client or ai_manufacturing
        self.fact_checker = fact_checker or FactChecker()
        self.kb = get_kb()

    def _get_retrieval_strategy(self, intent: str) -> RetrievalStrategy:
        """根据意图获取检索策略"""
        strategy_class = INTENT_RETRIEVAL_MAP.get(intent, KeywordRetrieval)
        return strategy_class()

    async def run(self, user_message: str) -> ChainResult:
        """
        执行完整管道

        Args:
            user_message: 用户消息

        Returns:
            ChainResult: 包含 answer, intent, retrieved_docs, fact_check, needs_human, confidence
        """
        # ── Step 1: Intent Classification ─────────────────────────────────
        intent = await self.intent_classifier.classify(user_message)

        # ── Step 2: Retrieval ─────────────────────────────────────────────
        strategy = self._get_retrieval_strategy(intent)
        retrieved_docs = await strategy.search(user_message, self.kb, top_k=5)

        # 构建 context 用于生成
        context = self._build_context(retrieved_docs)

        # ── Step 3: Generation ────────────────────────────────────────────
        prompt = self._build_prompt(user_message, intent, context)
        answer = await self.ai_client.chat(prompt)

        # ── Step 4: Fact Check ────────────────────────────────────────────
        fact_check = await self.fact_checker.check(user_message, answer, retrieved_docs)

        # 判断是否需要人工介入
        needs_human = fact_check.confidence < 0.7

        return ChainResult(
            answer=answer,
            intent=intent,
            retrieved_docs=retrieved_docs,
            fact_check=fact_check,
            needs_human=needs_human,
            confidence=fact_check.confidence,
        )

    def _build_context(self, retrieved_docs: list[dict]) -> str:
        """构建检索上下文"""
        if not retrieved_docs:
            return "（未检索到相关参考文档）"

        context_parts = []
        for i, doc in enumerate(retrieved_docs, 1):
            title = doc.get("title", "未知")
            content = doc.get("content", "") or doc.get("text", "")
            score = doc.get("score", 0)
            context_parts.append(
                f"[文档{i}] {title}（相关度:{score:.2f}）\n{content[:300]}"
            )

        return "\n\n".join(context_parts)

    def _build_prompt(self, user_message: str, intent: str, context: str) -> str:
        """构建完整 prompt"""
        intent_hints = {
            "quote": "用户可能在询问报价，请提供参考价格范围和交期。",
            "material": "用户询问材质相关问题，请提供材质规格参数。",
            "process": "用户询问工艺相关问题，请提供工艺流程和参数。",
            "blueprint": "用户询问图纸相关问题，请提供解读和建议。",
            "delivery": "用户询问交期相关问题，请提供标准交期。",
            "knowledge": "用户进行知识库搜索，请提供相关知识。",
            "sample": "用户请求样品，请说明样品流程和要求。",
            "complaint": "用户投诉或反馈问题，请认真对待并提供解决方案。",
        }
        hint = intent_hints.get(intent, "")

        return f"""参考文档：
{context}

{hint}

用户问题：{user_message}

请根据参考文档回答用户问题。如果参考文档不足以回答，请明确说明。
回答要求：专业、简洁、直接给答案。
"""


# ── 全局实例 ────────────────────────────────────────────────────────────────

prompt_chain = PromptChain()


# ── 便捷入口 ────────────────────────────────────────────────────────────────

async def process(user_message: str) -> ChainResult:
    """便捷入口：直接处理用户消息"""
    return await prompt_chain.run(user_message)


# ── 集成测试 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    async def test():
        print("=" * 60)
        print("PromptChain 集成测试")
        print("=" * 60)

        chain = PromptChain()

        test_cases = [
            "SUS304不锈钢的抗拉强度是多少？",
            "CNC加工的工艺流程是什么？",
            "请问这个产品多少钱？",
            "交期需要多久？",
        ]

        for msg in test_cases:
            print(f"\n{'─' * 60}")
            print(f"用户: {msg}")
            try:
                result = await chain.run(msg)
                print(f"意图: {result.intent}")
                print(f"置信度: {result.confidence} | 需要人工: {result.needs_human}")
                print(f"检索到文档数: {len(result.retrieved_docs)}")
                if result.retrieved_docs:
                    print(f"  Top1: {result.retrieved_docs[0].get('title', 'N/A')}")
                print(f"回答:\n{result.answer[:200]}...")
                if result.fact_check.warnings:
                    print(f"⚠️ 警告: {result.fact_check.warnings}")
            except Exception as e:
                print(f"❌ 错误: {e}")
                import traceback
                traceback.print_exc()

        print(f"\n{'=' * 60}")
        print("测试完成")

    asyncio.run(test())