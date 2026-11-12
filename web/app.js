/* ============================================================
   前端交互：对话框渲染 + SSE 流式接收 + 参数面板
   不引入任何框架——页面只有一个输入框和一个流，React 那套成本不划算。
   ============================================================ */

const chatEl = document.getElementById("chat");
const formEl = document.getElementById("composer");
const inputEl = document.getElementById("themeInput");
const sendBtn = document.getElementById("sendBtn");
const styleSelect = document.getElementById("styleSelect");
const styleHint = document.getElementById("styleHint");
const modeValue = document.getElementById("modeValue");
const maxCharsEl = document.getElementById("maxChars");
const paramBtn = document.getElementById("paramBtn");
const paramPanel = document.getElementById("paramPanel");
const panelCollapse = document.getElementById("panelCollapse");
const clearBtn = document.getElementById("clearBtn");
const toastEl = document.getElementById("toast");

const LEAF_SVG =
  '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 1.5l1.7 3.1 2.4-1.1-.8 2.7 3.3.5-2.3 2 1.4 2.4-3.1 0-.4 2.5-1.9-1.7v7.3h-.9l0-7.3-1.9 1.7-.4-2.5-3.1 0 1.4-2.4-2.3-2 3.3-.5-.8-2.7 2.4 1.1z"/></svg>';
const USER_SVG =
  '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="8.4" r="3.5"/><path d="M4.8 20.2c.7-3.6 3.6-5.7 7.2-5.7s6.5 2.1 7.2 5.7c.1.6-.4 1.1-1 1.1H5.8c-.6 0-1.1-.5-1-1.1z"/></svg>';

const state = {
  meta: null,
  style: null,
  streaming: false,
  controller: null,
  greeted: false,
};

const nowHM = () =>
  new Date().toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

/* ---------------- 渲染 ---------------- */

function addMessage(role, text) {
  const row = document.createElement("div");
  row.className = `msg ${role}`;

  const avatar = document.createElement("div");
  avatar.className = `avatar ${role === "ai" ? "ai" : "me"}`;
  avatar.innerHTML = role === "ai" ? LEAF_SVG : USER_SVG;

  const body = document.createElement("div");
  body.className = "msg-body";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const content = document.createElement("span");
  content.className = "bubble-text";
  content.textContent = text || "";
  bubble.append(content);

  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = nowHM();

  body.append(bubble, meta);
  row.append(avatar, body);
  chatEl.append(row);
  scrollToBottom();
  return { row, body, bubble, content, meta };
}

function setCaret(msg, on) {
  const existing = msg.bubble.querySelector(".caret");
  if (on && !existing) {
    const caret = document.createElement("span");
    caret.className = "caret";
    msg.bubble.append(caret);
  } else if (!on && existing) {
    existing.remove();
  }
}

function showTyping(msg) {
  msg.content.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
}

function scrollToBottom() {
  chatEl.scrollTop = chatEl.scrollHeight;
}

function greet() {
  const msg = addMessage("ai", "");
  msg.content.textContent =
    "我是你的诗人。给我一个主题，我来落笔——风格可以在右上角的「参数设置」里换。";

  if (state.meta && state.meta.examples && state.meta.examples.length) {
    const chips = document.createElement("div");
    chips.className = "chips";
    state.meta.examples.forEach((theme) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = theme;
      chip.addEventListener("click", () => {
        inputEl.value = theme;
        formEl.requestSubmit();
      });
      chips.append(chip);
    });
    msg.body.insertBefore(chips, msg.meta);
  }
  state.greeted = true;
}

/* ---------------- 错误与提示 ---------------- */

function showError(msg, message, code) {
  msg.bubble.classList.add("is-error");
  msg.content.textContent = message;
  if (code) {
    const tag = document.createElement("span");
    tag.className = "err-code";
    tag.textContent = `错误码 ${code}`;
    msg.bubble.append(tag);
  }
  msg.meta.textContent = nowHM();
  setCaret(msg, false);
}

let toastTimer = null;
function toast(text) {
  toastEl.textContent = text;
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastEl.hidden = true;
  }, 2200);
}

/* ---------------- 发送与流式接收 ---------------- */

async function send(theme) {
  const msg = addMessage("user", theme);
  msg.meta.textContent = nowHM();

  const reply = addMessage("ai", "");
  showTyping(reply);

  state.streaming = true;
  state.controller = new AbortController();
  sendBtn.classList.add("is-streaming");
  sendBtn.setAttribute("aria-label", "停止生成");

  let got = false;
  let aborted = false;

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme, style: state.style }),
      signal: state.controller.signal,
    });

    if (!res.ok) {
      // 400：输入校验没过，服务端返回了具体原因
      let info = { message: `请求失败（HTTP ${res.status}）`, code: "" };
      try {
        const data = await res.json();
        info = { message: data.message || info.message, code: data.code || "" };
      } catch (_) { /* 响应不是 JSON 就沿用默认文案 */ }
      showError(reply, info.message, info.code);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const handled = handleFrame(frame, reply);
        if (handled === "chunk") {
          if (!got) {
            reply.content.textContent = "";
            got = true;
          }
        } else if (handled === "stop") {
          return;
        }
      }
    }

    if (!got) {
      showError(reply, "上游没有返回内容，请重试。", "empty");
    } else {
      setCaret(reply, false);
      reply.meta.textContent = nowHM();
    }
  } catch (err) {
    if (err && err.name === "AbortError") {
      aborted = true;
      setCaret(reply, false);
      if (!got) {
        reply.content.textContent = "已停止。";
      } else {
        reply.meta.textContent = `${nowHM()} · 已停止`;
      }
    } else {
      console.error(err);
      showError(reply, "网络异常，请检查本地服务是否还在运行。", "network");
    }
  } finally {
    if (!aborted && got) setCaret(reply, false);
    state.streaming = false;
    state.controller = null;
    sendBtn.classList.remove("is-streaming");
    sendBtn.setAttribute("aria-label", "发送");
    inputEl.focus();
  }
}

function handleFrame(frame, reply) {
  let event = "message";
  const dataLines = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue; // 心跳
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return "ignore";

  let data = {};
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch (_) {
    return "ignore";
  }

  if (event === "chunk") {
    reply.content.textContent = data.text || "";
    setCaret(reply, true);
    scrollToBottom();
    return "chunk";
  }
  if (event === "done") {
    setCaret(reply, false);
    reply.meta.textContent = nowHM();
    return "done";
  }
  if (event === "error") {
    showError(reply, data.message || "生成失败，请稍后重试。", data.code);
    return "stop";
  }
  return "ignore";
}

/* ---------------- 事件绑定 ---------------- */

formEl.addEventListener("submit", (e) => {
  e.preventDefault();

  if (state.streaming) {
    // 生成中再点一次 = 停止。真正断开会通知后端停止上游，不只是遮住画面
    if (state.controller) state.controller.abort();
    return;
  }

  const theme = inputEl.value.trim();
  if (!theme) {
    toast("先写一个主题，比如「秋天」");
    inputEl.focus();
    return;
  }
  inputEl.value = "";
  send(theme);
});

styleSelect.addEventListener("change", () => {
  state.style = styleSelect.value;
  updateHint();
  inputEl.focus();
});

function updateHint() {
  const item = (state.meta?.styles || []).find((s) => s.label === state.style);
  styleHint.textContent = item && item.hint ? item.hint : "";
}

paramBtn.addEventListener("click", () => {
  const open = paramPanel.hidden;
  paramPanel.hidden = !open;
  paramBtn.setAttribute("aria-expanded", String(open));
});

panelCollapse.addEventListener("click", () => {
  paramPanel.hidden = true;
  paramBtn.setAttribute("aria-expanded", "false");
});

document.addEventListener("click", (e) => {
  if (paramPanel.hidden) return;
  if (paramPanel.contains(e.target) || paramBtn.contains(e.target)) return;
  paramPanel.hidden = true;
  paramBtn.setAttribute("aria-expanded", "false");
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !paramPanel.hidden) {
    paramPanel.hidden = true;
    paramBtn.setAttribute("aria-expanded", "false");
  }
});

clearBtn.addEventListener("click", () => {
  if (state.streaming && state.controller) state.controller.abort();
  chatEl.replaceChildren();
  greet();
  inputEl.focus();
});

document.getElementById("attachBtn").addEventListener("click", () => {
  toast("附件功能还没接入，先输入主题就好");
});
document.getElementById("emojiBtn").addEventListener("click", () => {
  toast("表情功能还没接入，先输入主题就好");
});

/* ---------------- 启动 ---------------- */

(async function boot() {
  try {
    const res = await fetch("/api/meta");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const meta = await res.json();
    state.meta = meta;
    state.style = meta.default_style;

    styleSelect.replaceChildren();
    meta.styles.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.label;
      opt.textContent = s.label;
      if (s.label === meta.default_style) opt.selected = true;
      styleSelect.append(opt);
    });
    updateHint();

    modeValue.textContent = meta.mode_label;
    maxCharsEl.textContent = `${meta.max_theme_chars} 字`;
    inputEl.setAttribute("maxlength", String(meta.max_theme_chars));

    greet();
    inputEl.focus();
  } catch (err) {
    console.error(err);
    const msg = addMessage("ai", "");
    showError(msg, "读取配置失败，服务可能没启动好。刷新页面试试。", "boot");
  }
})();
