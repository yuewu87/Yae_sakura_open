# 八重樱桌面助手 — Yae Sakura Desktop Companion

基于 PyQt5 的桌面 AI 角色扮演助手，角色为崩坏3「八重樱」，集成 Live2D 模型、流式对话、TTS 语音合成、视觉感知与长期记忆。

## 功能

| 模块 | 说明 |
|------|------|
| Live2D 展示 | PixiJS + Cubism SDK 渲染八重樱模型，支持口型同步 |
| 流式对话 | 多运营商 API（DeepSeek/千问/MiMo），支持思考模式，逐字流式输出 |
| TTS 语音 | GPT-SoVITS 八重樱音色，WebSocket 异步合成 + 本地播放，打断渐弱 |
| 视觉系统 | 摄像头人脸检测（MediaPipe），用户离开/归来感知，表情识别 |
| 记忆系统 | 三层记忆（工作/摘要）+ Obsidian Vault 长期记忆 + text2vec 向量语义检索 |
| 自动消息 | 可配超时自动对话；用户归来自动检测 |
| 知识库 | jieba + TF-IDF 语义检索，23 条角色知识，上下文加权 |

## 环境要求

- **Python**: 3.10+（推荐 conda 环境）
- **操作系统**: Windows 10/11
- **GPU**: TTS 推理需要 NVIDIA GPU（>=6GB VRAM）
- **摄像头**: 可选，用于视觉系统（人脸检测 + 表情识别）

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/yuewu87/Yae_sakura_open.git
cd Yae_sakura_open
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 下载模型

```bash
pip install huggingface_hub
python download_models.py
```

这会从 HuggingFace 下载：
- `shibing624/text2vec-base-chinese` — 文本嵌入模型 (422M)
- `yuewu871/yae-sakura-models` — TTS 权重 + Live2D 模型 (248M)

### 4. 安装 GPT-SoVITS 引擎

```bash
git clone https://github.com/RVC-Boss/GPT-SoVITS.git TTS_GPT_SoVITS/GPT_SoVITS
cd TTS_GPT_SoVITS/GPT_SoVITS
pip install -r requirements.txt
cd ../..
```

> GPT-SoVITS 需要额外安装 FFmpeg。建议使用 conda: `conda install ffmpeg`

### 5. 配置 API 密钥

复制 `.env.example` 为 `.env`，填入至少一个运营商的 API Key：

```bash
cp .env.example .env
```

支持的运营商：
- **DeepSeek** — https://platform.deepseek.com
- **千问 (Qwen)** — https://dashscope.aliyun.com
- **MiMo** — https://mimo.chat

### 6. 启动

先启动 TTS 服务（独立终端）：

```bash
python TTS_GPT_SoVITS/start_servers.py
```

再启动主界面（另一个终端）：

```bash
python 20_ui_第十七版_八重樱_沉浸界面.py
```

## 项目结构

```
├── 20_ui_第十七版_八重樱_沉浸界面.py   # 主程序入口
├── 启动TTS服务.bat                      # TTS 一键启动（Windows）
├── download_models.py                   # 模型下载脚本
├── requirements.txt                     # Python 依赖
├── need/                                # 核心功能模块
│   ├── chat/        对话线程 + WebView 消息渲染
│   ├── tts/         TTS 管理器
│   ├── memory/      记忆系统（Vault/摘要/工作）+ 管理对话框
│   ├── live2d/      Live2D 模型管理
│   ├── vision/      摄像头视觉系统
│   ├── knowledge/   知识库语义检索
│   ├── assets/      角色设定/HTML模板/JS库/知识库
│   └── api_config.py  API 运营商配置
├── TTS_GPT_SoVITS/                      # TTS 服务端（自研）
│   ├── start_servers.py     启动入口
│   ├── tts_websocket_server.py  WebSocket 服务
│   ├── tts_inferencer.py    推理器封装
│   └── GPT_SoVITS/          ← 需自行 clone
├── data/                                # 数据与模型（运行后下载）
│   ├── live2d_models/   Live2D 模型文件
│   ├── TTS_models/      GPT-SoVITS 权重
│   ├── text_models/     本地嵌入模型
│   ├── sakura_vault/    Obsidian 兼容长期记忆
│   └── img/             背景图片
```

## 侧边栏功能

- 左上角 `=` 按钮打开侧边栏
- **语音系统**：启动/关闭 TTS 服务器 + 连接/断开客户端
- **视觉系统**：启停摄像头 + 预览
- **API 运营商**：切换 DeepSeek/千问/MiMo，配置 Key 和模型
- **调试系统**：LLM 对话日志、记忆暂停开关、设置
- **记忆系统**：查看 Vault 长期记忆、清空记忆

## 已知问题

- text2vec 模型首次加载较慢（约 10-30 秒，取决于硬件）
- TTS 长句合成偶有丢词
- Qt 5.15 内嵌 Chromium 不支持 `backdrop-filter`
- GPT-SoVITS 与当前项目子模块方案不兼容，需手动 clone 到指定目录

## License

MIT License — 详见 [LICENSE](LICENSE)
