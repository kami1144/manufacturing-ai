"""
LINE 配置管理

功能：
- LINE Bot 配置（Channel Access Token, Channel Secret）
- 管理多个工厂/客户的 LINE Bot 配置
- Webhook URL 配置
"""

import os
from typing import Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class LINEConfig:
    """LINE 配置"""

    # LINE Bot 配置
    LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET", "")
    LINE_USER_ID: str = os.getenv("LINE_USER_ID", "")  # 管理员用户ID

    # Webhook 配置
    WEBHOOK_BASE_URL: str = os.getenv("WEBHOOK_BASE_URL", "")

    # 环境
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    def __init__(self) -> None:
        """初始化配置"""
        self._validate()

    def _validate(self) -> None:
        """验证配置"""
        errors = []

        if not self.LINE_CHANNEL_ACCESS_TOKEN:
            errors.append("LINE_CHANNEL_ACCESS_TOKEN is not set")
        if not self.LINE_CHANNEL_SECRET:
            errors.append("LINE_CHANNEL_SECRET is not set")

        if errors:
            if self.ENVIRONMENT == "production":
                raise ValueError("; ".join(errors))
            else:
                print(f"[WARN] {'; '.join(errors)}")

    @property
    def is_configured(self) -> bool:
        """检查是否配置完成"""
        return bool(self.LINE_CHANNEL_ACCESS_TOKEN and self.LINE_CHANNEL_SECRET)

    @property
    def is_development(self) -> bool:
        """检查是否是开发环境"""
        return self.ENVIRONMENT == "development"

    @property
    def webhook_url(self) -> str:
        """获取 Webhook URL"""
        if self.WEBHOOK_BASE_URL:
            return f"{self.WEBHOOK_BASE_URL}/line/webhook"
        return ""

    def get_safe_config(self) -> dict:
        """获取安全配置（不含敏感信息）"""
        return {
            "line_configured": self.is_configured,
            "environment": self.ENVIRONMENT,
            "webhook_base_url": self.WEBHOOK_BASE_URL or "not configured",
        }


class MultiFactoryConfig:
    """多工厂配置（支持多个工厂/客户的 LINE Bot）"""

    def __init__(self):
        self._factories: dict[str, dict] = {}
        self._load_factory_configs()

    def _load_factory_configs(self):
        """加载工厂配置"""
        # 从环境变量加载多工厂配置
        # 格式: FACTORY_1_TOKEN, FACTORY_1_SECRET, FACTORY_1_NAME
        for i in range(1, 10):
            token = os.getenv(f"FACTORY_{i}_TOKEN", "")
            secret = os.getenv(f"FACTORY_{i}_SECRET", "")
            name = os.getenv(f"FACTORY_{i}_NAME", "")

            if token and secret:
                self._factories[f"factory_{i}"] = {
                    "token": token,
                    "secret": secret,
                    "name": name or f"Factory {i}",
                }

    def get_factory(self, factory_id: str) -> Optional[dict]:
        """获取工厂配置"""
        return self._factories.get(factory_id)

    def list_factories(self) -> list[dict]:
        """列出所有工厂"""
        return [
            {"id": k, "name": v["name"]}
            for k, v in self._factories.items()
        ]

    def add_factory(
        self,
        factory_id: str,
        token: str,
        secret: str,
        name: str,
    ):
        """添加工厂配置"""
        self._factories[factory_id] = {
            "token": token,
            "secret": secret,
            "name": name,
        }

    def remove_factory(self, factory_id: str) -> bool:
        """移除工厂配置"""
        if factory_id in self._factories:
            del self._factories[factory_id]
            return True
        return False


# 全局配置实例
line_config = LINEConfig()
multi_factory_config = MultiFactoryConfig()