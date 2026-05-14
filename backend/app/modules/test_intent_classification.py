"""
Intent Classification 单元测试

运行方式：
cd ~/manufacturing-ai/backend
python -m pytest app/modules/test_intent_classification.py -v
"""

import pytest
import asyncio
from app.modules.intent_module import IntentClassifier, INTENT_CATEGORIES, INTENT_KEYWORDS


@pytest.fixture
def classifier():
    return IntentClassifier()


# ── 基础验证 ─────────────────────────────────────────

def test_intent_categories_valid(classifier):
    """所有定义的意图类别都是有效的"""
    valid = {"quote", "material", "process", "blueprint", "delivery", "knowledge", "sample", "complaint"}
    assert set(INTENT_CATEGORIES) == valid


def test_intent_keywords_cover_all_categories(classifier):
    """每个意图类别都有对应的关键词"""
    for intent in INTENT_CATEGORIES:
        assert intent in INTENT_KEYWORDS, f"Missing keywords for {intent}"
        assert len(INTENT_KEYWORDS[intent]) > 0, f"Empty keywords for {intent}"


# ── Fallback 规则测试 ─────────────────────────────────────────

FALLBACK_TEST_CASES = [
    # (输入, 期望意图)
    ("这个多少钱", "quote"),
    ("初次合作，想了解下你们的定价", "quote"),
    ("收到货了但是不太满意", "complaint"),
    ("东西到了有问题", "complaint"),
    ("这个零件的公差是多少", "blueprint"),
    ("订单什么时候能好", "delivery"),
    ("你们用SUS304吗", "material"),
    ("支持CNC加工吗", "process"),
    ("今天天气不错", "knowledge"),
    ("可以打样吗", "sample"),
    ("我要报价", "quote"),
    ("质量问题很严重", "complaint"),
]


def test_fallback_classify_valid_intent(classifier):
    """Fallback 返回有效的意图类别"""
    for text, expected in FALLBACK_TEST_CASES:
        result = classifier._keyword_fallback(text)
        assert result in INTENT_CATEGORIES, f"Input: {text}, Got: {result}"


def test_fallback_classify_correct_intent(classifier):
    """Fallback 分类准确性（允许部分偏差）"""
    deviations = 0
    for text, expected in FALLBACK_TEST_CASES:
        result = classifier._keyword_fallback(text)
        if result != expected:
            deviations += 1
            print(f"[偏差] 输入: {text!r} → 期望: {expected}, 实际: {result}")
    # 允许30%偏差（Fallback 用规则，LLM 会弥补）
    assert deviations <= len(FALLBACK_TEST_CASES) * 0.3, f"偏差过多: {deviations}/{len(FALLBACK_TEST_CASES)}"


# ── classify_sync 测试（同步调用） ─────────────────────────────────────────

def test_classify_sync_returns_valid_intent(classifier):
    """classify_sync 返回有效意图"""
    for text, _ in FALLBACK_TEST_CASES[:5]:
        result = classifier.classify_sync(text)
        assert result in INTENT_CATEGORIES, f"Input: {text}, Got: {result}"


def test_classify_sync_no_exception(classifier):
    """classify_sync 不抛出异常"""
    test_messages = [
        "这个报价多少",
        "东西坏了",
        "你好",
        " ",
        "",
    ]
    for msg in test_messages:
        try:
            result = classifier.classify_sync(msg)
            assert result in INTENT_CATEGORIES
        except Exception as e:
            pytest.fail(f"classify_sync raised exception for {msg!r}: {e}")


# ── 意图覆盖完整性测试 ─────────────────────────────────────────

def test_all_intents_have_handlers_in_line_module():
    """验证所有意图在 line_module.py 中都有对应 handler"""
    from app.modules.line_module import ManufacturingLINEBot
    bot = ManufacturingLINEBot()
    # 确保 process_message 中的 if/elif 覆盖所有意图
    # 这是一个 smoke test：导入不报错就说明结构OK
    assert hasattr(bot, '_handle_quote')
    assert hasattr(bot, '_handle_complaint')
    assert hasattr(bot, '_handle_sample')
    assert hasattr(bot, '_handle_material')
    assert hasattr(bot, '_handle_process')
    assert hasattr(bot, '_handle_blueprint')
    assert hasattr(bot, '_handle_delivery')
    assert hasattr(bot, '_handle_knowledge')
    assert hasattr(bot, '_handle_general')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
