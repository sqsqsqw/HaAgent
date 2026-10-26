import urllib.request, json

def get_public_ipv4() -> str:
    for url in ("https://ipinfo.io/ip", "http://ip.3322.net"):
        try:
            with urllib.request.urlopen(url, timeout=5) as f:
                ip = f.read().decode("utf-8").strip()
            if ip:
                return ip
        except Exception:
            continue
    return "获取失败"


def get_locate_by_ip(ip:str) -> dict:
        with urllib.request.urlopen(f"https://ipinfo.io/{ip}/json", timeout=5) as f:
            data = json.loads(f.read().decode("utf-8").strip())
        return {
            "ip": data.get("ip"),
            "城市": data.get("city"),
            "省份": data.get("region"),
            "国家": data.get("country"),
            "运营商": data.get("org", "").split(" ")[-1] if data.get("org") else ""
        }

