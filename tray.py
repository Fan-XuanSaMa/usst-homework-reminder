# -*- coding: utf-8 -*-
"""上理作业提醒托盘常驻程序。

- 任务栏托盘图标，悬浮显示下个截止；
- 每 check_interval_minutes 分钟自动检查一轮（默认 15）；
- 右键菜单：立即检查 / 打开作业页面 / 查看最近日志 / 静音到明天 / 退出；
- 用 pythonw.exe 启动则完全无控制台窗口；
- daemon.pid 防止多开；daemon.stop 文件出现即退出。
"""
import os
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import paths  # noqa: E402

STOP = paths.STOP
LOCK = paths.PID
LOG = paths.LOG
MUTE_UNTIL = paths.MUTE_UNTIL

ALARM = "alarm"          # 有紧急作业的图标颜色
NORMAL = "normal"


def log(msg):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def load_cfg():
    import json
    if not paths.CONFIG.exists():
        return {}
    try:
        return json.loads(paths.CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def muted_today():
    if not MUTE_UNTIL.exists():
        return False
    try:
        until = datetime.fromisoformat(MUTE_UNTIL.read_text(encoding="utf-8").strip())
        return datetime.now() < until
    except Exception:
        return False


def make_image(color):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 10, 58, 54], radius=8,
                        fill=(220, 38, 38) if color == ALARM else (37, 99, 235))
    d.rectangle([16, 18, 48, 22], fill="white")
    d.rectangle([16, 28, 48, 32], fill="white")
    d.rectangle([16, 38, 38, 42], fill="white")
    d.rectangle([28, 4, 36, 12], fill="white")
    return img


class App:
    def __init__(self):
        self.icon = None
        self.items = []
        self.last_summary = "尚未检查"
        self.busy = False

    # ---------- 检查 ----------
    def check_once(self):
        if self.busy:
            return
        self.busy = True
        try:
            import platforms
            import remind
            if muted_today():
                self.last_summary = f"{datetime.now():%H:%M} 已静音，跳过本轮"
                log(self.last_summary)
            else:
                mods = platforms.configured()
                if not mods:
                    raise platforms.NotConfigured("尚未保存账号密码")
                items = []
                for mod in mods:
                    items.extend(mod.fetch())
                self.items = items
                summary, sent = remind.check(items=items)
                self.last_summary = summary
                log(summary)
        except Exception as e:
            try:
                import platforms
                import remind
                normal = isinstance(e, (platforms.NotConfigured, remind.NotConfigured))
            except Exception:
                normal = False
            if normal:
                # 少配了账号或邮箱：提示即可，不算故障，不发告警邮件
                msg = f"{datetime.now():%Y-%m-%d %H:%M} 尚未配置：{e}"
                self.last_summary = msg
                log(msg)
            else:
                msg = f"{datetime.now():%Y-%m-%d %H:%M} 检查失败：{type(e).__name__}: {e}"
                self.last_summary = msg
                log(msg)
                log(traceback.format_exc())
                try:
                    import remind
                    remind.send_failure_alert(f"{type(e).__name__}: {e}")
                except Exception:
                    pass
        finally:
            self.busy = False
            self.refresh_icon()

    def worker(self):
        while not STOP.exists():
            self.check_once()
            interval = 15 * 60
            try:
                interval = int(load_cfg().get("check_interval_minutes", 15)) * 60
            except Exception:
                pass
            for _ in range(max(60, interval)):
                if STOP.exists():
                    return
                time.sleep(1)
        self.quit()

    # ---------- 托盘 ----------
    def pending(self):
        t = remind_now()
        out = []
        for a in self.items:
            if a["submitted"] or not a["due"]:
                continue
            delta = a["due"] - t
            if delta.total_seconds() < 0:
                continue                     # 已过截止不提醒
            out.append((delta, a))
        return sorted(out, key=lambda x: x[0])

    def window_days(self):
        try:
            return float(load_cfg().get("remind_days_before", 5))
        except Exception:
            return 5.0

    def refresh_icon(self):
        if not self.icon:
            return
        pend = self.pending()
        # 提醒窗口内的作业才算“待办”，图标才变红
        window = self.window_days() * 86400
        in_window = [(d, a) for d, a in pend if d.total_seconds() <= window]
        self.icon.icon = make_image(ALARM if in_window else NORMAL)
        if pend:
            delta, a = pend[0]
            tip = f"上理作业提醒\n{len(pend)} 个未提交\n最近：{a['title']}（{fmt_left(delta)}）"
        else:
            tip = "上理作业提醒\n暂无未提交作业"
        self.icon.title = tip[:127]

    def menu(self):
        import pystray
        pend = self.pending()
        window = self.window_days() * 86400
        items = [
            pystray.MenuItem(f"未提交 {len(pend)} 个", None, enabled=False),
            pystray.MenuItem("立即检查", lambda: threading.Thread(target=self.check_once, daemon=True).start()),
            self.home_item(),
            pystray.MenuItem("查看日志", self.open_log),
            pystray.MenuItem("编辑静默名单", self.open_mute),
            pystray.MenuItem("静音到明天 8:00", self.mute_today),
            pystray.MenuItem("退出", self.quit),
        ]
        for delta, a in pend[:8]:
            mark = "⚠ " if delta.total_seconds() <= window else ""
            label = f"{mark}{a['title'][:24]}（{fmt_left(delta)}）"
            items.insert(len(items) - 5, pystray.MenuItem(label, self.opener(a["url"])))
        return pystray.Menu(*items)

    @staticmethod
    def _platform_modules():
        try:
            import platforms
            return platforms.enabled()
        except Exception:
            return []

    def home_item(self):
        """单平台：一个「打开XX」菜单项；多平台：子菜单。"""
        import pystray
        mods = [m for m in self._platform_modules() if getattr(m, "HOME", "")]
        if not mods:
            return pystray.MenuItem("打开作业平台", None, enabled=False)
        if len(mods) == 1:
            return pystray.MenuItem(f"打开{mods[0].NAME}", self.opener(mods[0].HOME))
        return pystray.MenuItem(
            "打开作业平台",
            pystray.Menu(*[
                pystray.MenuItem(m.NAME, self.opener(m.HOME))
                for m in mods
            ]),
        )

    def opener(self, url):
        return lambda: webbrowser.open(url)

    def open_log(self):
        try:
            os.startfile(LOG)  # noqa: 仅 Windows
        except Exception:
            webbrowser.open(LOG.as_uri())

    def open_mute(self):
        paths.ensure()
        try:
            os.startfile(paths.MUTE_FILE)
        except Exception:
            webbrowser.open(paths.MUTE_FILE.as_uri())

    def mute_today(self):
        tomorrow = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
        MUTE_UNTIL.write_text(tomorrow.isoformat(), encoding="utf-8")
        self.last_summary = f"已静音到 {tomorrow:%m-%d %H:%M}"
        log(self.last_summary)
        self.refresh_icon()

    def quit(self):
        STOP.write_text("stop\n", encoding="utf-8")
        if self.icon:
            self.icon.stop()

    def run(self):
        import pystray
        self.icon = pystray.Icon(
            "usst_homework",
            make_image(NORMAL),
            "上理作业提醒",
            menu=pystray.Menu(
                pystray.MenuItem("正在启动…", None, enabled=False),
            ),
        )
        threading.Thread(target=self.worker, daemon=True).start()
        self.icon.menu = self.menu()
        self.icon.run()

    def setup(self):
        """icon 就绪后刷新菜单（pystray 要求）。"""
        import pystray
        self.icon.menu = self.menu()
        self.icon.update_menu()


def remind_now():
    from datetime import timezone
    return datetime.now(timezone(timedelta(hours=8)))


def fmt_left(delta):
    sec = int(delta.total_seconds())
    sign = "-" if sec < 0 else ""
    sec = abs(sec)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{sign}{d}天{h}小时"
    if h:
        return f"{sign}{h}小时{m}分"
    return f"{sign}{m}分钟"


def already_running():
    if not LOCK.exists():
        return False
    pid = LOCK.read_text(encoding="utf-8").strip()
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True, timeout=20).stdout
        return pid in out
    except Exception:
        return False


def main():
    paths.ensure()
    if already_running():
        print("已有实例在运行")
        return
    STOP.unlink(missing_ok=True)
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    try:
        App().run()
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
