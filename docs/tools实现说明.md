# tools 模块实现说明

本次补齐了 `src/haagent/tools/` 下 4 个空文件（原本 0 字节，无需备份），并改写了 `__init__.py` 汇总工具列表。
原有 `user_tools.py`（天气/定位/时间）未做任何修改。

## 工具总览（22 个）

| 模块 | 工具 | 作用 |
|---|---|---|
| user_tools（原有） | get_weather / get_location / get_full_local_time | 天气、定位、本地时间 |
| file_tools | read_text_file | 读文件，带行号，可分页 |
| | write_text_file | 整体写入（覆盖），自动建父目录 |
| | append_text_file | 追加内容（写日志用） |
| | list_directory | 列目录，目录在前，带大小/时间 |
| | search_in_files | 按关键字搜内容，返回「文件:行号: 行」 |
| | file_info | 绝对路径、类型、大小、时间 |
| | copy_or_move_file | 复制或移动 |
| | delete_path | 删除文件/目录（危险，见安全边界） |
| exec_tools | run_shell | 执行 shell 命令，返回退出码 + stdout/stderr |
| | run_python | 执行一段 Python 代码（临时文件，跑完即删） |
| | get_system_info | OS / Python / 解释器 / 可用命令 |
| web_tools | web_search | 联网搜索，零 API key |
| | fetch_web_page | 抓网页并提取正文纯文本 |
| | web_search_and_read | 搜索 + 逐条抓正文，一次给带出处的资料 |
| persistence_tools | remember / recall | 存/取一条长期记忆（JSON 落盘） |
| | search_memory / list_memories | 按关键字搜索 / 全部列出 |
| | forget | 删除一条记忆 |

## 安全边界（重要）

1. **文件工具全部锁定在工作区内**
   工作区 = 环境变量 `HAAGENT_WORKSPACE`，未设置则取进程当前目录。
   任何解析后落到工作区之外的路径直接返回「拒绝访问」，不会静默放行。
   实测：`read_text_file("C:/Windows/win.ini")` → 拒绝。

2. **命令工具有危险命令黑名单**
   `rm -rf /`、`mkfs`、`dd of=/dev/`、`format C:`、`shutdown/reboot`、`del /f /s`、
   `rd /s`、`reg delete`、fork 炸弹、`curl | sh`、`chmod -R 777 /`、`diskpart` 等命中即拒绝，
   不执行、直接返回拦截原因。

3. **时间与输出都有上限**
   `run_shell` / `run_python` 默认 60s 超时可调（上限 300s）；所有工具返回给模型的文本都会截断
   （文件类 8000 字符、命令类 6000 字符，超长保留头尾并标注省略了多少）。

4. **记忆文件写入是原子的**
   `~/.haagent/memory.json` 先写临时文件 + fsync，再 `os.replace` 替换，写一半断电不会损坏；
   文件若已损坏会自动改名为 `.broken-<时间戳>.json` 备份后重建。

## 联网方案：为什么「全程免费」

不依赖任何付费 API、不需要 key，只用 HTTP 请求 + 自己解析：

- **搜索**：Bing RSS（`bing.com/search?q=...&format=RSS`，返回规范 XML，国内可直连，实测 0.5s 内出结果）
  → DuckDuckGo HTML（海外网络备选）→ 360 搜索 HTML（最后兜底）。前一源失败自动换下一个。
  实测：DuckDuckGo 在国内超时（符合预期），Bing 稳定可用。
- **抓正文**：自己写了 `HTMLParser` 子类剥标签，跳过 script/style/noscript/svg/iframe，
  块级标签处换行、折叠空行；按响应头 charset → utf-8 → gbk 依次解码；
  支持 gzip/deflate 解压。**没有引入 bs4 / readability / requests 等额外依赖**，
  全部标准库，`pyproject.toml` 未新增依赖。

## 目录与配置

- 新增 `tests/smoke_tools.py`：22 个工具全部真实调用一遍，联网用例需外网。
- 新增 `.gitignore`：忽略 `.venv/`、`__pycache__/`、`.haagent_tmp/`、`.env`、`.idea/`。
- `run_python` 的临时脚本放在 `<工作区>/.haagent_tmp/`（已忽略，且不参与文件搜索）。

可配置的环境变量：

| 变量 | 作用 | 默认 |
|---|---|---|
| `HAAGENT_WORKSPACE` | 文件/命令工具的工作区根目录 | 进程当前目录 |
| `HAAGENT_MEMORY_FILE` | 记忆 JSON 路径 | `~/.haagent/memory.json` |
| `HAAGENT_SHELL` | 指定 shell 展示名（覆盖自动探测） | Windows 优先 bash，否则 cmd |

## 验证方式

```bash
.venv/Scripts/python.exe tests/smoke_tools.py     # 或 uv run python tests/smoke_tools.py
```

当前结果：`PASS (22) / FAIL (0)`；`ChatModel()` 绑定工具数 22，LangChain schema 生成正常。
Ollama 未启动（`localhost:11434` 无响应），因此未做「模型真的选工具」的端到端对话验证——
启动 `ollama serve` 并确保 `qwen3.5:4b` 可用后运行 `main.py` 即可。

## 后续可扩展

- 工具多了以后，`qwen3.5:4b` 选工具的准确率会下降，可以拆分工具集或换更大的模型。
- `middleware.py` 里的 `wrap_tool_call` 目前没接进 `chat.py`，接进去就能做统一的工具日志/拦截。
- `web_search` 若想更稳，可加一个可配置的搜索源顺序（现在写死在 `_SEARCH_SOURCES`）。
