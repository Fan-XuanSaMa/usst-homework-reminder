# -*- coding: utf-8 -*-
"""配置工具：账号和邮箱分开配置，互不干扰。

用法：
    python config_tool.py --account        # 只配作业平台账号（学号 + 密码）
    python config_tool.py --email          # 只配提醒邮箱（发件邮箱 + 授权码）
    python config_tool.py                  # 哪项没配就问哪项
    python config_tool.py --show           # 查看当前配置（敏感项打码）
    python config_tool.py --reset          # 清除全部凭据与登录状态
    python config_tool.py --reset-account  # 只清账号
    python config_tool.py --reset-email    # 只清邮箱
    python config_tool.py --import         # 从旧版明文 config.json 迁移

所有提示都可以直接回车跳过；输密码时屏幕不显示，也不会进入命令行历史。
"""
import getpass
import json
import sys

import paths
import platforms
import secrets_store as secrets


# ---------- 输入 ----------

def ask(prompt, default="", secret=False, allow_empty=False):
    shown = f" [{default}]" if default and not secret else ""
    while True:
        try:
            if secret:
                val = getpass.getpass(prompt + shown + ": ").strip()
            else:
                val = input(prompt + shown + ": ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消，未做任何修改。")
            return None
        if not val and default:
            return default
        if val or allow_empty:
            return val
        print("  不能为空，请重新输入（Ctrl+C 退出）")


# ---------- 账号 ----------

def _platform_menu():
    """返回可用平台；只有一个时直接用它。"""
    mods = [m for m in platforms.enabled() if getattr(m, "CREDS", None)]
    if not mods:
        print("没有可用的作业平台模块。")
        return None
    if len(mods) == 1:
        return mods[0]
    print("选择要配置的作业平台：")
    for i, m in enumerate(mods, 1):
        print(f"  {i}. {m.NAME}（{getattr(m, 'HOME', '')}）")
    while True:
        raw = ask("序号", "1")
        if raw is None:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(mods):
            return mods[int(raw) - 1]
        print("  请输入列表中的序号")


def setup_account():
    mod = _platform_menu()
    if mod is None:
        return 1
    key, name = mod.KEY, mod.NAME
    cur = secrets.account(key) or {}
    print(f"== {name} 账号 ==")
    answers = {}
    for field, label, is_secret in mod.CREDS:
        old = cur.get(field, "")
        # 非敏感字段（学号）把旧值当默认值显示；密码不回显旧值
        default = old if (old and not is_secret) else ""
        hint = "（输入时不显示，直接回车保留原值）" if (is_secret and old) else (
            "（输入时不显示）" if is_secret else "")
        val = ask(label + hint, default, secret=is_secret, allow_empty=bool(old and is_secret))
        if val is None:
            return 1
        answers[field] = val or old
    missing = [label for field, label, _ in mod.CREDS if not answers.get(field)]
    if missing:
        print("  缺少：" + "、".join(missing) + "，已取消。")
        return 1

    secrets.save_account(key, **answers)
    print(f"\n已保存到 {paths.SECRETS}（DPAPI 加密，仅本机本账户可解密）")
    print(f"下一步：python {mod.__name__}.py 验证能否登录并抓到作业")
    return 0


# ---------- 邮箱 ----------

def setup_email():
    cur = secrets.load().get("email") or {}
    print("== 提醒邮箱 ==")
    print("提示：QQ/163 等邮箱需要在网页版开启 SMTP 服务后获取「授权码」，不是登录密码。")
    sender = ask("发件邮箱", cur.get("sender", ""))
    if sender is None:
        return 1
    if not sender:
        print("  发件邮箱不能为空，已取消。")
        return 1

    old_code = cur.get("auth_code", "")
    auth_code = ask(
        "授权码（输入时不显示" + ("，直接回车保留原值" if old_code else "") + "）",
        secret=True, allow_empty=bool(old_code),
    )
    if auth_code is None:
        return 1
    auth_code = auth_code or old_code
    if not auth_code:
        print("  授权码不能为空，已取消。")
        return 1

    recipient = ask("收件邮箱（回车 = 同上，填自己即可）", cur.get("recipient", "") or sender)
    if recipient is None:
        return 1

    host = cur.get("host") or guess_host(sender)
    port = int(cur.get("port") or 465)
    secrets.save_email(sender, auth_code, recipient, host, port)
    print(f"\n已保存。服务器自动识别为 {host}:{port}，收件邮箱 {recipient}（均已打码显示于 --show）")
    print("下一步：python remind.py --test-email 验证能否发信")
    return 0


def guess_host(address):
    domain = (address.split("@")[-1] or "").lower()
    table = {
        "qq.com": "smtp.qq.com",
        "foxmail.com": "smtp.qq.com",
        "163.com": "smtp.163.com",
        "126.com": "smtp.126.com",
        "yeah.net": "smtp.yeah.net",
        "gmail.com": "smtp.gmail.com",
        "outlook.com": "smtp.office365.com",
        "hotmail.com": "smtp.office365.com",
        "usst.edu.cn": "smtp.office365.com",
    }
    return table.get(domain, f"smtp.{domain}" if domain else "smtp.qq.com")


# ---------- 查看 / 清除 ----------

def _status():
    """返回 (缺少的项列表, 是否全部就绪)。"""
    missing = []
    for m in platforms.enabled():
        if not secrets.account(m.KEY):
            missing.append(f"{m.NAME}账号")
    if not secrets.email_config():
        missing.append("提醒邮箱")
    return missing


def show():
    d = secrets.load()
    print("配置目录：", paths.DATA_DIR)
    print("凭据文件：", paths.SECRETS, "（DPAPI 加密）")
    print()
    print("== 作业平台账号 ==")
    mods = platforms.enabled()
    any_acct = False
    for m in mods:
        a = (d.get("accounts") or {}).get(m.KEY) or {}
        if a.get("user"):
            any_acct = True
            print(f"  {m.NAME:6s}：{secrets.mask(a.get('user', ''), 3)}"
                  f"  密码 {secrets.mask(a.get('password', ''))}（{len(a.get('password', ''))} 位）")
        else:
            print(f"  {m.NAME:6s}：未配置")
    if not mods:
        print("  （无可用平台）")
    print()
    print("== 提醒邮箱 ==")
    e = d.get("email") or {}
    if e.get("sender"):
        print("  发件邮箱：", secrets.mask_email(e.get("sender", "")))
        print("  收件邮箱：", secrets.mask_email(e.get("recipient", "") or e.get("sender", "")))
        print("  授权码  ：", secrets.mask(e.get("auth_code", "")))
        print("  服务器  ：", e.get("host", ""), e.get("port", ""))
    else:
        print("  未配置")
    print()
    if paths.CONFIG.exists():
        try:
            cfg = json.loads(paths.CONFIG.read_text(encoding="utf-8"))
            print("非敏感配置：", json.dumps(cfg, ensure_ascii=False))
        except Exception:
            pass
    missing = _status()
    if missing:
        print()
        print("尚未完成：" + "、".join(missing))
    return 0


def _clear_common():
    if paths.STATE.exists():
        paths.STATE.unlink()


def reset():
    paths.SECRETS.unlink(missing_ok=True)
    _clear_common()
    print("已清除全部凭据与登录状态。")
    return 0


def reset_account():
    d = secrets.load()
    if d.get("accounts"):
        d["accounts"] = {}
        secrets.save(d)
    _clear_common()
    print("已清除作业平台账号与登录状态。邮箱配置保留。")
    return 0


def reset_email():
    d = secrets.load()
    if d.get("email"):
        d.pop("email", None)
        secrets.save(d)
    print("已清除邮箱配置。账号配置保留。")
    return 0


# ---------- 迁移 ----------

def _placeholder(v):
    """识别配置模板里的占位文字，别把它们当成真凭据存下来。"""
    v = str(v or "").strip()
    if not v:
        return True
    if v.startswith("你的"):
        return True
    if "授权码" in v or ("学号" in v and len(v) <= 6):
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
    try:
        d = json.loads(old.read_text(encoding="utf-8"))
    except Exception as e:
        print("读取 config.json 失败：", e)
        return 1
    u, s = d.get("usst") or {}, d.get("smtp") or {}

    if u.get("user") and u.get("password") and not _placeholder(u.get("user")) and not _placeholder(u.get("password")):
        secrets.save_account("usst", user=u["user"], password=u["password"])
    if s.get("user") and s.get("auth_code") and not _placeholder(s.get("user")) and not _placeholder(s.get("auth_code")):
        secrets.save_email(
            s["user"], s["auth_code"],
            d.get("recipient") or s["user"],
            s.get("host") or guess_host(s["user"]),
            s.get("port") or 465,
        )

    keep = {k: v for k, v in d.items() if k not in ("usst", "smtp", "recipient", "portal_base_url")}
    keep.setdefault("check_interval_minutes", 15)
    keep.setdefault("remind_days_before", 5)
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
    print("config.json 现在只含非敏感设置（提醒天数、检查间隔）。")
    return 0


# ---------- 入口 ----------

def first_unconfigured():
    """返回第一个需要配置的步骤名，全部就绪返回 None。"""
    for m in platforms.enabled():
        if not secrets.account(m.KEY):
            return "account"
    if not secrets.email_config():
        return "email"
    return None


def main():
    paths.ensure()
    args = sys.argv[1:]
    if "--show" in args:
        return show()
    if "--reset" in args:
        return reset()
    if "--reset-account" in args:
        return reset_account()
    if "--reset-email" in args:
        return reset_email()
    if "--import" in args:
        return migrate()
    if "--account" in args:
        return setup_account()
    if "--email" in args:
        return setup_email()
    # 无参数：只问还缺什么
    step = first_unconfigured()
    if step is None:
        print("配置已完整。")
        return show()
    return setup_account() if step == "account" else setup_email()


if __name__ == "__main__":
    sys.exit(main())
