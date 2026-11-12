"""客户端自测：用 httpx.MockTransport 拦截请求，不联网、不花钱、不依赖真实 Key。

覆盖两条通道的协议正确性（URL / 请求体 / 响应解析），以及错误翻译与重试行为。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poet.client import (  # noqa: E402
    AccountError,
    AuthError,
    AppIdError,
    EmptyResponseError,
    RequestRejected,
    PoetClient,
    RateLimitError,
    UpstreamTimeout,
    UpstreamUnavailable,
    _strip_code_fence,
)
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


def make_settings(**kw) -> Settings:
    base = dict(dashscope_api_key="sk-test", max_retries=0, timeout_s=10, connect_timeout_s=2)
    base.update(kw)
    return Settings(_env_file=None, **base)


def make_client(handler, **kw) -> PoetClient:
    transport = httpx.MockTransport(handler)
    return PoetClient(make_settings(**kw), http_client=httpx.Client(transport=transport))


CHAT_RESP = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "qwen-plus",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "床前明月光\n疑是地上霜"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
}

RESPONSES_RESP = {
    "id": "resp-test",
    "object": "response",
    "created_at": 1700000000,
    "status": "completed",
    "output": [
        {
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "type": "message",
            "content": [{"type": "output_text", "text": "床前明月光\n疑是地上霜"}],
        }
    ],
}


def err_body(msg: str, code: str = "invalid") -> dict:
    return {"error": {"message": msg, "type": "invalid_request_error", "code": code}}


print("== 1. model 通道协议 ==")


def _model_ok():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=CHAT_RESP)

    client = make_client(handler, llm_mode=LLMMode.MODEL)
    out = client.generate("五言绝句", "秋天")
    assert out == "床前明月光\n疑是地上霜", out
    assert seen["path"] == "/compatible-mode/v1/chat/completions", seen["path"]
    body = seen["body"]
    assert body["model"] == "qwen-plus", body.get("model")
    assert body["temperature"] == 0.9, body.get("temperature")
    assert body["messages"][0]["role"] == "system"
    assert "秋天" in body["messages"][1]["content"]


check("model 通道：URL、model、temperature、messages 全部正确", _model_ok)

print("== 2. agent 通道协议 ==")


def _agent_ok():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=RESPONSES_RESP)

    client = make_client(handler, llm_mode=LLMMode.AGENT, app_id="app-abc123")
    out = client.generate("七言绝句", "离别")
    assert out == "床前明月光\n疑是地上霜", out
    assert seen["path"] == "/api/v2/apps/agent/app-abc123/compatible-mode/v1/responses", seen["path"]
    body = seen["body"]
    assert "model" not in body, "智能体通道不应传 model"
    assert isinstance(body["input"], list), "input 应是消息数组"
    assert body["input"][0]["role"] == "system", "system message 应在 input 首位"
    assert "离别" in body["input"][1]["content"]


check("agent 通道：URL 带 app_id、不传 model、system 在 input 首位", _agent_ok)

print("== 3. 响应解析健壮性 ==")


def _agent_multi_block():
    resp = {
        "id": "r",
        "object": "response",
        "status": "completed",
        "output": [
            {"type": "reasoning", "content": []},
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "第一段"},
                    {"type": "output_text", "text": "第二段"},
                ],
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=resp)

    client = make_client(handler, llm_mode=LLMMode.AGENT, app_id="x")
    assert client.generate("现代诗", "故乡") == "第一段第二段"


check("agent 通道：跳过非 message 元素、拼接多个 content 块", _agent_multi_block)


def _strip_fence():
    assert _strip_code_fence("```\n床前明月光\n```") == "床前明月光"
    assert _strip_code_fence("```python\nprint(1)\n```") == "print(1)"
    assert _strip_code_fence("床前明月光") == "床前明月光"
    assert _strip_code_fence("  前后空格  ") == "前后空格"


check("代码块包裹被剥掉", _strip_fence)

print("== 4. 错误翻译 ==")


def _auth():
    client = make_client(lambda req: httpx.Response(401, json=err_body("Incorrect API key")))
    try:
        client.generate("五言绝句", "秋天")
    except AuthError as e:
        assert e.code == "auth"
        assert "API Key" in e.user_message
        return
    raise AssertionError("401 没翻译成 AuthError")


check("401 -> AuthError", _auth)


def _rate():
    client = make_client(lambda req: httpx.Response(429, json=err_body("rate limited")))
    try:
        client.generate("五言绝句", "秋天")
    except RateLimitError as e:
        assert e.code == "rate_limit"
        return
    raise AssertionError("429 没翻译成 RateLimitError")


check("429 -> RateLimitError", _rate)


def _not_found():
    client = make_client(
        lambda req: httpx.Response(404, json=err_body("app not found")),
        llm_mode=LLMMode.AGENT,
        app_id="bad-id",
    )
    try:
        client.generate("五言绝句", "秋天")
    except AppIdError as e:
        assert e.code == "app_id"
        return
    raise AssertionError("404 没翻译成 AppIdError")


check("404(agent) -> AppIdError", _not_found)


def _server_error():
    client = make_client(lambda req: httpx.Response(503, json=err_body("busy")))
    try:
        client.generate("五言绝句", "秋天")
    except UpstreamUnavailable as e:
        assert e.code == "upstream"
        return
    raise AssertionError("503 没翻译成 UpstreamUnavailable")


check("503 -> UpstreamUnavailable", _server_error)


def _timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = make_client(handler)
    try:
        client.generate("五言绝句", "秋天")
    except (UpstreamTimeout, UpstreamUnavailable) as e:
        assert e.code in ("timeout", "upstream")
        return
    raise AssertionError("超时没被翻译")


check("连接超时 -> UpstreamTimeout/Unavailable", _timeout)

print("== 5. 空内容重试 ==")


def _empty_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(json.dumps(CHAT_RESP))
        body["choices"][0]["message"]["content"] = "   "
        return httpx.Response(200, json=body)

    client = make_client(handler)
    try:
        client.generate("五言绝句", "秋天")
    except EmptyResponseError:
        assert calls["n"] == 2, f"应重试 1 次共 2 次请求，实际 {calls['n']}"
        return
    raise AssertionError("空内容没抛 EmptyResponseError")


check("空内容触发 1 次重试后抛 EmptyResponseError", _empty_retry)

print("== 6. 传输层重试交给 SDK ==")


def _sdk_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json=err_body("busy"))
        return httpx.Response(200, json=CHAT_RESP)

    client = make_client(handler, max_retries=2)
    out = client.generate("五言绝句", "秋天")
    assert out.startswith("床前明月光"), out
    assert calls["n"] == 3, f"503 应被 SDK 重试到第 3 次成功，实际请求 {calls['n']} 次"


check("503 由 SDK 重试，第 3 次成功（证明未叠加 tenacity）", _sdk_retry)


def _auth_no_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json=err_body("bad key"))

    client = make_client(handler, max_retries=2)
    try:
        client.generate("五言绝句", "秋天")
    except AuthError:
        assert calls["n"] == 1, f"401 不该重试，实际请求 {calls['n']} 次"
        return
    raise AssertionError("401 没抛 AuthError")


check("401 不重试（重试一万次也没用）", _auth_no_retry)

print("== 7. 400 不能一律当 APP_ID 错误 ==")


def _account_400():
    # 阿里云欠费 / 额度耗尽时返回的就是 400 Access denied + overdue-payment
    body = err_body(
        "Access denied, please make sure your account is in good standing. "
        "For details, see: https://help.aliyun.com/zh/model-studio/error-code#overdue-payment"
    )
    client = make_client(lambda req: httpx.Response(400, json=body))
    try:
        client.generate("五言绝句", "秋天")
    except AccountError as e:
        assert e.code == "account"
        assert "账户" in e.user_message
        return
    raise AssertionError("欠费 400 没翻译成 AccountError")


check("400 + overdue-payment -> AccountError（不是 APP_ID 错误）", _account_400)


def _rejected_400():
    client = make_client(lambda req: httpx.Response(400, json=err_body("temperature out of range")))
    try:
        client.generate("五言绝句", "秋天")
    except RequestRejected as e:
        assert e.code == "rejected"
        assert "APP_ID" not in e.user_message
        return
    raise AssertionError("模型通道的参数型 400 没翻译成 RequestRejected")


check("400(模型通道) -> RequestRejected", _rejected_400)


def _agent_400():
    client = make_client(
        lambda req: httpx.Response(400, json=err_body("Invalid app id")),
        llm_mode=LLMMode.AGENT,
        app_id="app-x",
    )
    try:
        client.generate("五言绝句", "秋天")
    except AppIdError:
        return
    raise AssertionError("智能体通道的 400 仍应翻译成 AppIdError")


check("400(智能体通道) -> AppIdError", _agent_400)

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
