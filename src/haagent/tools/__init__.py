from haagent.tools.exec_tools import exec_tools
from haagent.tools.file_tools import file_tools
from haagent.tools.persistence_tools import persistence_tools
from haagent.tools.user_tools import user_tools
from haagent.tools.web_tools import web_tools

# 汇总所有工具，聊天模型通过 bind_tools(TOOLS) 一次性注册
TOOLS = [] + user_tools + file_tools + exec_tools + web_tools + persistence_tools

__all__ = [
    "TOOLS",
    "user_tools",
    "file_tools",
    "exec_tools",
    "web_tools",
    "persistence_tools",
    "information_tools"
]
