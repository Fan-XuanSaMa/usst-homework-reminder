# -*- coding: utf-8 -*-
"""配置向导：账号密码与邮箱凭据都加密保存在项目目录之外。

用法：
    python config_tool.py            # 交互填写全部配置
    python config_tool.py --setup    # 同上
    python config_tool.py --show     # 查看当前配置（敏感项打码）
    python config_tool.py --reset    # 清除全部凭据
    python config_tool.py --import   # 从旧的 config.json 明文迁移（迁移后自动删除明文）

输密码时屏幕不显示，也不会进入命令行历史。
"""
import getpass
import json
import sys

import paths
import secrets_store as secrets


def ask(prompt, default="", secret=False, allow_empty=False):
    shown = f" [{default}]" if default and not secret else ""
    while True:
        if secret:
            val = getpass.getpass(prompt + shown + ": ").strip()
        else:
            val = input(prompt + shown + ": ").strip()
        if not val and default:
            return default
        if val or allow_empty:
            return val
        print("  不能为空，请重新输入")


def setup():
    paths.ensure()
    cur = secrets.load()
    print("== 账号（统一身份认证）==")
    user = ask("学号", cur.get("usst", {}).get("user", ""))
    pwd = ask("密码（输入时不显示）", secret=True)
    if not pwd:
        print("  密码不能为空，已取消。")
        return 1

    print("\n== 提醒邮件 ==")
    recipient = ask("收件邮箱", cur.get("recipient", ""))
    smtp_user = ask("发件邮箱", cur.get("smtp", {}).get("user", ""))
    auth_code = ask("SMTP 授权码（不是登录密码，输入时不显示）", secret=True)
    if not auth_code:
        print("  授权码不能为空，已取消。")
        return 1
    host = ask("SMTP 服务器", _guess_host(smtp_user))
    port = ask("SMTP 端口", "465")

    cfg = json.loads(paths.CONFIG.read_text(encoding="utf-8")) if paths.CONFIG.exists() else {}
    cfg.setdefault("check_interval_minutes", 15)
    cfg.setdefault("remind_days_before", 5)
    days = ask("提前几天开始提醒", str(cfg.get("remind_days_before", 5)))
    interval = ask("每隔几分钟检查一次", str(cfg.get("check_interval_minutes", 15)))
    cfg.update({"remind_days_before": float(days), "check_interval_minutes": int(interval)})
    cfg["smtp"] = {"host": host, "port": int(port)}
    paths.CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    secrets.update(
        usst={"user": user, "password": pwd},
        smtp={"user": smtp_user, "auth_code": auth_code},
        recipient=recipient,
    )
    print("\n已保存。配置目录（已限当前用户访问）：", paths.DATA_DIR)
    print("凭据文件已用 Windows DPAPI 加密，仅本机本账户可解密。")
    print("\n下一步：python remind.py --test-email 验证邮箱")
    return 0


def _guess_host(email):
    domain = (email.split("@")[-1] or "").lower()
    table = {
        "qq.com": "smtp.qq.com",
        "foxmail.com": "smtp.qq.com",
        "163.com": "smtp.163.com",
        "126.com": "smtp.126.com",
        "gmail.com": "smtp.gmail.com",
        "outlook.com": "smtp.office365.com",
        "hotmail.com": "smtp.office365.com",
    }
    return table.get(domain, f"smtp.{domain}" if domain else "smtp.qq.com")


def show():
    if not secrets.exists():
        print("尚未配置。运行 python config_tool.py --setup")
        return 0
    d = secrets.load()
    u = d.get("usst", {})
    s = d.get("smtp", {})
    print("配置目录：", paths.DATA_DIR)
    print("凭据文件：", paths.SECRETS, "（DPAPI 加密）")
    print("  学号    ：", secrets.mask(u.get("user", ""), 3))
    print("  密码    ：", secrets.mask(u.get("password", "")), f"（{len(u.get('password',''))} 位）")
    print("  收件邮箱：", secrets.mask_email(d.get("recipient", "")))
    print("  发件邮箱：", secrets.mask_email(s.get("user", "")))
    print("  授权码  ：", secrets.mask(s.get("auth_code", "")))
    if paths.CONFIG.exists():
        print("非敏感配置：", json.dumps(json.loads(paths.CONFIG.read_text(encoding="utf-8")), ensure_ascii=False))
    return 0


def reset():
    if paths.SECRETS.exists():
        paths.SECRETS.unlink()
    if paths.STATE.exists():
        paths.STATE.unlink()
    print("已清除凭据与登录状态。")
    return 0


def _placeholder(v):
    """识别配置模板里的占位文字，别把它们当成真凭据存下来。"""
    v = str(v or "").strip()
    if not v:
        return True
    if v.startswith("你的"):
        return True
    if "授权码" in v or "学号" in v and len(v) <= 6:
        return True
    if v.endswith("@example.com"):
        return True
    return False


def migrate():
    """把旧版项目目录里的明文 config.json 迁到加密存储，然后清除明文。"""
    old = paths.BASE / "config.json"
    if not old.exists():
        print("项目目录没有 config.json，无需迁移。")
        return 0
    d = json.loads(old.read_text(encoding="utf-8"))
    u, s = d.get("usst") or {}, d.get("smtp") or {}

    payload = {}
    if u.get("user") and u.get("password") and not _placeholder(u.get("user")) and not _placeholder(u.get("password")):
        payload["usst"] = {"user": u["user"], "password": u["password"]}
    if s.get("user") and s.get("auth_code") and not _placeholder(s.get("user")) and not _placeholder(s.get("auth_code")):
        payload["smtp"] = {"user": s["user"], "auth_code": s["auth_code"]}
    if d.get("recipient") and not _placeholder(d.get("recipient")):
        payload["recipient"] = d["recipient"]

    if payload:
        secrets.update(**payload)

    keep = {k: v for k, v in d.items() if k not in ("usst", "smtp", "recipient", "portal_base_url")}
    keep.setdefault("check_interval_minutes", 15)
    keep.setdefault("remind_days_before", 5)
    if s.get("host"):
        keep["smtp"] = {"host": s.get("host", "smtp.qq.com"), "port": s.get("port", 465)}
    # 写回时只保留非敏感配置；里面已没有任何账号密码
    paths.CONFIG.write_text(json.dumps(keep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 迁移其余个人数据到新位置（可能跨盘符，不能用 replace）
    import shutil
    moved = []
    for name, dest in [("browser_state.json", paths.STATE), ("_browser_raw.json", paths.RAW),
                       ("sent_log.json", paths.SENT_LOG), ("reminder.log", paths.LOG),
                       ("mute.txt", paths.MUTE_FILE)]:
        src = paths.BASE / name
        if src.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                if not dest.exists():
                    shutil.move(str(src), str(dest))
                else:
                    src.unlink()          # 目标已有，丢弃旧的
            except Exception as e:
                # 移动失败时至少先删除，避免明文继续留在项目里
                print(f"  警告：移动 {name} 失败（{e}），直接删除旧文件")
                src.unlink(missing_ok=True)
            moved.append(name)

    print("已写入加密凭据：", paths.SECRETS)
    print("已移动个人数据：", ", ".join(moved) if moved else "无")
    print("config.json 现在只含非敏感设置（提醒天数、检查间隔、SMTP 服务器）。")
    return 0


def main():
    args = sys.argv[1:]
    if "--show" in args:
        return show()
    if "--reset" in args:
        return reset()
    if "--import" in args:
        return migrate()
    return setup()


if __name__ == "__main__":
    sys.exit(main())
