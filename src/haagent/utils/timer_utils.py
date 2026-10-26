import time
from datetime import datetime
from functools import wraps

def humanize_duration(seconds: float) -> str:
    """把秒数转成人话"""
    if seconds < 0.001:
        return f"{seconds*1_000_000:.0f} 微秒"
    if seconds < 1:
        return f"{seconds*1000:.0f} 毫秒"
    if seconds < 60:
        return f"{seconds:.2f} 秒"
    return f"{seconds/60:.1f} 分钟"

def timer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        start_str = datetime.now().strftime("%H:%M:%S")
        # print(f"▶ {func.__name__} 开始：{start_str}")

        result = func(*args, **kwargs)

        elapsed = time.perf_counter() - t0
        end_str = datetime.now().strftime("%H:%M:%S")
        # print(f"⏹ {func.__name__} 结束：{end_str}，耗时 {humanize_duration(elapsed)}")
        print(f"    ⏹ 耗时 {humanize_duration(elapsed)}")
        return result
    return wrapper
