"""
报价规则引擎单元测试

覆盖：
1. 数量段阶梯报价边界测试
2. 空规则文件异常处理
"""
import pytest
import tempfile
import os
from pathlib import Path
from rules_engine import RulesEngine, QuantityTier, get_default_rules


class TestQuantityTierBoundaries:
    """数量段阶梯报价边界测试"""

    @pytest.fixture
    def tiered_rules(self):
        """配置固定数量段的规则引擎"""
        rules = get_default_rules()
        rules.quantity_tiers = [
            QuantityTier(min_quantity=1, max_quantity=10, unit_price=12000),      # 1-9件
            QuantityTier(min_quantity=10, max_quantity=50, unit_price=8500),      # 10-49件
            QuantityTier(min_quantity=50, max_quantity=100, unit_price=6500),    # 50-99件
            QuantityTier(min_quantity=100, max_quantity=500, unit_price=5000),   # 100-499件
            QuantityTier(min_quantity=500, max_quantity=-1, unit_price=3800),  # 500+件
        ]
        return RulesEngine(rules)

    def test_tier_1_boundary(self, tiered_rules):
        """测试第1段边界：1件和9件"""
        # 1件 -> 第1段 (1-9)
        result = tiered_rules.calculate_tiered_price(1)
        assert result is not None
        assert result['tier_min'] == 1
        assert result['tier_max'] == 10
        assert result['unit_price'] == 12000
        assert result['total_price'] == 12000

        # 9件 -> 第1段 (1-9)
        result = tiered_rules.calculate_tiered_price(9)
        assert result is not None
        assert result['unit_price'] == 12000

    def test_tier_2_boundary(self, tiered_rules):
        """测试第2段边界：10件和49件"""
        # 10件 -> 第2段 (10-49)，注意：10是下界，包含10
        result = tiered_rules.calculate_tiered_price(10)
        assert result is not None
        assert result['tier_min'] == 10
        assert result['tier_max'] == 50
        assert result['unit_price'] == 8500
        assert result['total_price'] == 85000

        # 49件 -> 第2段 (10-49)
        result = tiered_rules.calculate_tiered_price(49)
        assert result is not None
        assert result['unit_price'] == 8500

    def test_tier_3_boundary(self, tiered_rules):
        """测试第3段边界：50件和99件"""
        # 50件 -> 第3段 (50-99)
        result = tiered_rules.calculate_tiered_price(50)
        assert result is not None
        assert result['tier_min'] == 50
        assert result['tier_max'] == 100
        assert result['unit_price'] == 6500

        # 99件 -> 第3段 (50-99)
        result = tiered_rules.calculate_tiered_price(99)
        assert result is not None
        assert result['unit_price'] == 6500

    def test_tier_4_boundary(self, tiered_rules):
        """测试第4段边界：100件和499件"""
        # 100件 -> 第4段 (100-499)
        result = tiered_rules.calculate_tiered_price(100)
        assert result is not None
        assert result['tier_min'] == 100
        assert result['tier_max'] == 500
        assert result['unit_price'] == 5000

        # 499件 -> 第4段 (100-499)
        result = tiered_rules.calculate_tiered_price(499)
        assert result is not None
        assert result['unit_price'] == 5000

    def test_tier_5_boundary_infinite(self, tiered_rules):
        """测试第5段边界：500件及以上（无限）"""
        # 500件 -> 第5段 (500+)
        result = tiered_rules.calculate_tiered_price(500)
        assert result is not None
        assert result['tier_min'] == 500
        assert result['tier_max'] == -1  # 无限
        assert result['unit_price'] == 3800
        assert result['total_price'] == 1900000

        # 1000件 -> 第5段 (500+)
        result = tiered_rules.calculate_tiered_price(1000)
        assert result is not None
        assert result['unit_price'] == 3800
        assert result['total_price'] == 3800000

    def test_tier_edge_cases(self, tiered_rules):
        """测试边界临界情况"""
        # 边界值0应该返回None（没有匹配的第0段）
        result = tiered_rules.calculate_tiered_price(0)
        # 0不在任何段范围内，应该返回None
        # 因为min_quantity=1是最小段，0<1所以不匹配
        assert result is None

    def test_tier_name_format(self, tiered_rules):
        """测试段名称格式"""
        # 有限区间: "min-max-1"
        result = tiered_rules.calculate_tiered_price(50)
        assert result['tier_name'] == "50-99"

        # 无限区间: "min+"
        result = tiered_rules.calculate_tiered_price(500)
        assert result['tier_name'] == "500+"


class TestEmptyRulesFileHandling:
    """空规则文件异常处理测试"""

    def test_empty_yaml_file(self):
        """测试空YAML文件加载"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write('')  # 写入空内容
            temp_path = f.name

        try:
            # 空文件应该能正常加载，使用默认规则
            engine = RulesEngine.load_rules(temp_path)
            assert engine is not None
            # 应该返回默认规则引擎
            result = engine.generate_quote('SUS304', 1.0, 1)
            assert result['material'] == 'SUS304'
        finally:
            os.unlink(temp_path)

    def test_missing_yaml_file(self):
        """测试不存在的YAML文件加载"""
        # 不存在的文件路径应返回默认规则
        engine = RulesEngine.load_rules('/nonexistent/path/rules.yaml')
        assert engine is not None
        result = engine.generate_quote('SUS304', 1.0, 1)
        assert result['material'] == 'SUS304'

    def test_invalid_yaml_file(self):
        """测试无效YAML文件加载"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write('invalid: yaml: content:')  # 无效YAML
            temp_path = f.name

        try:
            # yaml.safe_load在无效内容时会抛出异常
            with pytest.raises(yaml.YAMLError):
                RulesEngine.load_rules(temp_path)
        finally:
            os.unlink(temp_path)

    def test_partially_invalid_yaml_file(self):
        """测试部分无效YAML文件加载（缺少必需字段）"""
        # 创建一个只有部分字段的YAML，应该能正常加载默认值
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write('material_process_map:\n  SUS304: cnc_machining\n')  # 只有部分字段
            temp_path = f.name

        try:
            engine = RulesEngine.load_rules(temp_path)
            assert engine is not None
            # 默认值应该被填充
            result = engine.generate_quote('SUS304', 1.0, 1)
            assert result['material'] == 'SUS304'
        finally:
            os.unlink(temp_path)


# 导入yaml以在测试中使用
import yaml