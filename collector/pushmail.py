"""把日报推到邮箱：QQ 邮箱 SMTP（需要"授权码"，不是 QQ 密码）。

配置在 config/mail.yaml；auth_code 留空则静默跳过，不影响采集。
watchdog 每 6 小时跑一次，默认靠 data/mail-state.json 去重，每天只发第一轮。
"""

from __future__ import annotations

import json
import smtplib
import ssl
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

import yaml

from . import digest as digest_mod

CONFIG_PATH = Path(__file__).parent.parent / "config" / "mail.yaml"
SECRETS_PATH = Path(__file__).parent.parent / "config" / "secrets.yaml"
STATE_PATH = Path(__file__).parent.parent / "data" / "mail-state.json"


def _secret_password() -> str:
    try:
        return str((yaml.safe_load(SECRETS_PATH.read_text(encoding="utf-8")) or {}).get("mail_password") or "")
    except Exception:
        return ""

DEFAULTS = {
    "smtp_host": "smtp.qq.com",
    "smtp_port": 465,
    "user": "",
    "auth_code": "",
    "to": [],
    "daily": True,
}


def _conf() -> dict:
    conf = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            conf.update({k: v for k, v in data.items() if v not in (None, "")})
        except Exception:
            pass  # 配置坏了等同未配置，静默跳过
    to = conf.get("to")
    conf["to"] = [to] if isinstance(to, str) else list(to or [])
    if not conf.get("auth_code"):
        conf["auth_code"] = _secret_password()
    return conf


def _already_sent(today: str) -> bool:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8")).get("last_sent") == today
    except Exception:
        return False


def _mark_sent(today: str) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"last_sent": today}, ensure_ascii=False), encoding="utf-8"
    )


def _ai_from_md(md: str) -> str | None:
    """从日报 MD 里取回 AI 导读正文（build() 时生成，这里不重复调 LLM）。"""
    if "## AI 导读" not in md:
        return None
    seg = md.split("## AI 导读", 1)[1].split("\n## ", 1)[0].strip()
    return seg or None


def _set_from(msg, conf: dict) -> None:
    name = str(conf.get("from_name") or "").strip()
    msg["From"] = formataddr((name, conf["user"])) if name else conf["user"]
    reply_to = str(conf.get("reply_to") or "").strip()
    if reply_to:
        msg["Reply-To"] = reply_to


def _deliver(conf: dict, to: list[str], msg) -> str:
    """用主配置发送；认证/连接失败时自动退回 fallback。返回实际发件账号。"""
    ctx = ssl.create_default_context()

    def _try(c: dict) -> None:
        mode = c.get("smtp_mode") or ("ssl" if int(c["smtp_port"]) == 465 else "starttls")
        if mode == "ssl":
            s = smtplib.SMTP_SSL(c["smtp_host"], int(c["smtp_port"]), context=ctx, timeout=30)
        else:
            s = smtplib.SMTP(c["smtp_host"], int(c["smtp_port"]), timeout=30)
            s.starttls(context=ctx)
        with s:
            s.login(c["user"], c["auth_code"])
            s.sendmail(c["user"], to, msg.as_string())

    try:
        _try(conf)
        return conf["user"]
    except Exception as e:
        fb = conf.get("fallback") or {}
        if not (fb.get("user") and fb.get("auth_code")):
            raise
        print(f"  [mail] 主发件失败（{type(e).__name__}: {e}），改用备用 {fb['user']}")
        try:
            del msg["From"]
            del msg["Reply-To"]
        except Exception:
            pass
        msg["From"] = fb["user"]
        _try({**conf, **fb})
        return fb["user"]


def send_text(subject: str, body: str, to: list[str] | None = None) -> str:
    """发一封纯文本邮件（告警用）。复用同一套 SMTP 配置，不去重、不阻塞调用方。

    返回状态字符串；未配置时返回 `mail-not-configured` 而不是抛异常 ——
    告警发不出去，不该让整轮采集失败。
    """
    conf = _conf()
    if not conf.get("auth_code") or not conf.get("user"):
        return "mail-not-configured"
    recipients = [str(x) for x in (to or conf.get("to") or []) if str(x).strip()]
    if not recipients:
        return "mail-no-recipient"

    msg = MIMEMultipart()
    msg["Subject"] = Header(subject, "utf-8")
    _set_from(msg, conf)
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        who = _deliver(conf, recipients, msg)
        return f"mail-sent({who})"
    except Exception as e:
        return f"mail-failed: {type(e).__name__}: {e}"


def send(digest_path: Path, stats: dict, payload: dict | None = None,
         force: bool = False, lmarena: dict | None = None,
         aa: dict | None = None) -> str:
    """发送日报，返回状态描述（run.py 打印用）。任何异常由调用方兜底。

    payload 给了就发 HTML 版（浅色卡片排版），纯文本版作为备选一同附上；
    force=True 用于测试重发，绕过"每天一封"去重。
    """
    conf = _conf()
    if not (conf["user"] and conf["auth_code"]):
        fb = conf.get("fallback") or {}
        if fb.get("user") and fb.get("auth_code"):
            conf = {**conf, "user": fb["user"], "auth_code": fb["auth_code"],
                    "smtp_host": fb["smtp_host"], "smtp_port": fb["smtp_port"], "fallback": None}
        else:
            return "未配置（auth_code 留空），跳过"
    to = conf["to"] or [conf["user"]]
    today = datetime.now().strftime("%Y-%m-%d")
    after_hour = int(conf.get("send_after_hour") or 0)
    if after_hour and datetime.now().hour < after_hour and not force:
        return f"未到 {after_hour}:00，本轮只采集不发信"
    if conf["daily"] and not force and _already_sent(today):
        return "今天已发过，跳过"

    md = digest_path.read_text(encoding="utf-8")
    if payload:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(md, "plain", "utf-8"))
        msg.attach(
            MIMEText(
                digest_mod.email_html(payload, _ai_from_md(md), lmarena, aa), "html", "utf-8"
            )
        )
    else:
        msg = MIMEText(md, "plain", "utf-8")
    msg["Subject"] = Header(f"情报日报 {today} · {stats.get('raw', 0)} 条", "utf-8")
    _set_from(msg, conf)
    msg["To"] = ", ".join(to)

    ctx = ssl.create_default_context()
    sender = _deliver(conf, to, msg)
    if not force:
        _mark_sent(today)
    return f"已发送给 {', '.join(to)}（{sender} 发出）"


def send_custom(subject: str, text: str, html: str | None = None) -> str:
    """发送任意内容（如 arXiv 周报），不做"每天一封"去重。"""
    conf = _conf()
    if not (conf["user"] and conf["auth_code"]):
        fb = conf.get("fallback") or {}
        if fb.get("user") and fb.get("auth_code"):
            conf = {**conf, "user": fb["user"], "auth_code": fb["auth_code"],
                    "smtp_host": fb["smtp_host"], "smtp_port": fb["smtp_port"], "fallback": None}
        else:
            return "未配置（auth_code 留空），跳过"
    to = conf["to"] or [conf["user"]]
    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    _set_from(msg, conf)
    msg["To"] = ", ".join(to)

    ctx = ssl.create_default_context()
    sender = _deliver(conf, to, msg)
    return f"已发送给 {', '.join(to)}（{sender} 发出）"
