"""Web 接入层：FastAPI + SSE 流式。

为什么换掉 Gradio：
设计稿要的是「单栏对话流 + 左右气泡 + 时间戳 + 底部悬浮输入栏 + 右上角折叠参数面板」，
Gradio 的 DOM 由组件自己渲染，气泡时间戳、输入栏悬浮、参数面板折叠都做不出来，
只能靠 CSS 覆盖它的内部类名硬掰——Gradio 一升级就全废。原生前端反而更可控。

并发与取消（这是本次改造的两个硬点）：
1. service.stream 是同步阻塞的（openai SDK 同步流），用后台线程跑，通过
   asyncio.Queue 把结果送回事件循环。这样同步调用不会堵住 event loop，
   多个请求可以真正并行——不像 Gradio 默认 concurrency_limit=1 时全站串行。
2. 前端点「停止」会断开连接。这里每 0.5 秒检查一次 is_disconnected，
   断开就给 worker 打停止标记，worker 退出循环时 SDK 的连接随之关闭，
   上游不再继续计费。只断前端不停上游等于白烧 token。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from poet import service
from poet.client import PoetError
from poet.config import Settings, load_settings
from poet.styles import DEFAULT_STYLE, STYLES

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
log = logging.getLogger(__name__)

# 首屏「试试这些」的快捷主题。写死而不从模型猜，成本为零且可预期。
EXAMPLES = ["秋天", "离别", "深夜的便利店"]


class GenerateIn(BaseModel):
    theme: str = Field(default="", max_length=2000)
    style: str = DEFAULT_STYLE


def _sse(event: str, data: dict[str, object]) -> str:
    """SSE 帧。data 里的中文用 ensure_ascii=False 直出，省带宽也便于调试。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    app = FastAPI(title="AI 诗人 / 歌词生成器", docs_url=None, redoc_url=None)

    @app.get("/api/meta")
    def meta() -> dict[str, object]:
        return {
            "styles": [
                {"label": s.label, "hint": s.hint, "key": s.key} for s in STYLES.values()
            ],
            "default_style": DEFAULT_STYLE,
            "mode": settings.llm_mode,
            "mode_label": settings.effective_mode_label,
            "max_theme_chars": settings.max_theme_chars,
            "examples": EXAMPLES,
        }

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": str(settings.llm_mode)}

    # response_model=None：返回可能是 JSONResponse 也可能是 StreamingResponse，
    # 不让 FastAPI 去推断响应模型（它会拿联合类型当 Pydantic 字段，直接报错）
    @app.post("/api/generate", response_model=None)
    async def generate(payload: GenerateIn, request: Request) -> StreamingResponse | JSONResponse:
        # 先同步校验：输入不合法就别开流，直接给 400，前端能按状态码分别处理。
        # 这一层和界面无关，换成任何前端都复用同一套规则。
        try:
            style, theme = service.prepare(settings, payload.style, payload.theme)
        except PoetError as exc:
            return JSONResponse(
                status_code=400,
                content={"code": exc.code, "message": exc.for_user},
            )

        return StreamingResponse(
            _event_stream(request, style, theme),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",  # 让 nginx 不要缓冲 SSE
                "Connection": "keep-alive",
            },
        )

    # 并发闸门：超过上限的请求先排队。没有它，N 个用户同时点就是用同一个 Key
    # 同时打 N 倍的上游请求，既容易被限流，也难说清是谁花的钱。
    slots = asyncio.Semaphore(settings.concurrency_limit)

    async def _event_stream(
        request: Request, style: str, theme: str
    ) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict[str, object]] | None] = asyncio.Queue()
        stop = threading.Event()

        def emit(event: str, data: dict[str, object]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (event, data))

        def worker() -> None:
            try:
                for snapshot in service.stream(settings, style, theme):
                    if stop.is_set():
                        log.info("客户端已断开，停止上游生成")
                        return
                    emit("chunk", {"text": snapshot})
                emit("done", {})
            except PoetError as exc:
                log.warning("生成失败 code=%s detail=%s", exc.code, exc.detail)
                emit("error", {"code": exc.code, "message": exc.for_user})
            except Exception:
                log.exception("未预期的生成异常")
                emit("error", {"code": "internal", "message": "服务内部错误，请稍后重试。"})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        # 先拿槽位。等待期间持续发心跳，避免浏览器/代理以为连接死了。
        acquired = False
        while not acquired:
            try:
                await asyncio.wait_for(slots.acquire(), timeout=1.0)
                acquired = True
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield ": waiting\n\n"

        threading.Thread(target=worker, daemon=True, name=f"gen-{style}").start()

        try:
            while True:
                if await request.is_disconnected():
                    stop.set()
                    return
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.5)
                except TimeoutError:
                    # 心跳：长耗时（智能体挂知识库）时避免中间代理判定超时断流
                    yield ": ping\n\n"
                    continue
                if item is None:
                    return
                yield _sse(*item)
        finally:
            # 无论正常结束还是被取消，都要让 worker 尽快退出，避免线程泄漏
            stop.set()
            if acquired:
                slots.release()

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")

    # 静态资源单独挂 /static：挂根路径会把未知 URL 也吞掉，
    # 调试时 404 全变成「首页」更难定位。
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
