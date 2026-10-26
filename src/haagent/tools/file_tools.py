"""文件读写工具。

所有路径都被限制在「工作区」内（默认当前工作目录，可用环境变量 HAAGENT_WORKSPACE 覆盖），
防止模型误改工作区之外的文件。任何越界访问都会直接抛错，而不是静默放行。
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import click
from langchain.tools import tool

from haagent.utils import agent_prompt
from haagent.utils.timer_utils import timer

# 单次返回给模型的最大字符数，避免把上下文撑爆
MAX_OUTPUT_CHARS = 8000

# 搜索文件时跳过的目录 / 最大文件体积
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".idea",
             "dist", "build", ".mypy_cache", ".pytest_cache", ".haagent_tmp"}
MAX_FILE_BYTES = 2 * 1024 * 1024


# ---------------------------------------------------------------- 内部工具函数

def _workspace() -> Path:
    """返回工作区根目录（绝对路径）。"""
    root = os.environ.get("HAAGENT_WORKSPACE") or os.getcwd()
    return Path(root).expanduser().resolve()


def _resolve(path: str, must_exist: bool = False) -> Path:
    """把模型给的路径解析成绝对路径，并校验它没有跑出工作区。"""
    raw = Path(str(path).strip().strip('"').strip("'")).expanduser()
    target = (raw if raw.is_absolute() else _workspace() / raw).resolve()
    root = _workspace()
    if target != root and root not in target.parents:
        raise ValueError(f"拒绝访问：{target} 不在工作区 {root} 内")
    if must_exist and not target.exists():
        raise FileNotFoundError(f"路径不存在：{target}")
    return target


def _read_text(path: Path) -> str:
    """按 utf-8-sig → gbk → latin-1 的顺序尝试解码，尽量不因编码崩掉。"""
    data = path.read_bytes()
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _rel(path: Path) -> str:
    """相对工作区的展示路径，看着更清爽。"""
    try:
        return str(path.relative_to(_workspace()))
    except ValueError:
        return str(path)


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size}B"


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...（输出过长已截断，共 {len(text)} 字符）"


# -------------------------------------------------------------------- 工具实现

@tool
@timer
def read_text_file(path: str, start_line: int = 1, max_lines: int = 200) -> str:
    """读取文本文件内容，返回带行号的文本。

    参数：
    - path：文件路径，相对路径以工作区为基准
    - start_line：从第几行开始读（从 1 开始）
    - max_lines：最多读取多少行
    """
    print(f"📄  开始读取文件: {path}", end="")
    try:
        target = _resolve(path, must_exist=True)
    except (ValueError, FileNotFoundError) as e:
        return f"读取失败：{e}"
    if target.is_dir():
        return f"读取失败：{target} 是目录，请用 list_directory"

    start_line = max(1, int(start_line))
    max_lines = max(1, int(max_lines))
    lines = _read_text(target).splitlines()
    total = len(lines)
    chunk = lines[start_line - 1: start_line - 1 + max_lines]
    if not chunk:
        return f"文件 {_rel(target)} 共 {total} 行，起始行 {start_line} 已超出范围"

    body = "\n".join(f"{start_line + i:>5}|{line}" for i, line in enumerate(chunk))
    end = start_line + len(chunk) - 1
    header = f"# {_rel(target)}（共 {total} 行，本次显示 {start_line}-{end}）\n"
    return _clip(header + body)


@tool
@timer
@agent_prompt("我将写入{path}文件，且覆盖原内容")
def write_text_file(path: str, content: str) -> str:
    """把内容整体写入文件（覆盖原内容），父目录不存在会自动创建。

    参数：
    - path：文件路径，相对路径以工作区为基准
    - content：要写入的完整文本
    """
    print(f"📝  开始写入文件: {path}", end="")
    try:
        target = _resolve(path)
    except ValueError as e:
        return f"写入失败：{e}"
    if target.is_dir():
        return f"写入失败：{target} 是目录"

    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(str(content), encoding="utf-8", newline="\n")
    action = "覆盖" if existed else "新建"
    return f"已{action} {_rel(target)}，共写入 {len(str(content))} 个字符，{len(target.read_bytes())} 字节"


@tool
@timer
@agent_prompt("我将追加{path}文件的内容")
def append_text_file(path: str, content: str) -> str:
    """在文件末尾追加内容，文件不存在则创建。适合写日志。

    参数：
    - path：文件路径，相对路径以工作区为基准
    - content：要追加的文本
    """
    print(f"➕  开始追加文件: {path}", end="")
    try:
        target = _resolve(path)
    except ValueError as e:
        return f"追加失败：{e}"
    if target.is_dir():
        return f"追加失败：{target} 是目录"

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as f:
        f.write(str(content))
    return f"已向 {_rel(target)} 追加 {len(str(content))} 个字符"


@tool
@timer
def list_directory(path: str = ".", recursive: bool = False, max_entries: int = 200) -> str:
    """列出目录内容，目录在前、文件在后，带大小和修改时间。

    参数：
    - path：目录路径，默认工作区根目录
    - recursive：是否递归列出子目录
    - max_entries：最多列出多少项
    """
    print(f"📂  开始列目录: {path}", end="")
    try:
        target = _resolve(path, must_exist=True)
    except (ValueError, FileNotFoundError) as e:
        return f"列目录失败：{e}"
    if not target.is_dir():
        return f"列目录失败：{target} 不是目录"

    max_entries = max(1, int(max_entries))
    iterator = target.rglob("*") if recursive else target.iterdir()
    entries = []
    for item in iterator:
        if any(part in SKIP_DIRS for part in item.relative_to(target).parts):
            continue
        entries.append(item)
        if len(entries) >= max_entries + 1:
            break

    truncated = len(entries) > max_entries
    entries = entries[:max_entries]
    entries.sort(key=lambda p: (not p.is_dir(), str(p).lower()))

    rows = []
    for item in entries:
        try:
            stat = item.stat()
        except OSError:
            continue
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
        if item.is_dir():
            rows.append(f"[DIR ] {_rel(item)}/")
        else:
            rows.append(f"[{_human_size(stat.st_size):>7}] {mtime}  {_rel(item)}")

    header = f"# {_rel(target) or '.'}  共 {len(rows)} 项" + ("（已截断）" if truncated else "")
    return _clip(header + "\n" + ("\n".join(rows) if rows else "（空目录）"))


@tool
@timer
def search_in_files(keyword: str, path: str = ".", file_ext: str = "", max_results: int = 30) -> str:
    """在目录下按关键字搜索文件内容，返回「文件:行号: 匹配行」。

    参数：
    - keyword：要搜索的关键字（普通字符串，不是正则）
    - path：搜索起点目录，默认工作区根目录
    - file_ext：只搜指定扩展名，例如 ".py"；留空表示所有文本文件
    - max_results：最多返回多少条匹配
    """
    print(f"🔍  开始搜索内容: {keyword}", end="")
    try:
        start = _resolve(path, must_exist=True)
    except (ValueError, FileNotFoundError) as e:
        return f"搜索失败：{e}"

    keyword = str(keyword)
    ext = str(file_ext).strip().lower()
    max_results = max(1, int(max_results))
    hits: list[str] = []
    scanned = 0
    truncated = False

    for item in ([start] if start.is_file() else start.rglob("*")):
        if len(hits) >= max_results:
            truncated = True
            break
        if not item.is_file():
            continue
        relative_parts = item.relative_to(start).parts if start.is_dir() else ()
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        if ext and item.suffix.lower() != ext:
            continue
        try:
            if item.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        scanned += 1
        try:
            text = _read_text(item)
        except OSError:
            continue
        if "\x00" in text[:2000]:      # 粗判二进制文件
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if keyword.lower() in line.lower():
                hits.append(f"{_rel(item)}:{lineno}: {line.strip()[:300]}")
                if len(hits) >= max_results:
                    truncated = True
                    break

    if not hits:
        return f"在 {_rel(start)} 下扫描 {scanned} 个文件，未找到「{keyword}」"
    header = f"# 命中 {len(hits)} 条（扫描 {scanned} 个文件）" + ("（已截断）" if truncated else "")
    return _clip(header + "\n" + "\n".join(hits))


@tool
@timer
def file_info(path: str) -> str:
    """查看文件/目录的详细信息：绝对路径、类型、大小、时间。"""
    print(f"ℹ️  开始查看信息: {path}", end="")
    try:
        target = _resolve(path, must_exist=True)
    except (ValueError, FileNotFoundError) as e:
        return f"查询失败：{e}"

    stat = target.stat()
    kind = "目录" if target.is_dir() else ("文件" if target.is_file() else "其他")
    info = {
        "路径": str(target),
        "相对工作区": _rel(target),
        "类型": kind,
        "大小": _human_size(stat.st_size),
        "修改时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        "创建时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_ctime)),
    }
    if target.is_dir():
        info["子项数量"] = len(list(target.iterdir()))
    return "\n".join(f"{k}: {v}" for k, v in info.items())

@tool
@timer
@agent_prompt("我将{source}文件复制/移动到{target}路径下，是否移动为{move}")
def copy_or_move_file(source: str, target: str, move: bool = False) -> str:
    """复制或移动文件/目录（源和目标都必须在工作区内）。

    参数：
    - source：源路径
    - target：目标路径
    - move：True 为移动，False 为复制
    """
    print(f"📦  {'移动' if move else '复制'}文件: {source} -> {target}", end="")
    try:
        src = _resolve(source, must_exist=True)
        dst = _resolve(target)
    except (ValueError, FileNotFoundError) as e:
        return f"操作失败：{e}"

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(src), str(dst))
        elif src.is_dir():
            shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
        else:
            shutil.copy2(str(src), str(dst))
    except OSError as e:
        return f"操作失败：{e}"
    return f"已{'移动' if move else '复制'} {_rel(src)} -> {_rel(dst)}"


@tool
@timer
@agent_prompt("我将删除文件{path}")
def delete_path(path: str) -> str:
    """删除文件或目录（递归删除，危险操作，只在工作区内生效）。"""


    print(f"🗑  开始删除: {path}", end="")
    try:
        target = _resolve(path, must_exist=True)
    except (ValueError, FileNotFoundError) as e:
        return f"删除失败：{e}"
    if target == _workspace():
        return "删除失败：不允许删除工作区根目录"

    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as e:
        return f"删除失败：{e}"
    return f"已删除 {_rel(target)}"


file_tools = [
    read_text_file,
    write_text_file,
    append_text_file,
    list_directory,
    search_in_files,
    file_info,
    copy_or_move_file,
    delete_path,
]
