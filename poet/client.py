"""LLM 客户端：双通道、显式超时、错误分类、流式输出。

三个关键设计：

1. **传输层重试交给 SDK，不叠 tenacity。** openai SDK 内置的重试会识别 429/5xx/
   连接错误并遵循 Retry-After，比手写更贴协议。如果外面再套一层 tenacity，
   2×2 变成最多 4 次请求，延迟翻倍且账单翻倍。tenacity 只用在一个地方：
   **上游回了 200 但正文为空**——这不是传输问题，SDK 不会重试。

2. **显式覆盖 SDK 默认的 600 秒超时。** SDK 默认 Timeout(600, connect=5)，
   配合 Gradio 默认并发 1，一个卡住的请求能锁死整个应用半小时。

3. **错误翻译成业务类型。** 原实现把所有失败都 return 成一个 "❌ ..." 字符串，
   HTTP 一律 200，调用方无法区分 401/429/超时。这里翻译成 PoetError 子类，
   每类带独立的用户提示与错误码，便于 UI 展示和后续告警分级。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from functools import lru_cache

import httpx
import openai
from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from poet.config import Settings
from poet.styles import build_messages

log = logging.getLogger(__name__)


class PoetError(Exception):
    """业务异常基类。code 供程序判断，user_message 直接给用户看。"""

    code: str = "unknown"
    user_message: str = "生成失败，请稍后重试。"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.user_message}（{detail}）" if detail else self.user_message)


class AuthError(PoetError):
    code = "auth"
    user_message = "API Key 无效或已过期，请检查 DASHSCOPE_API_KEY。"


class AppIdError(PoetError):
    code = "app_id"
    user_message = "APP_ID 无效、应用未发布或无访问权限，请检查百炼控制台。"


class RateLimitError(PoetError):
    code = "rate_limit"
    user_message = "触发上游限流，请稍后再试。"


class UpstreamTimeout(PoetError):
    code = "timeout"
    user_message = "上游响应超时，请重试或换一个更简单的主题。"


class UpstreamUnavailable(PoetError):
    code = "upstream"
    user_message = "上游服务暂时不可用，请稍后重试。"


class EmptyResponseError(PoetError):
    code = "empty"
    user_message = "上游返回了空内容，已自动重试仍失败。"


def _translate(exc: openai.OpenAIError) -> PoetError:
    """把 SDK 异常翻译成业务异常。顺序重要：子类必须在父类之前判断。"""
    if isinstance(exc, openai.AuthenticationError):
        return AuthError(str(exc))
    if isinstance(exc, openai.RateLimitError):
        return RateLimitError(str(exc))
    if isinstance(exc, openai.APITimeoutError):
        return UpstreamTimeout(str(exc))
    if isinstance(exc, openai.APIConnectionError):
        return UpstreamUnavailable(f"网络不可达: {exc}")
    if isinstance(exc, openai.NotFoundError):
        # 智能体通道 404 基本都是 APP_ID 写错或应用没发布
        return AppIdError(str(exc))
    if isinstance(exc, openai.BadRequestError):
        return AppIdError(str(exc))
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code >= 500:
            return UpstreamUnavailable(f"HTTP {exc.status_code}")
        return PoetError(f"HTTP {exc.status_code}: {exc}")
    return PoetError(str(exc))


def _strip_code_fence(text: str) -> str:
    """模型仍可能无视约束用 ``` 包裹，这里兜底剥掉。"""
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


class PoetClient:
    """封装两条调用通道。构造一次，全局复用（连接池随之复用）。"""

    def __init__(self, settings: Settings, http_client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.timeout_s, connect=settings.connect_timeout_s),
            max_retries=settings.max_retries,
            http_client=http_client,  # 测试时注入 MockTransport，生产为 None
        )
        log.info(
            "客户端就绪 mode=%s base_url=%s timeout=%ss retries=%s",
            settings.llm_mode,
            settings.base_url,
            settings.timeout_s,
            settings.max_retries,
        )

    @property
    def is_agent(self) -> bool:
        return self.settings.is_agent

    # ---------- 非流式 ----------

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0.6),
        retry=retry_if_exception_type(EmptyResponseError),
        reraise=True,
    )
    def _call_raw(self, messages: list[dict[str, str]]) -> str:
        text = self._call_agent(messages) if self.is_agent else self._call_model(messages)
        text = _strip_code_fence(text or "")
        if not text.strip():
            raise EmptyResponseError("正文为空")
        return text

    def _call_model(self, messages: list[dict[str, str]]) -> str:
        resp = self._client.chat.completions.create(
            model=self.settings.model_name,
            messages=messages,  # type: ignore[arg-type]
            temperature=self.settings.temperature,
        )
        if not resp.choices:
            raise EmptyResponseError("choices 为空")
        return resp.choices[0].message.content or ""

    def _call_agent(self, messages: list[dict[str, str]]) -> str:
        # 智能体通道不传 model：模型、prompt、知识库、插件都由云端应用决定
        resp = self._client.responses.create(input=messages)  # type: ignore[arg-type]
        return _extract_agent_text(resp)

    def generate(self, style_label: str, theme: str) -> str:
        """生成一段内容。失败抛 PoetError 子类。"""
        messages = build_messages(style_label, theme)
        try:
            return self._call_raw(messages)
        except PoetError:
            raise
        except openai.OpenAIError as exc:
            log.warning("上游调用失败：%s", exc)
            raise _translate(exc) from exc

    # ---------- 流式 ----------

    def stream(self, style_label: str, theme: str) -> Iterator[str]:
        """逐块产出文本增量。异常发生在迭代过程中，调用方需 try/except。"""
        messages = build_messages(style_label, theme)
        try:
            if self.is_agent:
                yield from self._stream_agent(messages)
            else:
                yield from self._stream_model(messages)
        except PoetError:
            raise
        except openai.OpenAIError as exc:
            log.warning("上游流式调用失败：%s", exc)
            raise _translate(exc) from exc

    def _stream_model(self, messages: list[dict[str, str]]) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=self.settings.model_name,
            messages=messages,  # type: ignore[arg-type]
            temperature=self.settings.temperature,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def _stream_agent(self, messages: list[dict[str, str]]) -> Iterator[str]:
        stream = self._client.responses.create(input=messages, stream=True)  # type: ignore[arg-type]
        for event in stream:
            delta = getattr(event, "delta", None)
            if isinstance(delta, str) and delta:
                yield delta


def _extract_agent_text(resp: object) -> str:
    """从 Responses API 的返回对象里取正文。

    结构：resp.output[i].content[j].text，其中 content 元素 type 为 output_text。
    做防御性遍历，避免某个元素缺字段就整体崩掉。
    """
    parts: list[str] = []
    for item in getattr(resp, "output", None) or []:
        for block in getattr(item, "content", None) or []:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
    return "".join(parts).strip()


@lru_cache(maxsize=1)
def get_client(settings: Settings | None = None) -> PoetClient:
    """模块级单例。settings 相同则复用同一个客户端与连接池。"""
    if settings is None:
        from poet.config import load_settings

        settings = load_settings()
    return PoetClient(settings)
