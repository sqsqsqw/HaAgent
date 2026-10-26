# HaAgent

> **一个还在开发中的本地 AI Agent 实验项目。**

---

```
███████╗ ██████╗ ██████╗     ██████╗ ███████╗██╗   ██╗
██╔════╝██╔═══██╗██╔══██╗    ██╔══██╗██╔════╝██║   ██║
█████╗  ██║   ██║██████╔╝    ██║  ██║█████╗  ██║   ██║
██╔══╝  ██║   ██║██╔══██╗    ██║  ██║██╔══╝  ╚██╗ ██╔╝
██║     ╚██████╔╝██║  ██║    ██████╔╝███████╗ ╚████╔╝
╚═╝      ╚═════╝ ╚═╝  ╚═╝    ╚═════╝ ╚══════╝  ╚═══╝
```

# ⚠️ 警告：本项目处于开发阶段 ⚠️

**代码未完成、未经安全审计、接口随时可能变更。请勿用于生产环境。**

# ⚠️ 必须在沙箱中执行 ⚠️

**HaAgent 会以当前用户的权限在你的机器上执行 Shell 命令、运行任意 Python 代码、读写文件、访问网络。**
**它没有任何真正的权限边界。请务必在容器 / 虚拟机 / 一次性环境中运行，不要在你的主力工作机上裸跑。**

# ⚠️ 使用风险自担 ⚠️

**本项目按 "AS IS" 提供，不附带任何明示或暗示的担保。**
**因使用本项目导致的任何数据丢失、文件损坏、系统故障、密钥泄露、费用支出或其他任何直接 / 间接损失，均由使用者自行承担，作者不承担任何责任。**
**如果你不能接受这一点，请不要运行本项目。**

---

## 项目状态

| 项目 | 状态 |
| --- | --- |
| 版本 | `0.1.0`（**开发中 / Development**） |
| 稳定性 | ❌ 不稳定，API 与工具签名随时会变 |
| 测试 | ❌ 仅有冒烟脚本，无完整测试覆盖 |
| 文档 | 🚧 补写中 |
| 安全审计 | ❌ 从未进行 |
| 生产可用 | ❌ 明确不可用 |

当前只是一个**本地实验性 Agent**：通过 Ollama 驱动本地模型，配合一组自实现工具完成"聊天 + 动手干活"的闭环。大量功能（CLI 界面、权限确认、上下文管理）仍在开发或占位状态。

---

## 它是什么

一个用 Python + LangChain 写的本地 Agent 骨架：

- 推理端：`langchain-ollama` 调用本地 Ollama 模型（默认 `qwen3.5:4b`）
- 执行端：一组自实现的 `@tool` 工具，由模型自行决定调用
- 交互端：目前是极简的 `input()` 循环；Textual TUI 只搭了空壳，尚未接线

主循环在 `src/haagent/agent/chat.py`，工具注册见 `src/haagent/tools/__init__.py`。

---

## 工具一览

| 分类 | 工具 | 说明 |
| --- | --- | --- |
| 命令执行 | `run_shell` | 执行 Shell 命令（Windows 下优先 bash，否则 cmd） |
| 命令执行 | `run_python` | 执行一段 Python 代码 |
| 命令执行 | `get_system_info` | 读取系统信息 |
| 文件操作 | `read_text_file` / `write_text_file` / `append_text_file` | 文本读写 |
| 文件操作 | `list_directory` / `search_in_files` / `file_info` | 目录遍历、内容检索、文件属性 |
| 文件操作 | `copy_or_move_file` | 复制 / 移动 |
| 网络 | `web_search` | Bing / DuckDuckGo / 360 多源搜索 |
| 网络 | `fetch_web_page` / `web_search_and_read` | 抓取网页并转文本 |
| 记忆 | `remember` / `recall` / `search_memory` / `list_memories` / `forget` | 本地 JSON 键值记忆 |
| 环境 | `get_location` / `get_weather` / `get_full_local_time` | 位置、天气、本地时间 |
| 交互 | `confirm_perm_oper` / `notice` | 权限确认与提示（实现尚不完整） |

> 提醒：这些工具的能力叠加起来，等价于**一个能自发决定执行什么命令的远程 Shell**。这也是上面反复强调"必须沙箱运行"的原因。

### 现有的"安全"措施（很弱，别依赖）

- 工作目录锁定：默认当前工作目录，可用 `HAAGENT_WORKSPACE` 指定
- 危险命令正则黑名单（`rm -rf /`、`mkfs`、`dd of=/dev/`、`format`、`shutdown`、`curl | sh` 等）
- 输出长度截断，避免撑爆上下文
- 目的：**防手滑，不防恶意**。正则黑名单可被轻易绕过，不要把它当作安全边界。

---

## 快速开始

前置条件：Python **3.14+**、[uv](https://docs.astral.sh/uv/)、本地已跑起 [Ollama](https://ollama.com/) 并拉取模型。

```bash
git clone https://github.com/sqsqsqw/HaAgent.git
cd HaAgent

uv sync

# 启动 Ollama（另开一个终端）
ollama pull qwen3.5:4b
ollama serve
```

运行：

```bash
uv run python main.py
```

或安装为脚本后：

```bash
uv run haagent
```

在交互提示符输入指令即可，Agent 会自行决定调用哪些工具。

---

## 推荐运行方式：容器

这是**推荐**而不是可选的做法。示例（按需自行加固，例如去掉网络、只挂载临时目录、限制资源）：

```bash
docker run --rm -it \
  --network none \
  -v /tmp/haagent-workspace:/workspace \
  -w /workspace \
  -e HAAGENT_WORKSPACE=/workspace \
  python:3.14-slim bash
```

容器内再按上面的"快速开始"安装运行。**不要**把宿主机家目录、SSH 私钥、云厂商凭证挂进容器。

---

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HAAGENT_WORKSPACE` | 当前工作目录 | 文件与命令工具的工作区根目录，路径会被锁定在此之下 |

模型在 `src/haagent/agent/chat.py` 中硬编码（`ChatOllama(model="qwen3.5:4b")`），暂未提供配置项。`.env` 与 `.idea/` 均被 `.gitignore` 排除，请勿提交密钥。

---

## 已知限制

- CLI 用的是最原始的 `input()` 循环，Textual TUI 尚未接通
- 无会话持久化、无上下文压缩，长对话会撑爆上下文
- 无权限审批流程，工具调用直接执行（`confirm_perm_oper` 只是占位）
- 无重试 / 超时治理，网络工具依赖第三方页面结构，随时可能失效
- 无测试体系，改动即可能回归
- 仅适配 Windows / Linux 的常见 shell 环境，其他平台未验证

---

## 目录结构

```
HaAgent/
├── main.py                     # 入口
├── pyproject.toml              # uv 项目配置
├── src/haagent/
│   ├── agent/
│   │   ├── chat.py             # 模型 + 工具调用主循环
│   │   ├── main.py             # 交互循环
│   │   └── middleware.py
│   ├── tools/                  # 工具实现（exec/file/web/memory/user）
│   ├── utils/                  # 时间、IP、确认等辅助
│   └── cli/                    # Textual TUI（未完工）
├── docs/                       # 设计与工具说明
└── tests/                      # 冒烟脚本
```

---

## 免责声明

本项目仅用于个人学习与技术验证。使用本项目即表示你已理解并同意：

1. 本项目处于开发阶段，可能存在严重缺陷；
2. 本项目具有执行任意命令与代码的能力，必须隔离运行；
3. 由此产生的一切后果与损失，由使用者自行承担，作者不提供任何形式的担保或赔偿；
4. 使用本项目从事的任何行为（含违反当地法律法规的行为）与作者无关。

如果你不认同以上任何一条，请立即停止使用并删除本项目。
