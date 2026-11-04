# -*- coding: utf-8 -*-
"""上理一网畅学作业提醒：策略判断 + 邮件发送。

策略（阈值可在 config.json 调整）：
- 未提交、距截止 ≤ remind_days_before 天（默认 5）：汇总进每日邮件；
- 每天最多 1 封提醒邮件，无论有几个作业、检查多少次；
- 已过截止的作业：不再提醒；
- 已提交的作业：不再提醒；
- 暂未设截止时间的新作业：第一次发现时发 1 封「新作业」通知。

静默名单：同目录 mute.txt，一行一条规则，空格分隔关键词全部命中（课程名+作业名）才静默。

单独运行：
    python remind.py              # 抓取 + 判断 + 发邮件
    python remind.py --dry-run    # 只抓取并打印会发什么，不发邮件
    python remind.py --test-email # 发一封测试邮件，验证 SMTP
"""
import json
import smtplib
import sys
import time
from datetime import datetime, timedelta
from email.header import Header
from email.message import EmailMessage

import paths
import secrets_store as secrets

BASE = paths.BASE
STATE_FILE = paths.SENT_LOG
MUTE_FILE = paths.MUTE_FILE

DEFAULT_CONFIG = {
    "remind_days_before": 5,
    "check_interval_minutes": 15,
    "smtp": {"host": "smtp.qq.com", "port": 465},
}


def load_config():
    """读取非敏感设置；全新克隆还没有 config.json 时用默认值。"""
    if not paths.CONFIG.exists():
        return dict(DEFAULT_CONFIG)
    try:
        cfg = json.loads(paths.CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    merged["smtp"] = {**DEFAULT_CONFIG["smtp"], **(cfg.get("smtp") or {})}
    return merged


CONFIG = load_config()

CST = timedelta(hours=8)


class NotConfigured(RuntimeError):
    """尚未完成账号/邮箱配置。属于正常状态，不触发故障告警。"""


def now():
    from tronclass import now as _n
    return _n()


# ---------- 工具 ----------

def fmt_left(delta):
    sec = int(delta.total_seconds())
    sign = "-" if sec < 0 else ""
    sec = abs(sec)
    days, rem = divmod(sec, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{sign}{days} 天 {hours} 小时"
    if hours:
        return f"{sign}{hours} 小时 {mins} 分钟"
    return f"{sign}{mins} 分钟"


def fmt_due(due):
    return due.strftime("%m月%d日 %H:%M")


def fmt_course(name):
    """去掉课程名后面的 (2026-2027-1)-xxxx 学号，邮件里更好看。"""
    import re
    return re.sub(r"\(\d{4}-\d{4}-\d\)\s*-\s*[\d-]+$", "", name).strip()


# ---------- 静默名单 ----------

def load_mutes():
    if not MUTE_FILE.exists():
        return []
    rules = []
    for line in MUTE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rules.append([t.lower() for t in line.split()])
    return rules


def is_muted(a, rules):
    key = f"{a['course']} {a['title']}".lower()
    return any(all(t in key for t in rule) for rule in rules)


# ---------- 状态 ----------

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state):
    paths.ensure()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def rec_for(state, a):
    return state.setdefault(
        str(a["id"]),
        {"dates": [], "final_dates": [], "announced": False},
    )


# ---------- 邮件 ----------

def send_email(subject, body, dry_run=False):
    smtp = CONFIG.get("smtp") or {}
    user = secrets.get("smtp.user")
    auth_code = secrets.get("smtp.auth_code")
    recipient = secrets.get("recipient")
    if not user or not auth_code or not recipient:
        raise NotConfigured("尚未保存邮箱配置")
    msg = EmailMessage()
    msg["From"] = f"{Header('上理作业提醒', 'utf-8').encode()} <{user}>"
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    if dry_run:
        print(f"[dry-run] 邮件 -> {recipient}\n  标题：{subject}\n{body}\n")
        return
    last_err = None
    for attempt in range(3):
        try:
            with smtplib.SMTP_SSL(smtp.get("host", "smtp.qq.com"), int(smtp.get("port", 465)), timeout=30) as s:
                s.login(user, auth_code)
                s.send_message(msg)
            return
        except (smtplib.SMTPException, ConnectionError, OSError) as e:
            last_err = e
            time.sleep(5 * (attempt + 1))
    raise last_err


# ---------- 主逻辑 ----------

def check(items=None, dry_run=False):
    if items is None:
        import tronclass
        try:
            items = tronclass.fetch()
        except tronclass.NotConfigured as e:
            raise NotConfigured(str(e)) from e

    mutes = load_mutes()
    active = [a for a in items if not is_muted(a, mutes)]
    t = now()
    today = t.date().isoformat()
    state = load_state()
    days_before = float(CONFIG.get("remind_days_before", 5))

    # 只关心两类作业：未提交、未过截止、且在提醒窗口内
    # 已提交的不提醒；已过截止的不提醒；暂未设截止时间的进「新作业」一栏。
    undated, pending_all = [], []
    for a in active:
        if a["submitted"]:
            rec_for(state, a)["done"] = True
            continue
        if a["due"] is None:
            if not rec_for(state, a).get("announced"):
                undated.append(a)
            continue
        remain = a["due"] - t
        a["remain"] = remain
        rec_for(state, a).pop("done", None)
        if remain.total_seconds() < 0:
            continue                         # 已过截止：不再提醒
        if remain <= timedelta(days=days_before):
            pending_all.append(a)            # N 天内：进每日汇总

    # 一组作业的大标题、分组标签（用于每日汇总）
    def flat(a):
        return (
            f"[{fmt_course(a['course'])}] {a['title']}\n"
            f"    截止：{fmt_due(a['due'])}（剩余 {fmt_left(a['due'] - t)}）\n"
            f"    {a['url']}"
        )

    def undated_line(a):
        return (
            f"[{fmt_course(a['course'])}] {a['title']}\n"
            f"    暂无截止时间（老师可能还未设置）\n"
            f"    {a['url']}"
        )

    # 每天最多 1 封：距上一封不足 24 小时就不发（新作业通知也并入，保证严格一封）
    last_sent = _parse_iso(state.get("_digest_sent_at"))
    due_now = last_sent is None or (t - last_sent) >= timedelta(hours=24)

    sent = 0
    if due_now:
        blocks, n = [], 0
        if pending_all:
            blocks.append("【即将截止】")            # 5 天内
            blocks.append("\n\n".join(flat(a) for a in sorted(pending_all, key=lambda x: x["due"])))
            n += len(pending_all)
        if undated:
            blocks.append("【新作业（暂无截止时间）】")
            blocks.append("\n\n".join(undated_line(a) for a in undated))
            n += len(undated)
        if blocks:
            send_email(
                f"[作业提醒] {len(pending_all)} 个作业即将截止" + (f"，{len(undated)} 个新作业" if undated else ""),
                "\n\n".join(blocks) + "\n\n—— 上理作业提醒（每天一封）\n",
                dry_run=dry_run,
            )
            for a in pending_all:
                rec_for(state, a)["dates"] = [today]
            for a in undated:
                rec_for(state, a)["announced"] = True
            state["_digest_sent_at"] = t.isoformat()
            sent = 1

    if not dry_run:
        save_state(state)

    summary = (
        f"{t:%Y-%m-%d %H:%M} 检查完成：共 {len(items)} 个作业，未提交 "
        f"{sum(1 for a in active if not a['submitted'])} 个"
        f"（{days_before:g} 天内 {len(pending_all)}，无截止 {len(undated)}），"
        f"静默 {len(items) - len(active)} 个，"
        + (f"发送 {sent} 封" if due_now else "距上次提醒不足 24 小时，今天不再发送")
    )
    return summary, sent


def send_failure_alert(detail, dry_run=False):
    """抓取/登录失败告警：每天最多一封。"""
    state = load_state()
    rec = state.setdefault("_alert", {"dates": []})
    today = now().date().isoformat()
    if today in rec["dates"]:
        return False
    send_email(
        "[上理作业提醒] 系统故障：登录或抓取失败",
        (
            f"{now():%Y-%m-%d %H:%M} {detail}\n\n"
            "在恢复前不会收到作业提醒。\n"
            "常见原因：统一身份认证密码修改、http://1906.usst.edu.cn 改版、需要验证码。\n"
            "可手动运行 python tronclass.py 查看具体报错。\n"
        ),
        dry_run=dry_run,
    )
    rec["dates"].append(today)
    if not dry_run:
        save_state(state)
    return True


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    if "--test-email" in args:
        try:
            send_email(
                "[上理作业提醒] 配置测试邮件",
                f"这是一封测试邮件（{now():%Y-%m-%d %H:%M}）。收到说明 SMTP 配置正确。\n",
                dry_run=dry,
            )
        except Exception as e:
            print("测试邮件发送失败:", e)
            return 1
        if not dry:
            print("测试邮件已发送到", secrets.get("recipient"))
        return 0

    try:
        summary, _ = check(dry_run=dry)
        print(summary)
        return 0
    except Exception as e:
        # 未配置属于正常状态，不算故障，不触发告警
        if isinstance(e, NotConfigured):
            print(f"{e}\n运行：python config_tool.py --setup")
            return 2
        msg = f"{type(e).__name__}: {e}"
        print("失败:", msg)
        try:
            send_failure_alert(msg, dry_run=dry)
        except Exception as e2:
            print("（告警邮件未发送：", e2, "）")
        return 1


if __name__ == "__main__":
    sys.exit(main())
