"""上下文压缩工具：处理对话历史的 Token 管理和摘要。

核心思想：
- 定期使用 SummarizationMiddleware 总结旧对话
- 保留最近的关键消息
- 避免上下文无限增长导致 Token 耗尽
"""

from __future__ import annotations

from typing import Callable, Any
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain.agents.middleware import SummarizationMiddleware
import tiktoken

# ============================================================================
# 配置参数
# ============================================================================
CONTEXT_CONFIG = {
    "max_messages": 20,              # 最大消息数（硬限制）
    "summary_tokens_threshold": 2000,  # 触发摘要的 token 阈值
    "messages_to_keep": 10,          # 保留最近消息数
    "summary_interval": 5,            # 每次对话后摘要间隔
}

# ============================================================================
# Token 计数器（使用 tiktoken 估算）
# ============================================================================
try:
    TOKENIZER = tiktoken.encoding_for_model("qwen2.5")
except tkintoken.EncodingNotFoundError:
    try:
        TOKENIZER = tiktoken.get_encoding("cl100k_base")  # 备用编码
    except Exception:
        TOKENIZER = None


def estimate_tokens(text: str) -> int:
    """估算文本的 Token 数量。"""
    if not text or not TOKENIZER:
        return 0
    tokens = TOKENIZER.encode(text)
    return len(tokens)


def estimate_message_tokens(message: BaseMessage) -> int:
    """估算单条消息的 Token 数量。"""
    content = str(message.content)
    return estimate_tokens(content)


def compress_messages(
    messages: list[BaseMessage],
    max_tokens: int = 3000,
    summary_model: str = "qwen3.5:4b"
) -> list[BaseMessage]:
    """
    压缩消息列表，移除或摘要旧消息。

    策略：
    1. 计算当前 token 估计
    2. 如果超过阈值，从开头移除旧消息
    3. 对剩余旧消息进行摘要
    4. 保留最近的关键消息

    Args:
        messages: 原始消息列表
        max_tokens: 最大 Token 限制
        summary_model: 用于摘要的模型名称

    Returns:
        压缩后的消息列表
    """
    if not messages:
        return []

    # 计算总 token
    total_tokens = sum(estimate_message_tokens(m) for m in messages)
    
    # 如果未超限，直接返回
    if total_tokens <= max_tokens:
        return messages[:]

    # 策略 1：移除最早的消息直到接近阈值
    compressed = []
    remaining_tokens = total_tokens
    
    for msg in reversed(messages):
        msg_tokens = estimate_message_tokens(msg)
        if remaining_tokens - msg_tokens >= max_tokens * 0.8:
            compressed.insert(0, msg)
            remaining_tokens -= msg_tokens
        else:
            break

    # 策略 2：对早期消息进行摘要压缩
    if len(compressed) < len(messages) and total_tokens > max_tokens:
        early_messages = messages[:len(messages) - len(compressed)]
        
        if early_messages:
            # 创建临时模型用于摘要
            try:
                summary_llm = ChatOllama(model=summary_model, temperature=0.1)
                
                # 构建摘要提示
                summary_prompt = f"""请总结以下对话历史的关键信息：

{chr(10).join(f'- {str(m)}' for m in early_messages)}

要求：
1. 提取关键问题和决策点
2. 忽略无关细节和重复内容
3. 保持上下文连贯性
4. 输出格式为 JSON: {{"summary": "...", "key_points": [...]}}"""
                
                # 调用摘要
                summary_result = summary_llm.invoke(summary_prompt)
                summary_text = str(summary_result.content[:500])  # 限制长度
                
                # 添加摘要消息到开头
                if "JSON" in summary_text:
                    import json
                    try:
                        data = json.loads(summary_text)
                        summary_msg = SystemMessage(content=f"{data.get('summary', '')}\n关键要点：{', '.join(data.get('key_points', []))}")
                    except json.JSONDecodeError:
                        summary_msg = SystemMessage(content=summary_text)
                else:
                    summary_msg = SystemMessage(content=summary_text)
                
                compressed.insert(0, summary_msg)

            except Exception as e:
                # 摘要失败降级：直接删除早期消息
                print(f"⚠️  摘要失败，执行降级策略：{e}")
    
    return compressed


class CompressedContextManager:
    """上下文管理器：自动压缩对话历史。

    功能：
    - 添加消息时自动检查 Token 并压缩
    - 定期触发摘要（可配置）
    - 硬限制最大消息数
    """

    def __init__(self, max_messages: int = None, summary_interval: int = None):
        """初始化。

        Args:
            max_messages: 最大消息数（None 表示不强制限制，但会压缩）
            summary_interval: 每次对话后摘要间隔轮数
        """
        if max_messages is not None:
            CONTEXT_CONFIG["max_messages"] = max_messages
        
        self.max_messages = max_messages or CONTEXT_CONFIG["max_messages"]
        self.summary_interval = summary_interval or CONTEXT_CONFIG["summary_interval"]
        self.messages: list[BaseMessage] = []
        self.conversation_count = 0

    def add_message(self, message: BaseMessage) -> bool:
        """添加消息，自动压缩。

        Args:
            message: 要添加的消息

        Returns:
            是否成功添加（False 表示被截断）
        """
        # 检查硬限制
        if len(self.messages) >= self.max_messages and len(self.messages) > 10:
            # 触发摘要逻辑
            self._apply_summary()
        
        self.messages.append(message)
        return True

    def _apply_summary(self):
        """应用摘要压缩。"""
        # 使用内置的 SummarizationMiddleware（如果可用）
        try:
            from langchain.agents import initialize_agent
            tools = []  # 不需要工具
            
            # 创建临时摘要模型
            summary_llm = ChatOllama(
                model="qwen3.5:4b",
                temperature=0.1,
                max_tokens=500
            )
            
            # 使用 SummarizationMiddleware
            middleware = SummarizationMiddleware(
                model=summary_llm,
                max_tokens_before_summary=2000,
                messages_to_keep=10,
                summary_prompt=f"""请你总结这段对话历史：

{chr(10).join(f'- {str(m)}' for m in self.messages[:5])}

提取关键问题和决策点，忽略无关细节。
输出格式为 JSON: {{"summary": "...", "key_points": [...]}}"""
            )
            
            # 临时使用 middleware（简化版）
            summary_result = summary_llm.invoke(
                f"请总结以下对话：{chr(10).join(str(m) for m in self.messages)}"
            )
            summary_text = str(summary_result.content[:500])
            
            # 创建摘要消息
            import json
            try:
                data = json.loads(summary_text)
                summary_msg = SystemMessage(content=f"{data.get('summary', '')}\n关键要点：{', '.join(data.get('key_points', []))}")
            except:
                summary_msg = SystemMessage(content=summary_text)
            
            # 替换早期消息为摘要
            self.messages = [summary_msg] + self.messages[10:]

        except Exception as e:
            print(f"⚠️  摘要失败，执行降级策略：{e}")
            # 降级：直接删除旧消息
            if len(self.messages) > 10:
                self.messages = self.messages[-10:]

    def get_messages(self) -> list[BaseMessage]:
        """获取当前消息列表（已压缩）。"""
        return self.messages[:]

    def clear(self):
        """清空所有历史。"""
        self.messages = []


def create_summarization_middleware(
    model: str = "qwen3.5:4b",
    max_tokens_before_summary: int = 2000,
    messages_to_keep: int = 10
) -> SummarizationMiddleware:
    """创建摘要中间件实例。

    Args:
        model: 用于摘要的模型名称
        max_tokens_before_summary: 超过此 token 数触发摘要
        messages_to_keep: 保留最近的消息数

    Returns:
        SummarizationMiddleware 实例
    """
    return SummarizationMiddleware(
        model=model,
        max_tokens_before_summary=max_tokens_before_summary,
        messages_to_keep=messages_to_keep,
        summary_prompt="""请你总结这段对话历史：
- 提取关键问题和决策点
- 忽略无关细节
- 保持上下文连贯性

输出格式为 JSON: {{"summary": "...", "key_points": [...]}}"""
    )


# ============================================================================
# 测试示例
# ============================================================================
if __name__ == "__main__":
    # 简单测试
    from langchain_core.messages import HumanMessage, SystemMessage
    
    messages = [
        SystemMessage(content="你是一个助手"),
        HumanMessage(content="你好"),
        HumanMessage(content="帮我写个 Python 脚本"),
        HumanMessage(content="好的，我需要什么功能？"),
        HumanMessage(content="需要读取文件、执行命令"),
    ]
    
    compressed = compress_messages(messages, max_tokens=100)
    print(f"原始：{len(messages)} 条消息")
    print(f"压缩后：{len(compressed)} 条消息")
    for i, m in enumerate(compressed):
        print(f"{i}: {type(m).__name__} - {str(m)[:50]}")
