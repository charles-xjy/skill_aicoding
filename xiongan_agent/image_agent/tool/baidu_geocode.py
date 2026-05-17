import os
import requests
from langchain_core.tools import tool

# 不走代理，直连国内 API
_NO_PROXY = {"http": None, "https": None}


def _baidu_geocode(address: str, city: str = "") -> dict | None:
    ak = os.getenv("BAIDU_MAP_AK")
    if not ak:
        return None
    params = {"address": address, "output": "json", "ak": ak}
    if city:
        params["city"] = city
    try:
        resp = requests.get(
            "https://api.map.baidu.com/geocoding/v3/",
            params=params,
            proxies=_NO_PROXY,
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == 0:
            loc = data["result"]["location"]
            return {"lng": loc["lng"], "lat": loc["lat"], "source": "baidu"}
    except Exception:
        pass
    return None


def _gaode_geocode(address: str, city: str = "") -> dict | None:
    ak = os.getenv("GAODE_API_KEY")
    if not ak:
        return None
    params = {"address": address, "output": "json", "key": ak}
    if city:
        params["city"] = city
    try:
        resp = requests.get(
            "https://restapi.amap.com/v3/geocode/geo",
            params=params,
            proxies=_NO_PROXY,
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            lng, lat = data["geocodes"][0]["location"].split(",")
            return {"lng": float(lng), "lat": float(lat), "source": "gaode"}
    except Exception:
        pass
    return None


@tool
def baidu_geocode(address: str, city: str = "") -> dict:
    """
    将地址/地名转换为经纬度坐标。优先使用百度地图，失败时自动切换高德地图。

    参数:
    - address: 要查询的地址或地名，如"北京交通大学"、"雄安新区"
    - city: 可选，限定城市，如"北京市"，可提高精度

    返回:
    - {"lng": 经度, "lat": 纬度, "source": "baidu"|"gaode"} 或 {"error": 错误信息}
    """
    result = _baidu_geocode(address, city)
    if result:
        return result

    result = _gaode_geocode(address, city)
    if result:
        return result

    return {"error": f"百度和高德均无法解析地址：{address}"}
