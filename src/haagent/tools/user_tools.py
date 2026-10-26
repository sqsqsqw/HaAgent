
from langchain.tools import tool

from haagent.utils import ip_utils
from datetime import datetime
import time

from haagent.utils.timer_utils import timer


@tool
@timer
def get_weather(city: str) -> str:
    """获取指定城市的天气。"""
    print(f"🌤  开始调用天气查询: {city} 总是阳光明媚！", end="")
    return f"{city} 总是阳光明媚！"

@tool
@timer
def get_location() -> str:
    """获取用户当前的定位城市"""
    print("📍  开始调用定位:", end="")

    ip = ip_utils.get_public_ipv4()
    locate = ip_utils.get_locate_by_ip(ip)

    print(f"{locate["城市"]}.{locate["省份"]}" , end="")

    return locate

@tool
@timer
def get_full_local_time() -> dict:
    """获取用户当前默认时区的所有时间信息"""
    print("⏱️  开始获取当前时间", end="")
    now = datetime.now()                     # 系统默认时区的当前时间
    tz_name = time.tzname[time.daylight]     # 时区名（如 '中国标准时间' / 'CST'）
    utc_offset = time.timezone / 3600        # 本地与UTC的时差（小时，正负注意）
    if time.daylight:
        utc_offset = time.altzone / 3600

    return {
        # 基础字段
        "年": now.year,
        "月": now.month,
        "日": now.day,
        "时": now.hour,
        "分": now.minute,
        "秒": now.second,
        "微秒": now.microsecond,
        # 组合格式
        "完整时间": now.strftime("%Y-%m-%d %H:%M:%S"),
        "日期": now.strftime("%Y-%m-%d"),
        "时间": now.strftime("%H:%M:%S"),
        # 星期/周期信息
        "星期": now.strftime("%A"),          # Friday（英文）
        "星期数字": now.weekday() + 1,       # 1=周一 ... 7=周日
        "一年第几天": now.timetuple().tm_yday,
        "一年第几周(ISO)": now.isocalendar()[1],
        # 时区信息
        "时区名": tz_name,
        "UTC偏移小时": utc_offset,
        "是否夏令时": bool(time.daylight),
        # 时间戳
        "时间戳(秒)": int(now.timestamp()),
        "时间戳(毫秒)": int(now.timestamp() * 1000),
    }


user_tools = [get_weather, get_location, get_full_local_time]