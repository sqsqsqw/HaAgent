
from langchain.tools import tool
import click

from haagent.utils import ip_utils
from datetime import datetime
import time

from haagent.utils.timer_utils import timer

@tool
@timer
def confirm_perm_oper(mess: str) -> str:
    """以你自己为第一人称，将你要操作的行为或者具体的执行命令提供给用户审核，返回是否同意操作"""
    print("🪧  需要你确认操作哦:")
    print(f"        {mess}")
    if click.confirm("是否继续执行高危操作？（同意y/拒绝N）", default=False):
        print("✅ 已同意")
        return "已同意"
    else:
        print("❌ 已拒绝")
        return "已拒绝"


@tool
@timer
def notice(mess: str) -> str:
    """给用户推送通知，无返回值"""
    print("🔊  小哈来通知你啦:", end="")

    print(f"{mess}", end="")
    return ""



information_tools = [confirm_perm_oper, notice]