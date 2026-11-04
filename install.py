# -*- coding: utf-8 -*-
"""一键安装：检查依赖 + 配置检查 + 注册开机自启 + 启动托盘。

用法：
    python install.py               # 安装并启动
    python install.py --stop        # 停止托盘程序
    python install.py --uninstall   # 停止并移除开机自启
    python install.py --check       # 只跑一轮检查（不开托盘）

首次使用请先运行：python config_tool.py --setup
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import paths  # noqa: E402

STARTUP = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
VBS = STARTUP / "usst_homework_reminder.vbs"
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
REQUIRED = ["playwright", "pystray", "PIL"]

VBS_CONTENT = (
    "' 上理作业提醒：开机静默启动托盘（无控制台窗口）\n"
    f'CreateObject("WScript.Shell").Run """{PYTHONW}"" ""{BASE / "tray.py"}""", 0, False\n'
)


def sh(cmd):
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True)


def ensure_config():
    import paths
    import secrets_store as secrets

    paths.ensure()
    # 旧版项目内明文 config.json → 自动迁移到加密存储
    legacy = paths.BASE / "config.json"
    if legacy.exists():
        try:
            d = json.loads(legacy.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        if (d.get("usst") or {}).get("password") or (d.get("smtp") or {}).get("auth_code"):
            print("检测到项目内的明文配置，正在迁移到加密存储…")
            import config_tool
            config_tool.migrate()
            print()

    if secrets.exists():
        d = secrets.load()
        u, s = d.get("usst") or {}, d.get("smtp") or {}
        missing = []
        if not u.get("user") or not u.get("password"):
            missing.append("学号 / 密码")
        if not s.get("user") or not s.get("auth_code"):
            missing.append("发件邮箱 / SMTP 授权码")
        if not d.get("recipient"):
            missing.append("收件邮箱")
        if missing:
            print("还缺这些配置：" + "、".join(missing))
            print("请运行：python config_tool.py --setup")
            return False
        return True

    print("尚未配置账号与邮箱。")
    print("请运行：python config_tool.py --setup")
    return False


def ensure_deps():
    try:
        missing = []
        for mod in REQUIRED:
            try:
                __import__(mod)
            except ImportError:
                missing.append("pillow" if mod == "PIL" else mod)
        if missing:
            sh([sys.executable, "-m", "pip", "install", *missing])
        # 系统 Edge / Chrome 可直接驱动；都没有时再装 Chromium
        from playwright.sync_api import sync_playwright
        ok = False
        with sync_playwright() as p:
            for ch in ("msedge", "chrome"):
                try:
                    b = p.chromium.launch(headless=True, channel=ch)
                    b.close()
                    ok = True
                    break
                except Exception:
                    pass
        if not ok:
            sh([sys.executable, "-m", "playwright", "install", "chromium"])
    except subprocess.CalledProcessError as e:
        print("依赖安装失败：", e)
        return False
    return True


def install():
    if not ensure_config():
        return
    if not ensure_deps():
        return
    VBS.write_text(VBS_CONTENT, encoding="utf-8")
    print("开机自启已注册：", VBS)
    paths.ensure()
    paths.STOP.unlink(missing_ok=True)
    launcher = str(PYTHONW) if PYTHONW.exists() else sys.executable
    if not PYTHONW.exists():
        print("警告：未找到 pythonw.exe，托盘程序将带控制台窗口运行。")
    subprocess.Popen([launcher, str(BASE / "tray.py")], cwd=str(BASE))
    print("托盘程序已启动。右键任务栏图标可立即检查/查看日志/退出。")
    print("日志：", paths.LOG)
    print("个人数据目录：", paths.DATA_DIR)


def stop():
    paths.ensure()
    paths.STOP.write_text("stop\n", encoding="utf-8")
    print("已创建停止标记，托盘程序将在几分钟内退出（也可右键图标退出）。")


def uninstall():
    stop()
    VBS.unlink(missing_ok=True)
    print("开机自启已移除。")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--uninstall" in args:
        uninstall()
    elif "--stop" in args:
        stop()
    elif "--check" in args:
        sys.exit(subprocess.call([sys.executable, str(BASE / "remind.py")]))
    else:
        install()
