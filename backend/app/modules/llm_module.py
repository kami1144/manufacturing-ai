"""
LLM 模块 - 独立可复用

功能：
- 统一 LLM 调用接口
- 支持本地模型（DeepSeek-R1/Qwen）和云端 API
- 流式响应支持
- Prompt 模板管理

依赖：httpx（已有）
"""

from typing import Optional, Generator, AsyncGenerator
import json
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict
    finish_reason: str = "stop"


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:8001/v1"  # 本地模型默认地址
    api_key: str = "dummy"
    model: str = "deepseek-r1"
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: int = 120


class LLMClient:
    """统一 LLM 客户端"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """
        同步生成

        Args:
            prompt: 用户 prompt
            system: 系统 prompt
            **kwargs: 覆盖默认参数
        """
        import httpx

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # 合并参数
        req_config = {
            "model": kwargs.pop("model", self.config.model),
            "temperature": kwargs.pop("temperature", self.config.temperature),
            "max_tokens": kwargs.pop("max_tokens", self.config.max_tokens),
        }
        req_config.update(kwargs)

        try:
            with httpx.Client(timeout=self.config.timeout) as client:
                response = client.post(
                    f"{self.config.base_url}/chat/completions",
                    json={"messages": messages, **req_config},
                    headers={"Authorization": f"Bearer {self.config.api_key}"}
                )
                response.raise_for_status()
                data = response.json()

                return LLMResponse(
                    content=data["choices"][0]["message"]["content"],
                    model=data.get("model", req_config["model"]),
                    usage=data.get("usage", {}),
                    finish_reason=data["choices"][0].get("finish_reason", "stop")
                )
        except Exception as e:
            return LLMResponse(
                content=f"[Error: {str(e)}]",
                model=req_config["model"],
                usage={}
            )

    def generate_stream(
        self,
        prompt: str,
        system: Optional[str] = None
    ) -> Generator[str, None, None]:
        """流式生成"""
        import httpx

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        req_config = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True
        }

        try:
            with httpx.Client(timeout=self.config.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.config.base_url}/chat/completions",
                    json={"messages": messages, **req_config},
                    headers={"Authorization": f"Bearer {self.config.api_key}"}
                ) as response:
                    for line in response.iter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            chunk = json.loads(data)
                            content = chunk["choices"][0]["delta"].get("content", "")
                            if content:
                                yield content
        except Exception as e:
            yield f"[Error: {str(e)}]"


# ── Prompt 模板 ─────────────────────────────────────────

BLUEPRINT_SYSTEM_PROMPT = """你是一个制造业图纸分析师。

根据用户提供的图纸信息，请提取：
1. 材质（Material）
2. 表面处理（Surface Treatment）
3. 尺寸规格（Dimensions）
4. 公差要求（Tolerance）
5. 工艺要求（Process Requirements）
6. BOM清单

请用结构化格式输出。如果信息不足，请明确说明。"""


def analyze_blueprint_llm(blueprint_text: str, llm_client: LLMClient = None) -> str:
    """用 LLM 分析图纸"""
    if llm_client is None:
        llm_client = LLMClient()
    response = llm_client.generate(
        prompt=f"请分析以下图纸信息：\n{blueprint_text}",
        system=BLUEPRINT_SYSTEM_PROMPT
    )
    return response.content


def generate_quote_description(
    material: str,
    process_type: str,
    quantity: int,
    llm_client: LLMClient = None
) -> str:
    """用 LLM 生成报价说明"""
    if llm_client is None:
        llm_client = LLMClient()
    prompt = f"""根据以下信息生成报价说明：

- 材质：{material}
- 工艺：{process_type}
- 数量：{quantity}件

请生成一段专业的报价说明，包含价格影响因素和交期说明。"""

    response = llm_client.generate(prompt=prompt)
    return response.content


# ── CLI 入口 ────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("LLM Module - Manufacturing AI")
    print("=" * 50)

    # 测试连接
    client = LLMClient()
    print(f"\nConfig: {client.config.model} @ {client.config.base_url}")

    # 简单测试
    print("\nTesting connection...")
    response = client.generate(
        prompt="Say 'Hello' in Japanese.",
        system="You are a helpful assistant."
    )
    print(f"Response: {response.content}")
    print(f"Model: {response.model}")
