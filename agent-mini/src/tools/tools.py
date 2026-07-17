from typing import Any

from .registry import tool


@tool
def get_weather(city: str) -> dict[str, Any]:
    """查询指定城市今天的本地 mock 天气，不访问真实天气 API。

    Args:
        city: 城市名称，例如北京、上海、深圳。
    """
    fake_weather = {
        "北京": {"temperature": 26, "condition": "晴"},
        "上海": {"temperature": 24, "condition": "多云"},
        "深圳": {"temperature": 28, "condition": "小雨"},
    }
    return {
        "city": city,
        **fake_weather.get(city, {"temperature": 25, "condition": "未知"}),
        "source": "local-mock",
    }


__all__ = ["get_weather"]
