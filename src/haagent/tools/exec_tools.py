"""命令执行工具。

两条腿：
- run_shell：执行 shell 命令（Windows 下优先用 bash，没有则退回 cmd）
- run_python：跑一段 Python 代码

安全约束：工作目录锁定在工作区内；内置危险命令黑名单（删根目录、格式化磁盘、关机等）直接拒绝；
输出长度截断，避免把上下文撑爆。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from langchain.tools import tool

from haagent.utils import agent_prompt
from haagent.utils.timer_utils import timer

MAX_OUTPUT_CHARS = 6000
DEFAULT_TIMEOUT = 60

# 危险命令黑名单：命中直接拒绝执行
DANGEROUS_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*\s+)*-?[rR]?f?[rR]?\s+(/|~|\$HOME)\s*$",  # rm -rf /
    r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*\s+(/|~)\b",
    r"\bmkfs(\.\w+)?\b",                       # 格式化分区
    r"\bdd\s+if=.+\s+of=/dev/",               # 直接写磁盘
    r"\bformat\s+[a-zA-Z]:",                   # Windows format
    r"\b(shutdown|reboot|halt|poweroff)\b",    # 关机重启
    r"\bdel\s+/[fsq]\b",                       # del /f /s /q
    r"\brd\s+/s\b|\brmdir\s+/s\b",             # rd /s
    r"\breg\s+delete\b",                       # 删注册表
    r":\(\)\s*\{.*\};\s*:",                    # fork 炸弹
    r"\b(curl|wget)\b[^|;]*\|\s*(sudo\s+)?(ba)?sh\b",  # 下载即执行
    r">\s*/dev/sd[a-z]",
    r"\bchmod\s+-R\s+777\s+/\s*$",
    r"\bdiskpart\b|\bcipher\s+/w\b",
    r"\bbcdedit\b",
]
_DANGEROUS_RE = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]


def _workspace() -> Path:
    root = os.environ.get("HAAGENT_WORKSPACE") or os.getcwd()
    return Path(root).expanduser().resolve()


def _resolve_dir(path: str) -> Path:
    raw = Path(str(path).strip().strip('"').strip("'")).expanduser()
    target = (raw if raw.is_absolute() else _workspace() / raw).resolve()
    root = _workspace()
    if target != root and root not in target.parents:
        raise ValueError(f"拒绝执行：工作目录 {target} 不在工作区 {root} 内")
    return target


def _detect_shell() -> tuple[str | None, str]:
    """返回 (可执行文件, 展示名)。Windows 优先 git-bash，其次 cmd。"""
    override = os.environ.get("HAAGENT_SHELL")
    if override:
        return None, override
    if os.name == "nt":
        bash = shutil.which("bash")
        if bash:
            return bash, "bash"
        return None, "cmd"
    return None, "sh"


def _decode(data: bytes) -> str:
    """subprocess 输出按 utf-8 → gbk → latin-1 依次解码（Windows 中文常见 GBK）。"""
    if not data:
        return ""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head, tail = text[: int(limit * 0.7)], text[-int(limit * 0.2):]
    return f"{head}\n...（中间省略 {len(text) - len(head) - len(tail)} 字符）...\n{tail}"


def _check_command(command: str) -> str | None:
    for pattern in _DANGEROUS_RE:
        if pattern.search(command):
            return f"命令被安全策略拦截（匹配危险模式：{pattern.pattern}）"
    return None


# -------------------------------------------------------------------- 工具实现

@tool
@timer
@agent_prompt("我将执行命令{command}")
def run_shell(command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """在工作区内执行一条 shell 命令，返回退出码、标准输出和标准错误。

    注意：Windows 下若有 git-bash 则按 bash 语法执行（可用 ls/grep/cat），
    否则按 cmd 语法执行。别执行会阻塞的交互式命令（如 vim、python 交互式）。

    参数：
    - command：要执行的命令，例如 "ls -la" 或 "git status --short"
    - timeout：超时秒数，默认 60，最大 300
    """
    print(f"⌨️  开始执行命令: {command}", end="")
    blocked = _check_command(command)
    if blocked:
        return blocked

    timeout = max(1, min(int(timeout), 300))
    shell_path, shell_name = _detect_shell()
    if shell_path:
        argv = [shell_path, "-lc", command]
    elif os.name == "nt":
        argv = ["cmd", "/c", command]
    else:
        argv = ["/bin/sh", "-c", command]

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(_workspace()),
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        return (f"执行超时（>{timeout}s）已强制终止\n"
                f"命令: {command}\n部分输出:\n{_clip(_decode(e.stdout or b''))}")
    except OSError as e:
        return f"执行失败：{e}"

    elapsed = time.perf_counter() - t0
    parts = [
        f"$ {command}    [{shell_name}]",
        f"退出码: {proc.returncode}   耗时: {elapsed:.2f}s",
    ]
    stdout = _decode(proc.stdout).rstrip()
    stderr = _decode(proc.stderr).rstrip()
    if stdout:
        parts.append("--- stdout ---\n" + _clip(stdout))
    if stderr:
        parts.append("--- stderr ---\n" + _clip(stderr))
    if not stdout and not stderr:
        parts.append("（无输出）")
    return "\n".join(parts)


@tool
@timer
@agent_prompt("我将运行一段python代码：{code}")
def run_python(code: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """执行一段 Python 代码并返回输出（在临时文件里运行当前虚拟环境的解释器）。

    适合做计算、处理数据、验证小逻辑。代码里的 print 结果会返回给你。

    参数：
    - code：完整的 Python 代码文本
    - timeout：超时秒数，默认 60，最大 300
    """
    print("🐍  开始执行 Python 代码", end="")
    timeout = max(1, min(int(timeout), 300))
    tmp_dir = _workspace() / ".haagent_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    script = tmp_dir / f"snippet_{uuid.uuid4().hex[:8]}.py"
    script.write_text(code, encoding="utf-8", newline="\n")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(script)],
            cwd=str(_workspace()),
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Python 代码执行超时（>{timeout}s）已终止"
    except OSError as e:
        return f"执行失败：{e}"
    finally:
        script.unlink(missing_ok=True)

    parts = [f"退出码: {proc.returncode}"]
    stdout = _decode(proc.stdout).rstrip()
    stderr = _decode(proc.stderr).rstrip()
    if stdout:
        parts.append("--- stdout ---\n" + _clip(stdout))
    if stderr:
        parts.append("--- stderr ---\n" + _clip(stderr))
    if not stdout and not stderr:
        parts.append("（无输出，记得用 print 打印结果）")
    return "\n".join(parts)


@tool
@timer
def get_system_info() -> str:
    """查看当前运行环境：操作系统、Python 版本、解释器路径、工作区、常用命令是否可用。"""
    print("🖥  开始获取系统信息", end="")
    commands = ["git", "uv", "bash", "node", "java", "docker"]
    available = {c: (shutil.which(c) or "未安装") for c in commands}
    lines = [
        f"操作系统: {os.name} / {sys.platform}",
        f"Python: {sys.version.split()[0]}",
        f"解释器: {sys.executable}",
        f"工作区: {_workspace()}",
        f"shell: {_detect_shell()[1]}",
        f"CPU 核数: {os.cpu_count()}",
    ]
    lines += [f"命令 {k}: {v}" for k, v in available.items()]
    return "\n".join(lines)


exec_tools = [run_shell, run_python, get_system_info]
