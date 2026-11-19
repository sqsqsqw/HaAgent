from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, AIMessageChunk, ToolMessage, AIMessage
from langchain_ollama import ChatOllama

from haagent.tools import TOOLS


class ChatModel():

    def __init__(self):
        print("build agent")
        init_model = ChatOllama(
            model="qwen3.5:4b",
            temperature=0.7,

        )
        self.model = init_model.bind_tools(TOOLS)

        # self.model = create_agent(
        #     model="ollama:qwen3.5:4b",
        #     tools=TOOLS,
        #     middleware=[
        #         SummarizationMiddleware(
        #             model="ollama:qwen3.5:4b",
        #             max_tokens_before_summary=4000,
        #             messages_to_keep=20,
        #             summary_prompt="请你总结一下对话历史都说了什么，同时摘出重要的信息，提供后续对话参考",
        #         ),
        #     ],
        # )

        self.tool_map = {t.name: t for t in TOOLS}

    def get_model(self):
        return self.model


    def get_system_prompt(self):
        return SystemMessage("你是一个Agent,在保证不触犯中国法律,且保证操作安全的情况下,需要完成用户的各种需求")



class ChatContext():
    def __init__(self):
        self.messages = None

    def sask(self, question:str, model:ChatModel):
        if self.messages is None:
            self.messages: list[BaseMessage] = [model.get_system_prompt()]

        # 使用压缩管理器添加消息
        msg = HumanMessage(content=question)
        self.context_manager.add_message(msg)
        print("AI:")

        while True:
            accumulated_chunk: AIMessageChunk | None = None
            for chunk in model.get_model().stream(self.messages):
                if accumulated_chunk is None:
                    accumulated_chunk = chunk
                else:
                    accumulated_chunk += chunk
                print(chunk.content, end="", flush=True)

            print()
            if accumulated_chunk is None:
                break

            accumulated_chunk.init_tool_calls()
            full_msg = accumulated_chunk

            # 如果有工具调用，执行工具，追加ToolMessage，循环继续
            if full_msg.tool_calls:
                for tool_call in full_msg.tool_calls:
                    tool_name = tool_call["name"]
                    args = tool_call["args"]
                    # 分发执行工具
                    tool_obj = model.tool_map.get(tool_call["name"])
                    if tool_obj is not None:
                        res = tool_obj.invoke(tool_call["args"])
                    else:
                        res = f"错误：不存在工具 {tool_call['name']}"
                    # 工具结果入消息
                    self.messages.append(ToolMessage(
                        content=res,
                        tool_call_id=tool_call["id"]
                    ))
                # 继续while循环，再次调用LLM，拿到工具结果后的回答
                continue
            else:
                # 没有工具调用，本轮结束
                # self.messages.append(AIMessage(
                #     content=full_msg
                # ))
                print()
                break


class ChatAgent():
    def __init__(self):
        self.model = ChatModel()
        self.context = ChatContext()

    def speak(self, question:str):
        self.context.sask(question, self.model)


__all__ = ["ChatAgent"]