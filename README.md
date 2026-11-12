# 🍂 AI 诗人 / 歌词生成器

基于 **通义千问 / 阿里云百炼** + **Gradio** 的诗词与歌词生成应用。输入一个主题、选一种风格，AI 为你创作古典诗词、现代诗或原创歌词。

支持两种调用通道，改一行配置即可切换：

| 通道 | `LLM_MODE` | 说明 |
|---|---|---|
| 模型 | `model` | 直接调 `qwen-plus` 等模型，只需 API Key |
| 智能体 | `agent` | 调百炼控制台里的**智能体应用**，需 API Key + **App ID** |

> 两者不是同一个东西：模型是「你给 prompt，模型给结果」；智能体是云端配好 prompt、知识库、插件的一整个应用，代码只能传输入。协议也不同——智能体走 Responses API，不是 `chat/completions`。

---

## ✨ 功能

- **古典诗词**：五言/七言绝句、五言/七言律诗，prompt 里写死句数与每句字数（五绝 4×5、七绝 4×7、五律 8×5、七律 8×7），律诗额外要求对仗
- **现代诗**：自由分行、意象具体
- **原创歌词**：自动生成【歌名】【歌手】+【主歌】【副歌】结构，歌手要求虚构，不使用真实艺人姓名
- **流式输出**：边生成边显示，实测首块 1.4s 左右到达
- **输入防护**：长度上限、零宽字符清理、7 类指令注入拦截
- **错误分类型**：Key 无效 / App ID 无效 / 限流 / 超时 / 上游不可用 / 输入非法，各有独立提示
- **秋季主题界面**：暖色渐变、玻璃卡片、飘落落叶

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

> 需要 **Python 3.10+**（gradio 6 的要求，不是 3.9）。依赖已全部锁定小版本。

### 2. 配置凭证

复制模板并填写：

```bash
cp .env.example .env
```

`.env`：

```ini
DASHSCOPE_API_KEY=sk-你的Key
LLM_MODE=model
# 用智能体通道时填：
# LLM_MODE=agent
# APP_ID=你的应用ID
```

也可以用环境变量（二选一）：

```powershell
# Windows（设置后需重开终端）
setx DASHSCOPE_API_KEY "sk-你的Key"
```

```bash
# macOS / Linux
export DASHSCOPE_API_KEY=sk-你的Key
```

> `.env` 已在 `.gitignore` 里，不会被提交。**不要把 Key 写进代码或 README。**

### 3. 运行

```bash
python app.py
```

浏览器会自动打开 `http://127.0.0.1:7860`。

配置有问题时进程会**直接退出并打印原因**，不会跑到一半才报错。

---

## 🔑 拿 App ID（用智能体通道才需要）

1. 登录 [阿里云百炼控制台](https://bailian.console.aliyun.com/)
2. 左侧「应用管理」→ 创建或选择一个**智能体应用**
3. 在应用卡片上复制**应用 ID**，填进 `APP_ID`
4. 确认应用已**发布**

> 智能体接口目前仅适用**华北2（北京）**地域。其他地域改 `API_HOST`。

---

## 📁 目录结构

```
ai-poet-generator/
├── app.py               # 入口：加载配置 → 建界面 → 启动
├── poet/
│   ├── config.py        # 配置层，启动即校验（pydantic-settings）
│   ├── styles.py        # 风格策略表，prompt 的唯一来源
│   ├── client.py        # LLM 客户端：双通道 + 超时 + 错误翻译
│   ├── service.py       # 业务层：输入校验 → 调用 → 输出归一
│   └── ui.py            # 界面层：Gradio Blocks + 流式
├── tests/               # 49 项自测，全部离线，不消耗额度
├── .env.example
└── requirements.txt
```

---

## 🧪 测试

```bash
python tests/test_config.py    # 11 项：配置校验与 URL 拼接
python tests/test_styles.py    #  9 项：风格表与 prompt 约束
python tests/test_client.py    # 12 项：双通道协议、错误翻译、重试
python tests/test_service.py   # 17 项：输入校验、注入防护、流式累积
```

测试用 `httpx.MockTransport` 拦截请求，**不联网、不花额度、不需要真实 Key**。

---

## ⚙️ 可调参数

全部在 `.env` 里，代码中没有魔法数字：

| 参数 | 默认 | 说明 |
|---|---|---|
| `LLM_MODE` | `model` | `model` / `agent` |
| `MODEL_NAME` | `qwen-plus` | 仅 model 通道生效 |
| `TEMPERATURE` | `0.9` | 仅 model 通道生效 |
| `TIMEOUT_S` | `60` | 单次调用硬超时。SDK 默认是 **600 秒**，必须覆盖 |
| `CONNECT_TIMEOUT_S` | `5` | 连接超时 |
| `MAX_RETRIES` | `2` | 传输层重试次数（SDK 内置，识别 429/5xx） |
| `CONCURRENCY_LIMIT` | `8` | 事件并发上限。Gradio 默认是 **1**，即全站串行 |
| `MAX_THEME_CHARS` | `50` | 主题长度上限 |

---

## ❓ 常见问题

**Q：启动报 `缺少 DASHSCOPE_API_KEY`**
没配 Key。检查 `.env` 是否存在且 `DASHSCOPE_API_KEY` 有值；用 `setx` 设置的环境变量需要**重开终端**。

**Q：`LLM_MODE=agent` 启动报缺 APP_ID**
智能体通道必须有 App ID，见上面「拿 App ID」。暂时没有就先用 `LLM_MODE=model`。

**Q：报 `APP_ID 无效、应用未发布或无访问权限`**
三种可能：App ID 抄错、应用没发布、应用在其他业务空间（需要工作空间 ID）。

**Q：报 `触发上游限流`**
账号 QPS 或额度到了，等一会或去控制台看配额。

**Q：一个卡住的请求会不会把整个应用锁死？**
以前会——SDK 默认 600 秒超时 × 3 次重试 = 最坏 30 分钟，配合 Gradio 默认并发 1，全站等待。现在超时降到 60 秒且并发放开到 8，不会了。

---

## 📄 说明

- 生成的诗词/歌词均为 AI 原创，不涉及他人版权。
- 本项目通过环境变量读取 Key，代码与仓库不含任何密钥。

## 📜 License

MIT
