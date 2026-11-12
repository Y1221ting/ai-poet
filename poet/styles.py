"""风格策略表：prompt 的唯一来源。

原项目把 6 种风格写成 if/elif 拼字符串，加一种风格要动三处。
这里改成数据驱动：风格即数据，新增风格只需在 STYLES 里加一条。

对原 prompt 的两处实质改进：
1. 古典诗词补上**可验证的硬约束**（句数 × 每句字数）。原 prompt 只说"符合格律"，
   模型无法自查平仄，但句数和字数能显著提升合规率——这是可测量的差别。
2. 统一加"不要 markdown 代码块、不要解释"的收尾约束。原 prompt 只在部分风格里提，
   实际测试中模型经常把诗包在 ``` 里返回。
"""

from __future__ import annotations

from dataclasses import dataclass

# 古典诗体的硬约束：句数 / 每句字数 / 总字数
_REGULATED = {
    "五言绝句": (4, 5),
    "七言绝句": (4, 7),
    "五言律诗": (8, 5),
    "七言律诗": (8, 7),
}


@dataclass(frozen=True, slots=True)
class Style:
    """一种创作风格。"""

    key: str
    label: str
    system: str
    instruction: str
    expected_chars: int | None = None

    def render(self, theme: str) -> str:
        return self.instruction.format(theme=theme)


def _classical(label: str) -> Style:
    lines, per_line = _REGULATED[label]
    rules = [
        f"共 {lines} 句，每句 {per_line} 字，总字数 {lines * per_line} 字，不多不少",
        "押平声韵，一韵到底，韵脚不重复用字",
    ]
    if lines == 8:
        rules.append("中间两联（颔联、颈联）必须对仗，首尾两联可不对仗")
    rules.append("意境完整，避免堆砌辞藻")
    numbered = "\n".join(f"{i}) {r}；" for i, r in enumerate(rules, 1))
    return Style(
        key=f"classical_{lines}_{per_line}",
        label=label,
        system="你是一位精通中国古典诗词格律的诗人，熟谙平仄、对仗与押韵。",
        instruction=(
            f"请以「{{theme}}」为主题，写一首{label}。\n"
            f"硬性要求：\n"
            f"{numbered}\n"
            f"只输出诗本身：每句一行，不加标题、不加序号、不加解释、不要用代码块包裹。"
        ),
        expected_chars=lines * per_line,
    )


_SONG_INSTRUCTION = (
    "请以「{theme}」为主题，创作一首中文歌词。\n"
    "结构要求：\n"
    "1) 第一行写【歌名】：xxx，第二行写【歌手】：xxx，"
    "歌手必须是虚构的华语歌手或乐队名，不得使用真实艺人姓名，然后空一行；\n"
    "2) 正文用小标题分段标注【主歌1】【副歌】【主歌2】【桥段】【副歌】；\n"
    "3) 现代白话，情感真挚，句子长短自由、朗朗上口；\n"
    "4) 副歌要有记忆点，可重复。\n"
    "只输出歌词本身，不加创作说明、不要用代码块包裹。"
)

_MODERN_INSTRUCTION = (
    "请以「{theme}」为主题，写一首现代诗。\n"
    "要求：意象新颖，语言自然，分行自由，不要古典格律与对仗，"
    "不要用「啊」「呀」一类空泛的感叹词凑韵。\n"
    "只输出诗本身，不加标题、不加解释、不要用代码块包裹。"
)

STYLES: dict[str, Style] = {
    s.label: s
    for s in (
        *(_classical(label) for label in _REGULATED),
        Style(
            key="lyrics",
            label="歌词",
            system="你是一位优秀的华语流行作词人，擅长写出有画面感和记忆点的歌词。",
            instruction=_SONG_INSTRUCTION,
        ),
        Style(
            key="modern",
            label="现代诗",
            system="你是一位当代汉语诗人，语言克制、意象具体，拒绝陈词滥调。",
            instruction=_MODERN_INSTRUCTION,
        ),
    )
}

DEFAULT_STYLE = "五言绝句"
STYLE_LABELS: list[str] = list(STYLES)


class UnknownStyleError(ValueError):
    """风格名不在策略表里。"""


def get_style(label: str) -> Style:
    try:
        return STYLES[label]
    except KeyError:
        raise UnknownStyleError(
            f"未知风格：{label!r}。可选：{', '.join(STYLE_LABELS)}"
        ) from None


def build_messages(label: str, theme: str) -> list[dict[str, str]]:
    """组装成 OpenAI 风格的消息数组。

    system 与 user 分开传，而不是像原项目那样把角色写死在一段话里——
    这样切到智能体通道时，system message 可以原样放进 input 数组首位。
    """
    style = get_style(label)
    return [
        {"role": "system", "content": style.system},
        {"role": "user", "content": style.render(theme)},
    ]
