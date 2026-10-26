import inspect
from typing import Callable, Any
from functools import wraps

import click


def agent_prompt(
    template: str,
    callback: Callable[[dict[str, Any]], str] | None = None
):
    def decorator(func: Callable):
        sig = inspect.signature(func)

        @wraps(func)
        def wrapper(*args, **kwargs):
            # 把 args + kwargs 合并成完整参数字典
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            ctx = dict(bound.arguments)

            # 渲染提示文本：优先回调，否则模板format
            if callback is not None:
                prompt_text = callback(ctx)
            else:
                prompt_text = template.format(**ctx)

            if click.confirm(f"⚠ {prompt_text}，是否继续执行高危操作？（同意y/拒绝N）", default=False):
                click.echo("✅ 已同意")
                return func(*args, **kwargs)
            else:
                click.echo("❌ 已拒绝")
                return None

        return wrapper
    return decorator