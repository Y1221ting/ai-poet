import os
import random
import gradio as gr
from openai import OpenAI

# ================= 配置区 =================
# 建议用环境变量存 Key（更安全），也可在网页输入框里临时粘贴
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"  # 默认业务空间标准地址
MODEL = "qwen-plus"   # 有免费额度；想要更好效果可改成 qwen-max
# ==========================================
print(">>> 服务启动，当前 BASE_URL =", BASE_URL)


def generate_poem(theme, style, api_key):
    """后端核心：调用千问 API 生成诗词"""
    key = (api_key or "").strip() or DASHSCOPE_API_KEY
    if not key:
        return "⚠️ 未检测到 API Key：请在左侧输入框粘贴你的 Key"

    if style in ("五言绝句", "七言绝句", "五言律诗", "七言律诗"):
        sys_prompt = "你是一位才华横溢的中国古典诗人，擅长五言、七言等传统诗词创作。"
        prompt = (
            f"请以「{theme}」为主题，写一首{style}。"
            "要求：意境优美、对仗工整、符合格律、押韵，直接输出诗词本身，不要任何解释。"
        )
    elif style == "歌词":
        sys_prompt = "你是一位优秀的华语流行作词人，擅长创作动人的歌词。"
        prompt = (
            f"请以「{theme}」为主题，创作一首中文歌词。"
            "要求："
            "1) 开头先写出【歌名】和【歌手】，歌手请虚构一个华语歌手或乐队名（不要用真实艺人姓名），然后空一行；"
            "2) 正文使用现代白话，情感真挚，句子长短自由、朗朗上口；"
            "3) 分段并用【主歌】【副歌】等小标题标注结构；"
            "4) 不要使用文言文、不要刻意对仗；直接输出歌词本身，不要任何解释。"
        )
    else:  # 现代诗
        sys_prompt = "你是一位才华横溢的现代诗人。"
        prompt = (
            f"请以「{theme}」为主题，写一首现代诗。"
            "要求：意象新颖、语言自然、分行自由，不要古典格律与对仗，直接输出诗歌本身，不要任何解释。"
        )

    try:
        client = OpenAI(api_key=key, base_url=BASE_URL)
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.9,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"❌ 调用失败，请检查 API Key 是否有效。\n详情：{e}"


# ================= 落叶飘落动效 =================
# 用纯 CSS 生成一层固定在上层的落叶，pointer-events:none 不会挡住点击
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


def build_leaves_html():
    """随机生成一批飘落的秋叶"""
    rng = random.Random(2024)
    colors = ["#e06c2b", "#f0913a", "#c94f1e", "#d98c3f", "#b8552a", "#e8a33d"]
    parts = []
    for _ in range(12):
        left = rng.uniform(0, 100)
        size = rng.uniform(10, 22)
        dur = rng.uniform(8, 16)
        sway = rng.uniform(2.5, 5)
        delay = rng.uniform(0, 16)
        color = rng.choice(colors)
        op = rng.uniform(0.6, 0.95)
        parts.append(
            f'<span class="leaf" style="left:{left:.1f}%;'
            f'width:{size:.0f}px;height:{size:.0f}px;background:{color};opacity:{op:.2f};'
            f'animation:leafFall {dur:.1f}s linear infinite, leafSway {sway:.1f}s ease-in-out infinite alternate;'
            f'animation-delay:-{delay:.1f}s,0s;"></span>'
        )
    return LEAF_STYLE + '<div class="leaf-layer">' + "".join(parts) + "</div>"


# ================= 整体美化样式 =================
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


# ================= 前端界面 =================
with gr.Blocks(title="AI 诗人 / 歌词生成器", css=APP_CSS) as demo:
    gr.HTML(build_leaves_html())  # 飘落落叶层

    with gr.Column(elem_id="app-card"):
        gr.HTML(
            '<div class="app-title">🍂 AI 诗人 / 歌词生成器</div>'
            '<div class="app-subtitle">输入一个主题与风格，让大模型为你创作一首诗或一段歌词。</div>'
        )

        with gr.Row():
            with gr.Column(scale=1):
                theme = gr.Textbox(label="主题", value="秋天", placeholder="例如：秋天、离别、故乡")
                style = gr.Dropdown(
                    choices=["五言绝句", "七言绝句", "五言律诗", "七言律诗", "现代诗", "歌词"],
                    value="五言绝句",
                    label="风格",
                )
                api_key = gr.Textbox(
                    label="API Key（可选）",
                    placeholder="sk-...，留空则使用环境变量",
                    type="password",
                )
                btn = gr.Button("✨ 生成", elem_id="gen-btn", variant="primary")
            with gr.Column(scale=1):
                output = gr.Textbox(label="生成结果", lines=12, elem_id="result-box")

        btn.click(generate_poem, inputs=[theme, style, api_key], outputs=output)

        gr.Examples(
            examples=[["秋天", "七言律诗", ""], ["离别", "现代诗", ""], ["考试加油", "歌词", ""]],
            inputs=[theme, style, api_key],
        )

demo.launch(theme=gr.themes.Soft(), inbrowser=True)
