"""
AI 模块 - 制造业 AI 对话

功能：
- MiniMax AI 对话（文字）
- 非规则问题 → AI 回复
- 制造业场景 System Prompt

依赖：AI_API_KEY（从 .env 读取）
"""

import os
import asyncio
import json
import httpx
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# 制造业 System Prompt（回答范围约束版）
MANUFACTURING_SYSTEM_PROMPT = """你是制造业报价助手，专为制造业场景问答设计。你只能回答以下范围的问题：

✅ 可以回答的范围：
- 材质咨询（SUS304、SUS303、SECC、SPCC、ADC12、A5052 等金属材质规格）
- 工艺报价（CNC、钣金、铸造、表面处理等工艺流程和成本）
- 图纸识别与报价（材质、数量、工艺的参数提取）
- 交期查询（各类工艺的标准交期）
- 制造业相关的技术问题

❌ 不能回答的范围：
- 闲聊、日常话题、生活问题
- 非制造业知识（天气、新闻、历史、娱乐等）
- 你不知道的问题不要编造，如实说不知道

回答风格：专业、简洁、直接给答案，不废话。
如果用户问的问题超出范围，用以下固定回复：
「您好，我是制造业报价助手，专注于为您提供以下服务：
- 材质咨询（SUS304、SUS303、SECC等）
- 工艺报价（CNC、钣金、铸造等）
- 图纸识别与报价
- 交期查询

请发送图纸或告诉我您需要的材质、数量和工艺，我会为您报价。」"""


class AIManufacturing:
    """制造业 AI 对话"""

    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY", "")
        self.model = os.getenv("AI_MODEL", "MiniMax-M2.7")
        self.base_url = "https://api.minimax.chat/v1"
        self.timeout = 30.0

    async def chat(self, message: str, history: list[dict] = None) -> str:
        """
        发送对话，获取 AI 回复

        Args:
            message: 用户消息
            history: 对话历史 [{"role": "user"/"assistant", "content": "..."}]

        Returns:
            AI 回复文本
        """
        if not self.api_key:
            return "⚠️ AI 未配置，请联系管理员。"

        messages = [
            {"role": "system", "content": MANUFACTURING_SYSTEM_PROMPT}
        ]

        # 加入历史
        if history:
            for h in history[-10:]:  # 最多10条历史
                messages.append(h)

        messages.append({"role": "user", "content": message})

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
                        "temperature": 0.7,
                    },
                )
                response.raise_for_status()
                data = response.json()
                base = data.get("base_resp", {})
                if base.get("status_code") and base.get("status_code") != 0:
                    return f"⚠️ AI 服务错误：{base.get('status_msg', 'Unknown error')}"
                return data["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            return "⏳ AI 响应超时，请稍后再试。"
        except httpx.HTTPStatusError as e:
            return f"⚠️ AI 服务错误：{e.response.status_code}"
        except Exception as e:
            return f"⚠️ AI 异常：{str(e)}"

    async def vision(self, image_base64: str, prompt: str = "请描述这张图片的内容") -> dict:
        """
        使用 mmx CLI 进行图片识别

        Args:
            image_base64: 图片 base64 编码（不含 data:image/...;base64, 前缀）
            prompt: 提问

        Returns:
            包含 content 字段的 dict，或包含 error 字段的 dict
        """
        import base64
        import json
        import subprocess
        import tempfile
        import os

        mmx_path = "/Users/jinyonghao/.npm-global/bin/mmx"

        # 将 base64 解码并保存为临时文件
        try:
            image_data = base64.b64decode(image_base64)
        except Exception as e:
            print(f"[ERROR] Failed to decode base64: {e}")
            return {"error": str(e)}

        # 创建临时图片文件
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_file:
            tmp_file.write(image_data)
            image_path = tmp_file.name

        try:
            # 调用 mmx vision describe
            result = subprocess.run(
                [mmx_path, "vision", "describe", "--image", image_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            print(f"[DEBUG] mmx vision returncode: {result.returncode}")
            if result.returncode != 0:
                print(f"[ERROR] mmx vision stderr: {result.stderr}")
                return {"error": result.stderr}

            # 解析 JSON 输出，提取 content 字段
            try:
                output = json.loads(result.stdout)
                content = output.get("content", "")
                print(f"[DEBUG] mmx content: {content[:200]}...")
                return {"content": content, "raw": result.stdout}
            except json.JSONDecodeError as e:
                print(f"[ERROR] Failed to parse mmx JSON: {e}")
                print(f"[DEBUG] mmx stdout: {result.stdout[:500]}")
                # 不是 JSON，返回原始文本
                return {"content": result.stdout.strip(), "raw": result.stdout}
        except subprocess.TimeoutExpired:
            print("[ERROR] mmx vision timeout")
            return {"error": "timeout"}
        except Exception as e:
            print(f"[ERROR] mmx vision failed: {e}")
            return {"error": str(e)}
        finally:
            # 清理临时文件
            try:
                os.unlink(image_path)
            except Exception:
                pass


# 全局实例
ai_manufacturing = AIManufacturing()
