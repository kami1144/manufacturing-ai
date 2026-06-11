"""
PromptChain 集成测试

运行方式：
    cd ~/manufacturing-ai/backend
    python -m pytest app/modules/test_prompt_chain.py -v

或直接运行：
    python app/modules/test_prompt_chain.py
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.prompt_chain import (
    PromptChain,
    PromptChainResult,
    ChainResult,
    FactChecker,
    FactCheckResult,
    KnowledgeRetrieval,
    KeywordRetrieval,
    QuoteRetrieval,
    INTENT_RETRIEVAL_MAP,
)


# ── Mock 数据 ────────────────────────────────────────────────────────────────

MOCK_RETRIEVED_DOCS = [
    {
        "title": "SUS304不锈钢材质规格",
        "content": "抗拉强度: ≥520 MPa | 屈服强度: ≥205 MPa | 延伸率: ≥40%",
        "category": "material",
        "score": 0.95,
        "source": "SUS304.md"
    },
    {
        "title": "AL5052铝合金材质规格",
        "content": "抗拉强度: 193-269 MPa | 屈服强度: ≥65 MPa",
        "category": "material",
        "score": 0.80,
        "source": "AL5052.md"
    },
]

MOCK_ANSWER_WITH_FACTS = (
    "SUS304不锈钢的抗拉强度为≥520 MPa，屈服强度为≥205 MPa，"
    "延伸率≥40%，密度8.00 g/cm³，符合JIS G4303标准。"
)

MOCK_ANSWER_SHORT = "SUS304是一种不锈钢。"

MOCK_ANSWER_UNCERTAIN = "我不清楚SUS304的具体抗拉强度，需要查一下资料。"


# ── Tests for FactChecker ────────────────────────────────────────────────────

class TestFactChecker:
    """FactChecker 单元测试"""

    def setup_method(self):
        self.checker = FactChecker.__new__(FactChecker)  # 跳过 __init__

    def test_check_with_matching_facts(self):
        """测试：回答包含文档中的规格信息 → 高置信度"""
        result = asyncio.run(self.checker.check(
            question="SUS304抗拉强度是多少？",
            answer=MOCK_ANSWER_WITH_FACTS,
            retrieved_docs=MOCK_RETRIEVED_DOCS
        ))

        assert result.confidence >= 0.7
        assert result.is_verified is True
        assert len(result.warnings) == 0

    def test_check_with_short_answer(self):
        """测试：回答过短 → 置信度降低"""
        result = asyncio.run(self.checker.check(
            question="SUS304抗拉强度是多少？",
            answer=MOCK_ANSWER_SHORT,
            retrieved_docs=MOCK_RETRIEVED_DOCS
        ))

        assert result.confidence < 0.7
        assert any("过短" in w for w in result.warnings)

    def test_check_with_uncertain_answer(self):
        """测试：回答包含不确定性表述 → 置信度降低"""
        result = asyncio.run(self.checker.check(
            question="SUS304抗拉强度是多少？",
            answer=MOCK_ANSWER_UNCERTAIN,
            retrieved_docs=MOCK_RETRIEVED_DOCS
        ))

        assert result.confidence < 0.6
        assert any("不确定性" in w for w in result.warnings)

    def test_check_with_no_docs(self):
        """测试：无参考文档 → 低置信度"""
        result = asyncio.run(self.checker.check(
            question="SUS304抗拉强度是多少？",
            answer=MOCK_ANSWER_WITH_FACTS,
            retrieved_docs=[]
        ))

        assert result.confidence < 0.5
        assert result.is_verified is False

    def test_check_empty_answer(self):
        """测试：空回答 → 最低置信度"""
        result = asyncio.run(self.checker.check(
            question="SUS304抗拉强度是多少？",
            answer="",
            retrieved_docs=MOCK_RETRIEVED_DOCS
        ))

        assert result.confidence == 0.0
        assert result.is_verified is False


# ── Tests for Retrieval Strategies ─────────────────────────────────────────

class TestRetrievalStrategies:
    """检索策略单元测试"""

    def test_intent_retrieval_map_complete(self):
        """测试：所有意图都有对应策略"""
        expected_intents = {"quote", "material", "process", "blueprint", "delivery", "knowledge", "sample", "complaint"}
        assert set(INTENT_RETRIEVAL_MAP.keys()) == expected_intents

    def test_knowledge_retrieval_class(self):
        """测试：KnowledgeRetrieval 是有效的检索策略"""
        strategy = KnowledgeRetrieval()
        assert hasattr(strategy, "search")
        assert asyncio.iscoroutinefunction(strategy.search)

    def test_keyword_retrieval_class(self):
        """测试：KeywordRetrieval 是有效的检索策略"""
        strategy = KeywordRetrieval()
        assert hasattr(strategy, "search")
        assert asyncio.iscoroutinefunction(strategy.search)

    def test_quote_retrieval_class(self):
        """测试：QuoteRetrieval 是有效的检索策略"""
        strategy = QuoteRetrieval()
        assert hasattr(strategy, "search")
        assert asyncio.iscoroutinefunction(strategy.search)


# ── Tests for PromptChain ────────────────────────────────────────────────────

class TestPromptChain:
    """PromptChain 集成测试"""

    def setup_method(self):
        """跳过真实初始化的快速 setup"""
        self.mock_intent_classifier = AsyncMock()
        self.mock_intent_classifier.classify = AsyncMock(return_value="material")

        self.mock_ai_client = AsyncMock()
        self.mock_ai_client.chat = AsyncMock(return_value=MOCK_ANSWER_WITH_FACTS)

        self.mock_fact_checker = AsyncMock()
        self.mock_fact_checker.check = AsyncMock(return_value=FactCheckResult(
            is_verified=True,
            confidence=0.85,
            warnings=[],
            corrections=[]
        ))

        self.chain = PromptChain.__new__(PromptChain)
        self.chain.intent_classifier = self.mock_intent_classifier
        self.chain.ai_client = self.mock_ai_client
        self.chain.fact_checker = self.mock_fact_checker
        self.chain.kb = MagicMock()

    @pytest.mark.asyncio
    async def test_run_returns_chain_result(self):
        """测试：run() 返回 ChainResult"""
        result = await self.chain.run("SUS304抗拉强度是多少？")

        assert isinstance(result, ChainResult)
        assert result.intent == "material"
        assert result.answer == MOCK_ANSWER_WITH_FACTS
        assert result.confidence == 0.85
        assert result.needs_human is False  # 0.85 >= 0.7

    @pytest.mark.asyncio
    async def test_run_low_confidence_needs_human(self):
        """测试：confidence < 0.7 → needs_human=True"""
        self.chain.fact_checker.check = AsyncMock(return_value=FactCheckResult(
            is_verified=False,
            confidence=0.5,
            warnings=["未检索到参考文档"],
            corrections=[]
        ))

        result = await self.chain.run("SUS304抗拉强度是多少？")

        assert result.confidence == 0.5
        assert result.needs_human is True

    @pytest.mark.asyncio
    async def test_run_calls_all_steps(self):
        """测试：run() 依次调用各步骤"""
        await self.chain.run("测试消息")

        # Step 1: intent classifier 被调用
        self.mock_intent_classifier.classify.assert_called_once_with("测试消息")

        # Step 3: AI client 被调用（参数包含 context）
        self.mock_ai_client.chat.assert_called_once()
        call_args = self.mock_ai_client.chat.call_args[0][0]
        assert "参考文档" in call_args
        assert "测试消息" in call_args

        # Step 4: fact checker 被调用
        self.chain.fact_checker.check.assert_called_once()

    def test_build_context(self):
        """测试：_build_context 正确格式化文档"""
        context = self.chain._build_context(MOCK_RETRIEVED_DOCS)

        assert "文档1" in context
        assert "SUS304不锈钢材质规格" in context
        assert "≥520 MPa" in context
        assert "文档2" in context

    def test_build_context_empty(self):
        """测试：空文档列表 → 返回默认值"""
        context = self.chain._build_context([])
        assert "未检索到" in context

    def test_build_prompt(self):
        """测试：_build_prompt 包含意图提示"""
        prompt = self.chain._build_prompt(
            user_message="SUS304是什么？",
            intent="material",
            context="参考文档内容..."
        )

        assert "参考文档" in prompt
        assert "SUS304是什么？" in prompt
        assert "材质" in prompt  # material 意图有对应提示

    def test_get_retrieval_strategy(self):
        """测试：意图 → 检索策略映射正确"""
        chain = self.chain

        assert isinstance(chain._get_retrieval_strategy("knowledge"), KnowledgeRetrieval)
        assert isinstance(chain._get_retrieval_strategy("quote"), QuoteRetrieval)
        assert isinstance(chain._get_retrieval_strategy("material"), KeywordRetrieval)
        assert isinstance(chain._get_retrieval_strategy("process"), KeywordRetrieval)

    @pytest.mark.asyncio
    async def test_retrieval_strategy_search(self):
        """测试：检索策略实际搜索知识库"""
        mock_kb = MagicMock()
        mock_kb.vector_search.return_value = MOCK_RETRIEVED_DOCS

        strategy = KnowledgeRetrieval()
        results = await strategy.search("SUS304", mock_kb, top_k=5)

        mock_kb.vector_search.assert_called_once_with("SUS304", top_k=5)
        assert len(results) == 2


# ── Tests for ChainResult dataclass ─────────────────────────────────────────

class TestChainResult:
    """ChainResult 数据类测试"""

    def test_chain_result_fields(self):
        """测试：ChainResult 包含所有必要字段"""
        fc = FactCheckResult(is_verified=True, confidence=0.8)
        result = ChainResult(
            answer="测试回答",
            intent="material",
            retrieved_docs=MOCK_RETRIEVED_DOCS,
            fact_check=fc,
            needs_human=False,
            confidence=0.8
        )

        assert result.answer == "测试回答"
        assert result.intent == "material"
        assert len(result.retrieved_docs) == 2
        assert result.fact_check.is_verified is True
        assert result.needs_human is False
        assert result.confidence == 0.8

    def test_needs_human_when_confidence_below_07(self):
        """测试：confidence < 0.7 时 needs_human=True"""
        fc = FactCheckResult(is_verified=False, confidence=0.65)
        result = ChainResult(
            answer="测试",
            intent="knowledge",
            retrieved_docs=[],
            fact_check=fc,
            needs_human=True,
            confidence=0.65
        )

        assert result.needs_human is True
        assert result.confidence < 0.7


# ── 运行入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])