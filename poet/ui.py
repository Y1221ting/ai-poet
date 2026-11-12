"""界面层：Gradio Blocks + 流式输出 + 错误契约。

与原实现的三处差异：
1. **流式**：生成过程中逐块刷新，而不是等十几秒看到一片空白。智能体挂插件时
   单次耗时可能远超纯模型，不流式的体验不可接受。
2. **错误走 gr.Error**：不再把 "❌ ..." 拼成字符串塞进输出框。业务异常和正常
   结果彻底分开，前端能区分展示。
3. **删掉 API Key 输入框**：Key 只从环境变量 / .env 读。让用户在页面里粘贴
   凭证是反模式——请求体里是明文，且多用户场景等于让人把 Key 交给你的服务器。
"""

from __future__ import annotations

import random
from collections.abc import Iterator

import gradio as gr

from poet import service
from poet.client import PoetError
from poet.config import Settings
from poet.styles import DEFAULT_STYLE, STYLE_LABELS

LEAF_COLORS = ["#e06c2b", "#f0913a", "#c94f1e", "#d98c3f", "#b8552a", "#e8a33d"]

LEAF_STYLE = """
<style>
@keyframes leafFall {
  0%   { transform: translateY(-12vh) rotate(0deg); }
  100% { transform: translateY(112vh) rotate(680deg); }
}
@keyframes leafSway {
  0%   { margin-left: -30px; }
  100% { margin-left: 30px; }
}
.leaf-layer{
  position: fixed; inset: 0; width: 100vw; height: 100vh;
  pointer-events: none; overflow: hidden; z-index: 6;
}
.leaf{
  position: absolute; top: -10vh; display: block;
  border-radius: 0 100% 0 100%;
  filter: drop-shadow(0 1px 2px rgba(120,70,20,0.12));
}
</style>
"""

APP_CSS = """
body {
  background: linear-gradient(135deg, #fff7e6 0%, #ffe9c7 45%, #f7d9a8 100%) !important;
  background-attachment: fixed !important;
}
.gradio-container { background: transparent !important; }

#app-card {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-radius: 22px;
  padding: 28px 30px;
  margin: 28px auto;
  box-shadow: 0 14px 44px rgba(160, 100, 40, 0.22);
  border: 1px solid rgba(255, 255, 255, 0.7);
}
.app-title {
  font-size: 34px; font-weight: 800; color: #5a3410;
  margin: 0 0 6px; letter-spacing: 2px;
}
.app-subtitle { color: #8a5a2b; margin: 0 0 18px; font-size: 15px; }
.app-badge {
  display: inline-block; padding: 3px 10px; border-radius: 999px;
  background: rgba(217, 96, 31, 0.12); color: #b0511c;
  font-size: 12px; font-weight: 600; margin-left: 8px; vertical-align: middle;
}

#gen-btn {
  background: linear-gradient(135deg, #f0913a, #d9601f) !important;
  border: none !important; color: #fff !important;
  font-weight: 700 !important; border-radius: 12px !important;
  box-shadow: 0 6px 18px rgba(217, 96, 31, 0.35) !important;
}
#gen-btn:hover { filter: brightness(1.06); }

#result-box textarea {
  background: rgba(255, 252, 245, 0.95) !important;
  font-size: 16px !important; line-height: 1.9 !important;
  color: #4a2f14 !important; border-radius: 12px !important;
}
"""


def build_leaves_html(count: int = 12) -> str:
    """生成飘落的秋叶。

    原实现用 random.Random(2024) 固定种子、且只在模块加载时生成一次，
    结果所有用户、所有刷新看到的落叶位置完全一致——等于一张静态底图。
    这里去掉固定种子，每次页面构建重新抽签。
    """
    rng = random.Random()
    parts = []
    for _ in range(count):
        left = rng.uniform(0, 100)
        size = rng.uniform(10, 22)
        dur = rng.uniform(8, 16)
        sway = rng.uniform(2.5, 5)
        delay = rng.uniform(0, 16)
        color = rng.choice(LEAF_COLORS)
        op = rng.uniform(0.6, 0.95)
        parts.append(
            f'<span class="leaf" style="left:{left:.1f}%;'
            f"width:{size:.0f}px;height:{size:.0f}px;background:{color};opacity:{op:.2f};"
            f"animation:leafFall {dur:.1f}s linear infinite, leafSway {sway:.1f}s ease-in-out infinite alternate;"
            f'animation-delay:-{delay:.1f}s,0s;"></span>'
        )
    return LEAF_STYLE + '<div class="leaf-layer">' + "".join(parts) + "</div>"


def _generate_stream(settings: Settings, theme: str, style: str) -> Iterator[str]:
    """把业务异常翻译成 gr.Error，让 Gradio 用红色提示条展示而不是塞进文本框。"""
    try:
        yield from service.stream(settings, style, theme)
    except PoetError as exc:
        # 校验类错误与上游类错误分开提示，便于用户判断该改输入还是该等一等
        raise gr.Error(exc.for_user) from exc


def build_ui(settings: Settings) -> gr.Blocks:
    badge = "智能体" if settings.is_agent else "模型"
    limit_hint = (
        f"当前通道：<span class='app-badge'>{badge}</span>"
        f"<span class='app-badge'>并发 {settings.concurrency_limit}</span>"
        f"<span class='app-badge'>超时 {int(settings.timeout_s)}s</span>"
    )

    with gr.Blocks(title="AI 诗人 / 歌词生成器") as demo:
        gr.HTML(build_leaves_html())

        with gr.Column(elem_id="app-card"):
            gr.HTML(
                '<div class="app-title">🍂 AI 诗人 / 歌词生成器</div>'
                '<div class="app-subtitle">输入一个主题与风格，让大模型为你创作一首诗或一段歌词。</div>'
                f"<div>{limit_hint}</div>"
            )

            with gr.Row():
                with gr.Column(scale=1):
                    theme = gr.Textbox(
                        label="主题",
                        value="秋天",
                        placeholder="例如：秋天、离别、故乡",
                        max_lines=1,
                    )
                    style = gr.Dropdown(
                        choices=STYLE_LABELS,
                        value=DEFAULT_STYLE,
                        label="风格",
                    )
                    btn = gr.Button("✨ 生成", elem_id="gen-btn", variant="primary")
                with gr.Column(scale=1):
                    output = gr.Textbox(label="生成结果", lines=12, elem_id="result-box")

            def _on_click(theme_text: str, style_label: str):
                # 用生成器函数而不是 lambda：Gradio 只有在 fn 本身是 generator
                # function 时才按流式处理，lambda 返回生成器对象会被当成一次性结果。
                yield from _generate_stream(settings, theme_text, style_label)

            btn.click(
                fn=_on_click,
                inputs=[theme, style],
                outputs=output,
                concurrency_limit=settings.concurrency_limit,
            )

            gr.Examples(
                examples=[["秋天", "七言律诗"], ["离别", "现代诗"], ["考试加油", "歌词"]],
                inputs=[theme, style],
            )

    return demo
