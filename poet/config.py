"""配置层：所有外部可变项集中在这里，启动即校验。

用 pydantic-settings 而不是裸 os.getenv 的三个理由：
1. 启动时校验：缺 Key / 类型错 / 超范围，进程直接起不来，不会跑到用户点了按钮才报错。
2. 单一事实来源：端口、超时、并发、模型名都从这里取，代码里不再出现魔法数字。
3. 支持 .env 文件 + 真实环境变量覆盖，本地开发和部署走同一套代码。

双通道设计（LLM_MODE）：
    model —— 直接调模型（qwen-plus 等），走 OpenAI 兼容 chat/completions
    agent —— 调百炼智能体应用，走 OpenAI 兼容 Responses API（需 APP_ID）
保留 model 通道是为了在 APP_ID 缺失时仍能降级运行，也方便两条链路对比。
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_API_HOST = "https://dashscope.aliyuncs.com"


class LLMMode(StrEnum):
    """调用的目标类型。"""

    MODEL = "model"
    AGENT = "agent"


class Settings(BaseSettings):
    """应用配置。字段名小写，自动对应大写的环境变量名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    dashscope_api_key: str = ""
    app_id: str = ""
    llm_mode: LLMMode = LLMMode.MODEL

    api_host: str = DEFAULT_API_HOST
    model_name: str = "qwen-plus"
    temperature: float = Field(default=0.9, ge=0.0, le=2.0)

    timeout_s: float = Field(default=60.0, gt=0)
    connect_timeout_s: float = Field(default=5.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)

    concurrency_limit: int = Field(default=8, ge=1, le=64)
    max_theme_chars: int = Field(default=50, ge=1, le=200)

    server_name: str = "127.0.0.1"
    server_port: int = Field(default=7860, ge=1024, le=65535)

    @property
    def is_agent(self) -> bool:
        return self.llm_mode is LLMMode.AGENT

    @property
    def base_url(self) -> str:
        """OpenAI SDK 的 base_url，按通道切换到不同路径。"""
        host = self.api_host.rstrip("/")
        if self.is_agent:
            return f"{host}/api/v2/apps/agent/{self.app_id}/compatible-mode/v1/"
        return f"{host}/compatible-mode/v1"

    @property
    def effective_mode_label(self) -> str:
        return f"智能体应用 ({self.app_id[:6]}...)" if self.is_agent else f"模型 ({self.model_name})"

    @model_validator(mode="after")
    def _validate_combination(self) -> Settings:
        if not self.dashscope_api_key.strip():
            raise ValueError(
                "缺少 DASHSCOPE_API_KEY。请在 .env 文件或环境变量中配置后再启动。"
            )
        if self.is_agent and not self.app_id.strip():
            raise ValueError(
                "LLM_MODE=agent 时必须提供 APP_ID（百炼控制台 → 应用管理 → 应用卡片上复制）。"
                "若暂时没有，把 LLM_MODE 设为 model 仍可运行。"
            )
        if self.connect_timeout_s >= self.timeout_s:
            raise ValueError(
                f"connect_timeout_s({self.connect_timeout_s}) 必须小于 timeout_s({self.timeout_s})。"
            )
        return self


def load_settings() -> Settings:
    """读取配置。校验失败会抛 ValueError，由入口捕获并给出可读提示。"""
    return Settings()
