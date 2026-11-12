"""入口：加载配置 → 组装 FastAPI 应用 → 启动 uvicorn。

界面已从 Gradio 换成「FastAPI + 原生前端」（web/ 目录）：
设计稿要的对话气泡、时间戳、底部悬浮输入栏、右上角折叠参数面板，
Gradio 的组件结构表达不了，只能覆盖内部类名硬掰，升级即碎。

这个文件只负责组装与启动，失败时能一眼看出卡在哪一步。
"""

from __future__ import annotations

import logging
import sys
import threading
import webbrowser

import uvicorn
from pydantic import ValidationError

from poet.api import create_app
from poet.config import load_settings

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # 这几家的 HTTP 层日志太吵，只留警告。openai 3.x 用的是 httpx2，
    # 只关 httpx 是关不掉的。
    for noisy in ("httpx", "httpx2", "openai", "urllib3", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def format_config_error(exc: ValidationError) -> str:
    """把 pydantic 的多层报错压成用户能看懂的一行行提示。"""
    lines = ["配置校验失败，服务未启动：", ""]
    for err in exc.errors():
        msg = err.get("msg", "")
        # model_validator 抛的 ValueError 会被包一层 "Value error, " 前缀
        msg = msg.removeprefix("Value error, ")
        loc = ".".join(str(x) for x in err.get("loc", ()))
        lines.append(f"  · {msg}" if not loc else f"  · [{loc}] {msg}")
    lines += [
        "",
        "解决办法：把 .env.example 复制成 .env 并填写，或设置同名环境变量。",
        "  Windows: setx DASHSCOPE_API_KEY \"sk-...\"   （设置后需重开终端）",
        "  macOS/Linux: export DASHSCOPE_API_KEY=sk-...",
    ]
    return "\n".join(lines)


def main() -> int:
    setup_logging()
    log = logging.getLogger("poet")

    try:
        settings = load_settings()
    except ValidationError as exc:
        print(format_config_error(exc), file=sys.stderr)
        return 1

    url = f"http://{settings.server_name}:{settings.server_port}"
    log.info("通道=%s 目标=%s", settings.llm_mode, settings.effective_mode_label)
    log.info(
        "超时=%ss 连接超时=%ss 重试=%s",
        settings.timeout_s,
        settings.connect_timeout_s,
        settings.max_retries,
    )
    log.info("地址=%s", url)

    app = create_app(settings)

    if settings.open_browser:
        # 等 uvicorn 起来再开，避免浏览器先到一步拿到「无法访问」
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        app,
        host=settings.server_name,
        port=settings.server_port,
        log_config=None,  # 用上面配好的 logging，别再另起一套
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
