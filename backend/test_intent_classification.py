"""
Intent Classification Test - 意图分类测试

测试：
- classify_sync() 同步方法
- 关键词回退
- 各种意图类型识别
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.modules.intent_module import IntentClassifier, INTENT_CATEGORIES


def test_classify_sync_quote():
    """测试报价意图"""
    classifier = IntentClassifier()
    result = classifier.classify_sync("请问这个产品多少钱？")
    print(f"[TEST] '请问这个产品多少钱？' -> {result}")
    assert result == "quote", f"Expected 'quote', got '{result}'"
    print("[PASS] test_classify_sync_quote")


def test_classify_sync_material():
    """测试材质意图"""
    classifier = IntentClassifier()
    # 用不包含"价格"的表述，避免与 quote 关键词冲突
    result = classifier.classify_sync("SUS304是什么材质？")
    print(f"[TEST] 'SUS304是什么材质？' -> {result}")
    assert result == "material", f"Expected 'material', got '{result}'"
    print("[PASS] test_classify_sync_material")


def test_classify_sync_process():
    """测试工艺意图"""
    classifier = IntentClassifier()
    result = classifier.classify_sync("CNC加工是怎么做的？")
    print(f"[TEST] 'CNC加工是怎么做的？' -> {result}")
    assert result == "process", f"Expected 'process', got '{result}'"
    print("[PASS] test_classify_sync_process")


def test_classify_sync_blueprint():
    """测试图纸意图"""
    classifier = IntentClassifier()
    result = classifier.classify_sync("请问有CAD图纸吗？")
    print(f"[TEST] '请问有CAD图纸吗？' -> {result}")
    assert result == "blueprint", f"Expected 'blueprint', got '{result}'"
    print("[PASS] test_classify_sync_blueprint")


def test_classify_sync_delivery():
    """测试交期意图"""
    classifier = IntentClassifier()
    result = classifier.classify_sync("交货期需要多久？")
    print(f"[TEST] '交货期需要多久？' -> {result}")
    assert result == "delivery", f"Expected 'delivery', got '{result}'"
    print("[PASS] test_classify_sync_delivery")


def test_classify_sync_knowledge():
    """测试知识库意图"""
    classifier = IntentClassifier()
    # 用明确不含材质名的知识问题
    result = classifier.classify_sync("什么是ISO9001标准？")
    print(f"[TEST] '什么是ISO9001标准？' -> {result}")
    assert result == "knowledge", f"Expected 'knowledge', got '{result}'"
    print("[PASS] test_classify_sync_knowledge")


def test_classify_sync_sample():
    """测试样品请求意图"""
    classifier = IntentClassifier()
    result = classifier.classify_sync("可以申请样品吗？")
    print(f"[TEST] '可以申请样品吗？' -> {result}")
    assert result == "sample", f"Expected 'sample', got '{result}'"
    print("[PASS] test_classify_sync_sample")


def test_classify_sync_complaint():
    """测试投诉意图"""
    classifier = IntentClassifier()
    result = classifier.classify_sync("产品质量有问题要投诉")
    print(f"[TEST] '产品质量有问题要投诉' -> {result}")
    assert result == "complaint", f"Expected 'complaint', got '{result}'"
    print("[PASS] test_classify_sync_complaint")


def test_intent_categories():
    """验证意图类别定义"""
    print(f"[TEST] INTENT_CATEGORIES: {INTENT_CATEGORIES}")
    expected = ["quote", "material", "process", "blueprint", "delivery", "knowledge", "sample", "complaint"]
    assert INTENT_CATEGORIES == expected, f"Expected {expected}, got {INTENT_CATEGORIES}"
    print("[PASS] test_intent_categories")


if __name__ == "__main__":
    print("=" * 50)
    print("Intent Classification Tests")
    print("=" * 50)

    try:
        test_intent_categories()
        test_classify_sync_quote()
        test_classify_sync_material()
        test_classify_sync_process()
        test_classify_sync_blueprint()
        test_classify_sync_delivery()
        test_classify_sync_knowledge()
        test_classify_sync_sample()
        test_classify_sync_complaint()

        print("=" * 50)
        print("ALL TESTS PASSED!")
        print("=" * 50)
    except Exception as e:
        print(f"[FAIL] {e}")
        sys.exit(1)