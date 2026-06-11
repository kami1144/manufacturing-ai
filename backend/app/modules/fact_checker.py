"""
Fact Checker 模块 - 回答与文档一致性验证

功能：
- 调用 MiniMax LLM 对比「LLM生成的回答」vs「原始文档」
- 检测数字/名称矛盾、幻觉、遗漏关键信息
- 返回结构化验证结果

依赖：ai_module 中的 AIManufacturing
"""

import os
import json
import httpx
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()


# ── 检查标准 System Prompt ──────────────────────────────────────────────

FACT_CHECK_SYSTEM_PROMPT = """你是事实核查员，专门验证回答是否与原始文档一致。

检查标准：
1. **数字矛盾**：答案中的数值（数量/尺寸/价格/公差等）必须与文档完全一致，不允许四舍五入或估算
2. **名称矛盾**：材质名/工艺名/产品型号等专有名词必须准确匹配，不允许同义词替换
3. **幻觉检测**：答案中出现的任何信息（特征/参数/说明）必须能在文档中找到依据
4. **遗漏检测**：文档中的关键信息（如表面处理/公差要求/材料规格）必须在答案中体现
5. **范围约束**：答案不得包含文档中未提及的内容（如默认工艺/假设参数）

输出要求：
- 仔细对比每个数字、每个名称、每个关键描述
- 对于模糊匹配（如"大约"vs精确值），视为不一致
- 对于缺失的文档关键信息，标记为遗漏

你必须输出严格的 JSON 格式，不要输出任何其他内容。"""


FACT_CHECK_USER_PROMPT = """请核查以下回答与原始文档的一致性：

## 原始文档：
{document}

## LLM 回答：
{answer}

请输出 JSON 格式的核查结果：
{{
    "is_factual": true/false,  // 整体是否事实正确
    "confidence": 0.0-1.0,     // 置信度（0完全错误，1完全正确）
    "issues": [                // 发现的问题列表
        {{
            "type": "number_contradiction/name_contradiction/hallucination/missing_critical_info/out_of_scope",
            "description": "具体问题描述",
            "document_value": "文档中的值（若无则填null）",
            "answer_value": "回答中的值（若无则填null）",
            "severity": "high/medium/low"  // 严重程度
        }}
    ],
    "correction": "如果有问题，提供正确的回答内容；否则填''"
}}

confidence 规则：
- 1.0：完全一致，无任何问题
- 0.8-0.99：有轻微不一致（如措辞差异）但核心内容正确
- 0.6-0.79：有实质性错误（如关键数字不匹配）但部分正确
- < 0.6：严重错误（幻觉严重或大量遗漏）

如果 confidence < 0.7，则 is_factual 必须为 false。"""


class FactChecker:
    """回答与文档一致性验证器"""

    def __init__(self):
        self.api_key = self._load_hermes_key() or os.getenv("AI_API_KEY", "")
        self.model = os.getenv("AI_MODEL", "MiniMax-Text-01")
        self.base_url = "https://api.minimax.chat/v1"
        self.timeout = 60.0

    def _load_hermes_key(self) -> str:
        """从 hermes auth.json 读取有效 MiniMax key"""
        try:
            auth_path = os.path.expanduser("~/.hermes/auth.json")
            with open(auth_path) as f:
                d = json.load(f)
            creds = d.get("credential_pool", {}).get("minimax", [])
            if creds:
                return creds[0].get("access_token", "") or ""
        except Exception:
            pass
        return ""

    async def check(
        self,
        answer: str,
        document: str,
        system_prompt: Optional[str] = None
    ) -> dict:
        """
        核查回答与文档的一致性

        Args:
            answer: LLM 生成的回答
            document: 原始文档
            system_prompt: 可选的自定义 system prompt

        Returns:
            {{
                "is_factual": bool,      // 整体是否事实正确
                "confidence": float,     // 置信度 0-1
                "issues": List[dict],    // 发现的问题
                "correction": str        // 修正后的回答
            }}
        """
        if not self.api_key:
            return {
                "is_factual": False,
                "confidence": 0.0,
                "issues": [{"type": "config_error", "description": "未配置 AI API Key", "severity": "high"}],
                "correction": "⚠️ Fact Checker 未配置，请联系管理员。"
            }

        messages = [
            {"role": "system", "content": system_prompt or FACT_CHECK_SYSTEM_PROMPT},
            {"role": "user", "content": FACT_CHECK_USER_PROMPT.format(
                document=document,
                answer=answer
            )}
        ]

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
                        "temperature": 0.3,  # 较低温度确保稳定输出
                    },
                )
                response.raise_for_status()
                data = response.json()

                base = data.get("base_resp", {})
                if base.get("status_code") and base.get("status_code") != 0:
                    return {
                        "is_factual": False,
                        "confidence": 0.0,
                        "issues": [{"type": "api_error", "description": f"API 错误: {base.get('status_msg')}", "severity": "high"}],
                        "correction": ""
                    }

                content = data["choices"][0]["message"]["content"]
                return self._parse_response(content)

        except httpx.TimeoutException:
            return {
                "is_factual": False,
                "confidence": 0.0,
                "issues": [{"type": "timeout", "description": "Fact Checker 响应超时", "severity": "medium"}],
                "correction": ""
            }
        except Exception as e:
            return {
                "is_factual": False,
                "confidence": 0.0,
                "issues": [{"type": "error", "description": f"异常: {str(e)}", "severity": "high"}],
                "correction": ""
            }

    def _parse_response(self, content: str) -> dict:
        """解析 LLM 返回的 JSON 响应"""
        try:
            # 尝试提取 JSON（可能包含在 ```json ... ``` 中）
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])  # 去掉 ```json 和 ```
            
            result = json.loads(content)
            
            # 强制执行 confidence < 0.7 → is_factual=False
            if result.get("confidence", 1.0) < 0.7:
                result["is_factual"] = False
            
            # 确保字段完整
            return {
                "is_factual": result.get("is_factual", False),
                "confidence": result.get("confidence", 0.0),
                "issues": result.get("issues", []),
                "correction": result.get("correction", "")
            }
        except json.JSONDecodeError as e:
            return {
                "is_factual": False,
                "confidence": 0.0,
                "issues": [{"type": "parse_error", "description": f"无法解析 LLM 输出: {str(e)}", "severity": "high"}],
                "correction": content  # 返回原始内容供调试
            }


# ── 便捷函数 ──────────────────────────────────────────────────────────

async def check_factuality(answer: str, document: str) -> dict:
    """
    快速核查回答与文档的一致性

    Args:
        answer: LLM 生成的回答
        document: 原始文档

    Returns:
        核查结果 dict
    """
    checker = FactChecker()
    return await checker.check(answer, document)


# ── 测试 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    async def test_with_hallucination():
        """测试：故意生成一个有幻觉的回答，验证能检测出来"""
        
        # 原始文档（来自制造业场景）
        document = """
        产品：BAM-2024-001 铝合金支架
        材质：A5052-H32（铝合金）
        数量：500 件
        尺寸：120mm x 80mm x 15mm
        公差：±0.1mm
        表面处理：阳极氧化（黑色）
        单价：¥45.00/件
        交期：15 个工作日
        """
        
        # 错误回答（包含幻觉和数字错误）
        wrong_answer = """
        产品：BAM-2024-001 铝合金支架
        材质：A5052-H32（铝合金）✓
        数量：1000 件（错误：文档说500件）
        尺寸：120mm x 80mm x 15mm ✓
        公差：±0.2mm（错误：文档说±0.1mm）
        表面处理：喷砂处理（幻觉：文档说阳极氧化）
        单价：¥50.00/件（错误：文档说¥45.00）
        交期：15 个工作日 ✓
        """
        
        print("=" * 60)
        print("Fact Checker 测试 - 幻觉检测")
        print("=" * 60)
        print("\n📄 原始文档:")
        print(document)
        print("\n🤖 LLM 回答（包含错误）:")
        print(wrong_answer)
        print("\n" + "-" * 60)
        
        checker = FactChecker()
        result = await checker.check(wrong_answer, document)
        
        print("\n📊 核查结果:")
        print(f"  is_factual: {result['is_factual']}")
        print(f"  confidence: {result['confidence']}")
        print(f"  issues 数量: {len(result['issues'])}")
        
        for i, issue in enumerate(result['issues'], 1):
            print(f"\n  问题 {i}:")
            print(f"    type: {issue.get('type')}")
            print(f"    description: {issue.get('description')}")
            print(f"    severity: {issue.get('severity')}")
        
        if result['correction']:
            print(f"\n✏️  修正建议:")
            print(result['correction'])
        
        print("\n" + "=" * 60)
        
        # 验证检测到了幻觉
        if not result['is_factual'] and result['confidence'] < 0.7:
            print("✅ 测试通过：成功检测出幻觉和数字错误！")
        else:
            print("❌ 测试失败：未能检测出错误！")

    asyncio.run(test_with_hallucination())