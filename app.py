"""入口：加载配置 → 构建界面 → 启动服务。

原来的 app.py 把配置、prompt 拼接、LLM 调用、CSS、界面全部塞在一个文件里。
现在拆成 poet/ 下的五个模块，这个文件只负责组装与启动，方便一眼看出进程
是怎么起来的、失败时卡在哪一步。
"""

from __future__ import annotations

import logging
import os
import sys

# 必须写在 import gradio 之前：关掉 Gradio 的启动遥测，否则每次启动都会
# 向 huggingface / api.gradio.app 打几个请求，日志里一片噪音。
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from poet.config import load_settings  # noqa: E402
from poet.ui import APP_CSS, build_ui  # noqa: E402

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # 这几家的 HTTP 层日志太吵，只留警告。注意 openai 3.x 用的是 httpx2，
    # 只关 httpx 是关不掉的。
    for noisy in ("httpx", "httpx2", "openai", "gradio", "urllib3"):
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

    log.info("通道=%s 模型/应用=%s", settings.llm_mode, settings.effective_mode_label)
    log.info("超时=%ss 重试=%s 并发=%s", settings.timeout_s, settings.max_retries, settings.concurrency_limit)

    demo = build_ui(settings)
    # 默认每个事件并发 1，全站串行；这里按配置放开
    demo.queue(default_concurrency_limit=settings.concurrency_limit)
    # css / theme 在 Gradio 6 必须从 Blocks() 移到 launch()
    demo.launch(
        css=APP_CSS,
        theme=gr.themes.Soft(),
        server_name=settings.server_name,
        server_port=settings.server_port,
        inbrowser=True,
        show_error=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
