"""配置层自测：覆盖正常/异常/边界三类情形。不联网、不花钱。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poet.config import LLMMode, Settings  # noqa: E402

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


def fresh(**kwargs) -> Settings:
    """绕过环境变量与 .env，直接构造。"""
    return Settings(_env_file=None, **kwargs)


print("== 1. 缺少 Key 必须启动即失败 ==")


def _no_key():
    try:
        fresh(dashscope_api_key="")
    except ValueError as e:
        assert "DASHSCOPE_API_KEY" in str(e), f"错误信息不够定位: {e}"
        return
    raise AssertionError("空 Key 居然构造成功了")


check("空 Key 抛错且提示明确", _no_key)


def _blank_key():
    try:
        fresh(dashscope_api_key="   ")
    except ValueError:
        return
    raise AssertionError("纯空格 Key 居然通过了")


check("纯空格 Key 也被拦截", _blank_key)

print("== 2. model 通道 ==")


def _model_url():
    s = fresh(dashscope_api_key="sk-test", llm_mode=LLMMode.MODEL)
    assert s.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1", s.base_url
    assert s.is_agent is False


check("model 通道 base_url 正确", _model_url)


def _model_no_appid_ok():
    s = fresh(dashscope_api_key="sk-test", llm_mode=LLMMode.MODEL, app_id="")
    assert s.is_agent is False
    assert "qwen-plus" in s.effective_mode_label


check("model 通道不要求 APP_ID", _model_no_appid_ok)

print("== 3. agent 通道 ==")


def _agent_missing_appid():
    try:
        fresh(dashscope_api_key="sk-test", llm_mode=LLMMode.AGENT, app_id="")
    except ValueError as e:
        assert "APP_ID" in str(e), f"错误信息不够定位: {e}"
        return
    raise AssertionError("agent 模式缺 APP_ID 居然通过了")


check("agent 通道缺 APP_ID 抛错", _agent_missing_appid)


def _agent_url():
    s = fresh(dashscope_api_key="sk-test", llm_mode=LLMMode.AGENT, app_id="abc123def456")
    expect = "https://dashscope.aliyuncs.com/api/v2/apps/agent/abc123def456/compatible-mode/v1/"
    assert s.base_url == expect, s.base_url
    assert s.is_agent is True


check("agent 通道 base_url 正确（含 app_id 与结尾斜杠）", _agent_url)


def _custom_host():
    s = fresh(
        dashscope_api_key="sk-test",
        llm_mode=LLMMode.AGENT,
        app_id="x1",
        api_host="https://dashscope-intl.aliyuncs.com/",
    )
    assert s.base_url.startswith("https://dashscope-intl.aliyuncs.com/api/v2/apps/agent/x1/")
    assert "//api" not in s.base_url, "host 尾部斜杠导致双斜杠"


check("自定义 host 尾部斜杠被正确归一", _custom_host)

print("== 4. 边界值与联动校验 ==")


def _timeout_order():
    try:
        fresh(dashscope_api_key="sk-test", timeout_s=5, connect_timeout_s=10)
    except ValueError as e:
        assert "connect_timeout_s" in str(e)
        return
    raise AssertionError("connect >= total 居然通过了")


check("connect_timeout 必须小于 timeout", _timeout_order)


def _temp_range():
    try:
        fresh(dashscope_api_key="sk-test", temperature=3.0)
    except Exception:  # noqa: BLE001
        return
    raise AssertionError("temperature=3.0 居然通过了")


check("temperature 超范围被拦截", _temp_range)


def _concurrency_range():
    try:
        fresh(dashscope_api_key="sk-test", concurrency_limit=0)
    except Exception:  # noqa: BLE001
        return
    raise AssertionError("concurrency_limit=0 居然通过了")


check("concurrency_limit=0 被拦截", _concurrency_range)

print("== 5. 环境变量优先于默认值 ==")


def _env_override():
    os.environ["DASHSCOPE_API_KEY"] = "sk-from-env"
    os.environ["APP_ID"] = "env-app-id"
    os.environ["LLM_MODE"] = "agent"
    try:
        s = Settings(_env_file=None)
        assert s.dashscope_api_key == "sk-from-env", s.dashscope_api_key
        assert s.app_id == "env-app-id", s.app_id
        assert s.llm_mode is LLMMode.AGENT
    finally:
        for k in ("DASHSCOPE_API_KEY", "APP_ID", "LLM_MODE"):
            os.environ.pop(k, None)


check("DASHSCOPE_API_KEY / APP_ID / LLM_MODE 可从环境变量读取", _env_override)

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
