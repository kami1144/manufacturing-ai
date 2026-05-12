# 报价规则配置说明

## 概述

本配置文件用于驱动报价规则引擎的可配置参数。可以修改 `default_rules.yaml` 来调整报价逻辑，而无需修改代码。

## 配置项说明

### material_process_map

材料到工艺的分类映射。键为材料牌号，值为工艺类型。

- `cnc_machining` - CNC加工
- `sheet_metal` - 钣金
- `die_casting` - 压铸

### labor_rates

工时费率，单位：日元/小时。

### material_rates

材料成本费率，单位：日元/kg。

### hour_coefficients

工时系数，用于计算每kg材料所需的工时（小时）。

计算公式：`total_hours = base_hours + (weight_kg * hour_coefficient)`

### base_hours

工艺基础工时（小时），每道工序的固定工时。

### surface_treatment_surface

表面处理加价表，单位：日元。

### tolerance_multipliers

公差等级系数，用于调整不同公差要求的成本。

- `normal` - 普通公差 (IT12-IT14)
- `high` - 高精度 (IT8-IT10)
- `ultra` - 超高精度 (IT5-IT6)

### lead_times

交期（天），从订单确认到交货的天数。

### profit_margin

利润率，0.15 表示 15% 利润率。

### volume_discounts

数量折扣配置。

- `min_quantity` - 最小数量
- `discount` - 折扣率（0.10 = 10% off）

## 使用方法

### 加载自定义规则

```python
from backend.app.modules.rules_engine import RulesEngine, get_default_rules

# 加载默认规则
rules = get_default_rules()

# 从自定义YAML加载规则
engine = RulesEngine.load_rules('/path/to/custom_rules.yaml')
```

### 生成报价

```python
from backend.app.modules.rules_engine import RulesEngine

engine = RulesEngine()
quote = engine.generate_quote(
    material='SUS304',
    weight_kg=2.5,
    quantity=100,
    surface_treatment='镀镍',
    tolerance='high'
)
print(quote)
```

## 修改规则

1. 编辑 `default_rules.yaml`
2. 确保YAML格式正确
3. 重新加载规则引擎

验证YAML格式：
```bash
python3 -c "import yaml; yaml.safe_load(open('backend/app/rules/default_rules.yaml'))"
```