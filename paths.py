# -*- coding: utf-8 -*-
"""统一管理文件位置：代码在项目目录，个人数据全部在项目之外。

数据目录（默认 %APPDATA%\\usst-homework-reminder）：
    secrets.dat        账号密码 / SMTP 授权码（Windows DPAPI 加密）
    browser_state.json 登录 Cookie
    _browser_raw.json  抓取到的课程与作业原始数据
    sent_log.json      发送记录
    reminder.log       运行日志
    mute.txt           静默名单（可能含课程名，故不放项目内）
    daemon.pid / daemon.stop / mute.until

可用环境变量 USST_HW_DATA_DIR 覆盖数据目录（测试用）。
"""
import os
from pathlib import Path

VERSION = "0.1.1"

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"


def _default_data_dir():
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "usst-homework-reminder"
    return Path.home() / ".usst-homework-reminder"


DATA_DIR = Path(os.environ.get("USST_HW_DATA_DIR") or _default_data_dir())

SECRETS = DATA_DIR / "secrets.dat"
STATE = DATA_DIR / "browser_state.json"
RAW = DATA_DIR / "_browser_raw.json"
SENT_LOG = DATA_DIR / "sent_log.json"
LOG = DATA_DIR / "reminder.log"
MUTE_FILE = DATA_DIR / "mute.txt"
PID = DATA_DIR / "daemon.pid"
STOP = DATA_DIR / "daemon.stop"
MUTE_UNTIL = DATA_DIR / "mute.until"

DEFAULT_MUTE = """# 静默名单：命中规则的作业不再发送任何提醒邮件。
# 一行一条规则，空格分隔多个关键词；「课程名 + 作业名」同时包含所有关键词才命中（不区分大小写）。
# 例：离散数学 第一次     → 只静默这门课的这个作业
#     离散数学             → 静默这门课的所有作业
# 以 # 开头的行为注释。删除某行即恢复提醒。
"""


def ensure():
    """创建数据目录、收紧权限、补齐静默名单。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _harden_acl(DATA_DIR)
    if not MUTE_FILE.exists():
        MUTE_FILE.write_text(DEFAULT_MUTE, encoding="utf-8")


def _harden_acl(path):
    """去掉继承权限，只保留当前用户，避免同机其他账户读取。失败则忽略。"""
    if os.name != "nt":
        return
    try:
        import subprocess
        user = os.environ.get("USERNAME") or ""
        if not user:
            return
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True, timeout=20,
        )
    except Exception:
        pass
