"""AI 诗人 / 歌词生成器 —— 应用包。

模块划分：
    config   配置与启动校验
    styles   创作风格策略表（prompt 的唯一来源）
    client   LLM 客户端（双通道 + 超时 / 重试 / 错误映射）
    service  业务编排（输入校验 → 调用 → 结果归一）
    ui       Gradio 界面与事件绑定
"""

__version__ = "1.0.0"
