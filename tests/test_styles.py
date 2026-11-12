"""风格策略表自测：确保每种风格都能产出结构合法的 messages。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poet.styles import (  # noqa: E402
    DEFAULT_STYLE,
    STYLE_LABELS,
    STYLES,
    UnknownStyleError,
    build_messages,
    get_style,
)

PASS = 0
FAIL = 0


def check(name: str, fn) -> None:
    global PASS, FAIL
    try:
        fn()
        print(f"  [PASS] {name}")
        PASS += 1
    except AssertionError as e:
        print(f"  [FAIL] {name} -> {e}")
        FAIL += 1
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] {name} -> 意外异常 {type(e).__name__}: {e}")
        FAIL += 1


EXPECTED_LABELS = ["五言绝句", "七言绝句", "五言律诗", "七言律诗", "歌词", "现代诗"]

print("== 1. 风格表完整性 ==")


def _labels():
    assert STYLE_LABELS == EXPECTED_LABELS, f"风格列表不符: {STYLE_LABELS}"
    assert DEFAULT_STYLE in STYLES, "默认风格不在表里"


check("6 种风格齐全且顺序稳定", _labels)


def _keys_unique():
    keys = [s.key for s in STYLES.values()]
    assert len(keys) == len(set(keys)), f"key 重复: {keys}"


check("内部 key 唯一", _keys_unique)

print("== 2. messages 结构 ==")


def _structure():
    for label in STYLE_LABELS:
        msgs = build_messages(label, "秋天")
        assert len(msgs) == 2, f"{label}: 消息条数应为 2，实际 {len(msgs)}"
        assert msgs[0]["role"] == "system", f"{label}: 首条不是 system"
        assert msgs[1]["role"] == "user", f"{label}: 次条不是 user"
        assert msgs[0]["content"].strip(), f"{label}: system 为空"
        assert "秋天" in msgs[1]["content"], f"{label}: 主题没注入"
        assert "{" not in msgs[1]["content"], f"{label}: 存在未替换的占位符"
        assert "}" not in msgs[1]["content"], f"{label}: 存在未替换的占位符"


check("全部风格：system+user、主题已注入、无残留占位符", _structure)

print("== 3. 古典诗体硬约束 ==")


def _classical_constraints():
    cases = {"五言绝句": (4, 5), "七言绝句": (4, 7), "五言律诗": (8, 5), "七言律诗": (8, 7)}
    for label, (lines, per_line) in cases.items():
        text = get_style(label).render("离别")
        style = get_style(label)
        assert style.expected_chars == lines * per_line, (
            f"{label}: expected_chars 应为 {lines * per_line}，实际 {style.expected_chars}"
        )
        assert f"共 {lines} 句" in text, f"{label}: prompt 未写明句数"
        assert f"每句 {per_line} 字" in text, f"{label}: prompt 未写明每句字数"
        assert f"总字数 {lines * per_line} 字" in text, f"{label}: prompt 未写明总字数"


check("四类诗体的句数/字数约束已写入 prompt 且与 expected_chars 一致", _classical_constraints)


def _lushi_duizhang():
    for label in ("五言律诗", "七言律诗"):
        assert "对仗" in get_style(label).render("秋夜"), f"{label}: 律诗缺对仗要求"
    for label in ("五言绝句", "七言绝句"):
        assert "对仗" not in get_style(label).render("秋夜"), f"{label}: 绝句不该强制对仗"


check("律诗要求对仗、绝句不要求", _lushi_duizhang)

print("== 4. 歌词与版权约束 ==")


def _lyrics_rules():
    text = get_style("歌词").render("考试加油")
    for kw in ("【歌名】", "【歌手】", "【副歌】", "【主歌1】"):
        assert kw in text, f"歌词 prompt 缺少结构标记 {kw}"
    assert "虚构" in text and "不得使用真实艺人姓名" in text, "歌词 prompt 缺少虚构歌手约束"


check("歌词结构标记齐全且保留虚构歌手约束", _lyrics_rules)

print("== 5. 输出格式约束 ==")


def _no_markdown():
    for label in STYLE_LABELS:
        text = get_style(label).render("故乡")
        assert "不要用代码块包裹" in text, f"{label}: 缺少禁止代码块约束"
        assert "不加解释" in text or "不加创作说明" in text, f"{label}: 缺少禁止解释约束"


check("全部风格都禁止 markdown 代码块与额外解释", _no_markdown)

print("== 6. 异常路径 ==")


def _unknown_style():
    try:
        build_messages("骈文", "秋天")
    except UnknownStyleError as e:
        assert "骈文" in str(e), "错误信息里没有回显非法风格名"
        assert "五言绝句" in str(e), "错误信息没给出可选列表"
        return
    raise AssertionError("非法风格居然通过了")


check("未知风格抛 UnknownStyleError 且提示可选值", _unknown_style)


def _theme_with_braces():
    # 主题里含花括号不应破坏 format
    msgs = build_messages("五言绝句", "代码 {test} 报错")
    assert "{test}" in msgs[1]["content"], "含花括号的主题被吞掉了"


check("主题含花括号不会破坏模板渲染", _theme_with_braces)

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
