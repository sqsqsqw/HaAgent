"""tools 冒烟测试：把每个工具都真实调用一遍。

运行：
    uv run python tests/smoke_tools.py
或：
    .venv/Scripts/python.exe tests/smoke_tools.py

联网相关用例需要能访问外网（Bing / example.com）。
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HAAGENT_WORKSPACE", ROOT)
# 记忆写到临时文件，避免污染 ~/.haagent/memory.json
os.environ["HAAGENT_MEMORY_FILE"] = os.path.join(tempfile.gettempdir(), "haagent_mem_test.json")
if os.path.exists(os.environ["HAAGENT_MEMORY_FILE"]):
    os.unlink(os.environ["HAAGENT_MEMORY_FILE"])     # 每次从干净状态开始

from haagent.tools import TOOLS  # noqa: E402

tool_map = {t.name: t for t in TOOLS}
print(f"[LOAD] 共 {len(TOOLS)} 个工具: {list(tool_map)}\n")

ok, fail = [], []


def expect(name, args, marker=None, forbid=None):
    """marker: 输出里必须包含的文本；forbid: 输出里不能出现的文本。"""
    try:
        text = str(tool_map[name].invoke(args))
    except Exception as e:                                  # noqa: BLE001
        fail.append(name)
        print(f"===== {name} ERROR =====\n{type(e).__name__}: {e}\n")
        return
    bad = not text.strip()
    if marker and marker not in text:
        bad = True
    if forbid and forbid in text:
        bad = True
    (fail if bad else ok).append(name)
    print(f"===== {name} {'FAIL' if bad else 'OK'} =====")
    print(text[:600])
    print()


print("-------- 文件工具 --------")
expect("read_text_file", {"path": "pyproject.toml", "max_lines": 8}, marker="haagent")
expect("write_text_file", {"path": ".haagent_tmp/demo.txt", "content": "第一行 hello\n第二行 world\n"})
expect("append_text_file", {"path": ".haagent_tmp/demo.txt", "content": "追加的第三行\n"})
expect("read_text_file", {"path": ".haagent_tmp/demo.txt"}, marker="追加的第三行")
expect("list_directory", {"path": ".haagent_tmp"}, marker="demo.txt")
expect("search_in_files", {"keyword": "append_text_file", "path": "src", "file_ext": ".py"}, marker="file_tools.py")
expect("file_info", {"path": ".haagent_tmp/demo.txt"}, marker="类型: 文件")
expect("copy_or_move_file", {"source": ".haagent_tmp/demo.txt", "target": ".haagent_tmp/demo_copy.txt"})
expect("delete_path", {"path": ".haagent_tmp/demo_copy.txt"}, marker="已删除")

print("-------- 越界保护（应被拒绝） --------")
print(str(tool_map["read_text_file"].invoke({"path": "C:/Windows/win.ini"})))
print(str(tool_map["run_shell"].invoke({"command": "rm -rf /"})))
print()

print("-------- 命令工具 --------")
expect("run_shell", {"command": "echo hello && ls -1 src/haagent"}, marker="hello")
expect("run_python", {"code": "print(sum(range(10)))"}, marker="45")
expect("get_system_info", {}, marker="Python")

print("-------- 联网工具 --------")
expect("web_search", {"query": "LangChain 是什么", "max_results": 3}, marker="http")
expect("fetch_web_page", {"url": "https://example.com", "max_chars": 500}, forbid="抓取失败")
expect("web_search_and_read", {"query": "langchain tool calling", "max_results": 1, "max_chars": 800})

print("-------- 持久化工具 --------")
expect("remember", {"key": "编辑器", "value": "用户喜欢用 PyCharm", "tags": "偏好,工具"}, marker="已记住")
expect("remember", {"key": "时区", "value": "Asia/Shanghai"})
expect("recall", {"key": "编辑器"}, marker="PyCharm")
expect("search_memory", {"keyword": "偏好"}, marker="编辑器")
expect("list_memories", {})
expect("recall", {"key": "不存在的key"}, marker="没有找到")
expect("forget", {"key": "时区"}, marker="已删除记忆")

print("\n================ 汇总 ================")
print(f"PASS ({len(ok)}): {ok}")
print(f"FAIL ({len(fail)}): {fail}")
sys.exit(1 if fail else 0)
