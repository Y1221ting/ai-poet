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

/* 头像与标识：一律细线水墨风格，不用色块或卡通形象 */
const LEAF_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.55" stroke-linejoin="round" stroke-linecap="round"><path d="M12 2.6l1.5 3.2 2.4-1.4-.6 3 3.4.3-2.1 2.4 1.3 2.6-3.1-.2-.3 2.9-2-1.9v7.6"/><path d="M12 2.6l-1.5 3.2L8.1 4.4l.6 3-3.4.3 2.1 2.4-1.3 2.6 3.1-.2.3 2.9 2-1.9"/></svg>';
const USER_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.45" stroke-linecap="round"><circle cx="12" cy="8.6" r="3.6"/><path d="M5.2 20.4c.9-3.5 3.6-5.4 6.8-5.4s5.9 1.9 6.8 5.4"/></svg>';

const state = {
  meta: null,
  style: null,
  streaming: false,
  controller: null,
  greeted: false,
};

/* 短札用「14.20」，落款用「2026年11月12日 17:20」，两种粒度分开 */
const nowHM = () =>
  new Date()
    .toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })
    .replace(":", ".");

const fullDate = () => {
  const d = new Date();
  const hm = d
    .toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
};

/* ---------------- 渲染 ---------------- */

/**
 * role=ai  -> 花笺：题签 + 正文 + 落款
 * role=me  -> 短札：茶褐实底 + 时间戳
 * 两者都返回 { row, body, bubble, content, meta }，上层只认这套接口。
 */
function addMessage(role, text, opts = {}) {
  const row = document.createElement("div");
  row.className = `msg ${role === "ai" ? "ai" : "me"}`;

  const avatar = document.createElement("div");
  avatar.className = `avatar ${role === "ai" ? "ai" : "me"}`;
  avatar.innerHTML = role === "ai" ? LEAF_SVG : USER_SVG;

  const body = document.createElement("div");
  body.className = "msg-body";

  let bubble;
  let content;
  let meta;

  if (role === "ai") {
    bubble = document.createElement("article");
    bubble.className = "jian";

    const tag = document.createElement("span");
    tag.className = "jian-tag";
    tag.textContent = opts.tag ?? state.style ?? "";

    content = document.createElement("p");
    content.className = "jian-text";
    content.textContent = text || "";

    const sign = document.createElement("div");
    sign.className = "jian-sign";
    const name = document.createElement("span");
    name.className = "sign-name";
    name.textContent = "AI 诗人";
    meta = document.createElement("span");
    meta.className = "sign-time";
    meta.textContent = opts.pending ? "运笔中…" : fullDate();
    sign.append(name, meta);

    bubble.append(tag, content, sign);
  } else {
    bubble = document.createElement("div");
    bubble.className = "zha";
    bubble.textContent = text || "";
    content = bubble;

    meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = nowHM();
  }

  body.append(bubble);
  if (role !== "ai") body.append(meta);

  row.append(avatar, body);
  chatEl.append(row);
  scrollToBottom();
  return { row, body, bubble, content, meta };
}

function setCaret(msg, on) {
  const existing = msg.content.querySelector(".caret");
  if (on && !existing) {
    const caret = document.createElement("span");
    caret.className = "caret";
    msg.content.append(caret);
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
  const msg = addMessage("ai", "", { tag: "序", pending: false });
  msg.content.textContent =
    "我是你的诗人。给我一个主题，我来落笔——风格可在右上角「参数设置」中更换。";
  msg.meta.textContent = "候 题";
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
    msg.content.after(tag);
  }
  msg.meta.textContent = fullDate();
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
  addMessage("user", theme);

  const reply = addMessage("ai", "", { pending: true });
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
      reply.meta.textContent = fullDate();
    }
  } catch (err) {
    if (err && err.name === "AbortError") {
      aborted = true;
      setCaret(reply, false);
      if (!got) {
        reply.content.textContent = "已停止。";
      } else {
        reply.meta.textContent = `${fullDate()} · 已停笔`;
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
    reply.meta.textContent = fullDate();
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
