from langchain.agents.middleware import wrap_tool_call


@wrap_tool_call
def tool_logger(request, handler):
    # request 包含：工具名、入参、state、runtime上下文
    print(f"[Middleware 前置] 调用工具：{request.name}, 参数：{request.args}")
    # 这里可以做拦截：if request.name == "delete_db": return ToolMessage("禁止操作")
    result = handler(request) # 真正执行tool
    print(f"[Middleware 后置] 返回结果：{result.content}")
    return result