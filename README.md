# 🍂 AI 诗人 / 歌词生成器

一个基于 **通义千问（DashScope）大模型 API** + **Gradio** 的 Web 小应用：输入主题与风格，让 AI 为你创作古典诗词、现代诗或原创歌词。

## ✨ 功能

- 古典诗词：五言/七言绝句、五言/七言律诗（讲究格律、对仗、押韵）
- 现代诗：自由分行、意象化
- 原创歌词：自动生成【歌名】【歌手】+【主歌】【副歌】结构
- 秋意界面：暖色渐变背景、玻璃质感卡片、动态落叶飘落效果

## 🧱 技术栈

- Python 3.9+
- Gradio（Web 界面）
- OpenAI SDK（调用通义千问 OpenAI 兼容接口）
- 阿里云百炼 / 通义千问 API

## 📦 安装

```bash
pip install -r requirements.txt
```

## 🔑 配置 API Key

1. 打开 [阿里云百炼控制台](https://bailian.console.aliyun.com/)，注册并开通服务，创建 API Key。
2. 把 Key 配置为环境变量（推荐）：

Windows（PowerShell）：

```powershell
setx DASHSCOPE_API_KEY "sk-你的Key"
```

macOS / Linux：

```bash
export DASHSCOPE_API_KEY=sk-你的Key
```

> 也可以直接在网页的「API Key」输入框里临时粘贴，无需配置环境变量。

## ▶️ 运行

```bash
python app.py
```

浏览器会自动打开（也可手动访问终端显示的 `http://127.0.0.1:7860` 等地址）。

## 🖱️ 使用

1. 输入主题（如「秋天」「离别」「考试加油」）
2. 选择风格（古典诗词 / 现代诗 / 歌词）
3. 点击「✨ 生成」
4. 右侧查看结果

## 📄 说明

- 生成的诗词/歌词均为 **AI 原创内容**，非搬运现有作品，不涉及他人版权。
- 请勿把 API Key 提交到代码仓库：本项目通过环境变量读取 Key，代码本身不含密钥。

## 📁 目录结构

```
ai-poet-generator/
├── app.py            # 主程序（界面 + 调用大模型）
├── requirements.txt  # 依赖清单
├── .gitignore
└── README.md
```

## 📜 License

MIT
