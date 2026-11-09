import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 本机实测可用的本地代理（v2rayN）。墙外源用它。
DEFAULT_PROXY = os.environ.get("COLLECTOR_PROXY", "socks5h://127.0.0.1:10808")


def session(use_proxy: bool = False) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    retry = Retry(
        total=2,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    if use_proxy:
        s.proxies = {"http": DEFAULT_PROXY, "https": DEFAULT_PROXY}
    return s


def get_json(url: str, *, use_proxy: bool = False, timeout: int = 15, **kw):
    with session(use_proxy) as s:
        r = s.get(url, timeout=timeout, **kw)
        r.raise_for_status()
        return r.json()


def get_text(url: str, *, use_proxy: bool = False, timeout: int = 15, **kw) -> str:
    with session(use_proxy) as s:
        r = s.get(url, timeout=timeout, **kw)
        r.raise_for_status()
        r.encoding = r.encoding or "utf-8"
        return r.text
