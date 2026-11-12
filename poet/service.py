"""业务层：输入校验 → 调用客户端 → 结果归一。

这一层存在的意义是把「用户输入不可信」这件事挡在 LLM 之前。

原项目把 theme 直接拼进 prompt，没有任何校验。纯文本模型下最坏结果是胡说八道，
但智能体挂了插件之后，一次 prompt 注入可能触发有副作用的工具调用（发请求、
查库、调外部 API）。所以校验和注入防护在这里不是可选项。
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from poet.client import PoetError
from poet.config import Settings
from poet.styles import STYLE_LABELS, build_messages, get_style

# 明显的指令注入特征。宁可误杀（让用户换个说法），也不要放过。
_INJECTION_PATTERNS = [
    re.compile(r"忽略(以上|之前|前面|上述)"),
    re.compile(r"(忘记|忘掉)(你|之前|以上)"),
    re.compile(r"ignore\s+(all\s+)?(previous|above|prior)", re.I),
    re.compile(r"(system|系统)\s*(prompt|提示词|指令)", re.I),
    re.compile(r"你现在(是|扮演)"),
    re.compile(r"(输出|打印|泄露|告诉我)你(的)?\s*(设定|配置|密钥|api\s*key)", re.I),
    re.compile(r"</?\s*(system|instructions?)\s*>", re.I),
]

# 需要清理的不可见字符：零宽空格、零宽连接符、BOM、方向控制符
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")


class InputError(PoetError):
    """用户输入不合法。单独一类，好在 UI 上与上游错误区分对待。"""

    code = "invalid_input"
    user_message = "输入不合法。"


def _clean(theme: str) -> str:
    text = _INVISIBLE.sub("", theme or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def validate_theme(theme: str, settings: Settings) -> str:
    """校验并返回清洗后的主题。不合法则抛 InputError。"""
    text = _clean(theme)

    if not text:
        raise InputError("主题不能为空，例如：秋天、离别、故乡")

    if len(text) > settings.max_theme_chars:
        raise InputError(
            f"主题过长（{len(text)} 字），请控制在 {settings.max_theme_chars} 字以内。"
            f"太长会让模型抓不住重点，也更容易被当成指令。"
        )

    if "\n" in text:
        raise InputError("主题请写在一行内，不要换行。")

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            raise InputError(
                "主题里含有疑似指令的内容，已拒绝。请只填写一个创作主题词或短语。"
            )

    return text


def validate_style(style_label: str) -> str:
    if style_label not in STYLE_LABELS:
        raise InputError(f"未知风格：{style_label}。可选：{'、'.join(STYLE_LABELS)}")
    return style_label


def normalize_output(text: str) -> str:
    """统一换行、去掉行尾空格、折叠连续空行。模型常吐出尾随空格和多余空行。"""
    lines = [line.rstrip() for line in (text or "").split("\n")]
    out: list[str] = []
    blank = 0
    for line in lines:
        if line:
            blank = 0
            out.append(line)
        else:
            blank += 1
            if blank <= 1:  # 最多保留一个连续空行
                out.append("")
    # 只去掉首尾的**空行**，不用 strip()：那会把第一行的行首缩进也吃掉，
    # 而诗歌排版可能靠缩进。
    while out and not out[0]:
        out.pop(0)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def prepare(settings: Settings, style_label: str, theme: str) -> tuple[str, str]:
    """校验并返回 (style_label, theme)。UI 与 CLI 共用同一套入口。"""
    return validate_style(style_label), validate_theme(theme, settings)


def generate(settings: Settings, style_label: str, theme: str) -> str:
    """一次性返回完整结果。"""
    from poet.client import get_client

    style_label, theme = prepare(settings, style_label, theme)
    raw = get_client(settings).generate(style_label, theme)
    return normalize_output(raw)


def stream(settings: Settings, style_label: str, theme: str) -> Iterator[str]:
    """流式产出**累积**文本（Gradio 要的是完整快照，不是增量）。"""
    style_label, theme = prepare(settings, style_label, theme)
    buffer = ""
    for delta in get_client(settings).stream(style_label, theme):
        buffer += delta
        yield buffer
    if not buffer.strip():
        raise InputError("上游没有返回任何内容，请重试。")


def describe_styles() -> list[dict[str, str]]:
    """给 UI 用的风格说明。"""
    return [
        {
            "label": label,
            "system": get_style(label).system,
            "preview": build_messages(label, "示例主题")[1]["content"].split("\n")[0],
        }
        for label in STYLE_LABELS
    ]
