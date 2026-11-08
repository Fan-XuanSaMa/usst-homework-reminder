# -*- coding: utf-8 -*-
"""超星学习通（i.chaoxing.com）作业抓取。

流程：
1. Playwright 无头启动系统 Edge/Chrome，会话存在 chaoxing_state.json；
2. 会话失效时用手机号 + 密码登录（passport2 的 fanyalogin 接口，
   密码用页面里固定写死的 AES-ECB 密钥加密，等同于官方前端行为）；
3. 打开「我学的课」页面拿课程列表（courseid / clazzid / personid）；
4. 逐门课请求作业列表页 /work/task-list，解析出作业标题、状态、剩余时间。

学习通的作业列表只给相对时间（「剩余 21 小时 51 分钟」），不给绝对截止时刻，
所以这里的 due 是由「现在 + 剩余时间」现算的，精度到分钟，刷新一次更新一次。
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone

import paths
import secrets_store as secrets

# ---- 平台元信息 ----
KEY = "chaoxing"
NAME = "超星学习通"
HOME = "https://i.chaoxing.com/"
CREDS = [
    ("user", "学习通手机号", False),
    ("password", "学习通密码", True),
]

CST = timezone(timedelta(hours=8))

LOGIN_URL = "https://passport2.chaoxing.com/login?fid=&newversion=true&refer=https%3A%2F%2Fi.chaoxing.com"
COURSE_PAGE = "https://mooc1-1.chaoxing.com/visit/interaction"
TASK_LIST = "https://mooc1.chaoxing.com/mooc-ans/work/task-list"

# 前端 login.js 里写死的传输密钥（AES-128-ECB），不是用户密钥
_AES_KEY = b"u2oh6Vu^HWe4_AES"

COOKIE_HINT = "uf"          # 有这个 Cookie 说明已登录


class LoginError(RuntimeError):
    """自动登录失败（密码错、需要验证码、页面改版等）。"""


class NotConfigured(LoginError):
    """尚未填账号密码。属于正常状态，不触发故障告警。"""


def now():
    return datetime.now(CST)


def log(msg):
    paths.LOG.parent.mkdir(parents=True, exist_ok=True)
    with paths.LOG.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


# ---------- 凭据 ----------

def load_creds():
    user = secrets.get(f"accounts.{KEY}.user")
    pwd = secrets.get(f"accounts.{KEY}.password")
    if not user or not pwd:
        return None
    return {"user": user, "password": pwd}


# ---------- 加密 ----------

def encrypt_password(plain):
    """复刻页面 login.js 的 encryptByAES：AES-128-ECB + PKCS7，输出 hex。"""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    p = padding.PKCS7(128).padder()
    data = p.update(plain.encode("utf-8")) + p.finalize()
    enc = Cipher(algorithms.AES(_AES_KEY), modes.ECB()).encryptor()
    return (enc.update(data) + enc.finalize()).hex()


# ---------- 浏览器 ----------

def _launch(p):
    last = None
    for channel in ("msedge", "chrome", None):
        try:
            kw = {"headless": True}
            if channel:
                kw["channel"] = channel
            return p.chromium.launch(**kw)
        except Exception as e:
            last = e
    raise LoginError(f"找不到可用浏览器：{last}")


def _logged_in(ctx):
    return any(c.get("name") == COOKIE_HINT for c in ctx.cookies())


def _do_login(page, user, pwd):
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector("#phone", timeout=20000)
        page.wait_for_selector("#pwd", timeout=20000)
    except Exception:
        raise LoginError(f"没等到登录表单，当前地址：{page.url[:120]}")

    page.fill("#phone", user)
    page.fill("#pwd", pwd)
    page.click("#loginBtn")

    # 登录接口是异步的；等 Cookie 出现，最多 30 秒
    for _ in range(30):
        page.wait_for_timeout(1000)
        cookies = {c.get("name"): c.get("value") for c in page.context.cookies()}
        if COOKIE_HINT in cookies:
            return
        if "/login" not in page.url:
            # 已经跳走也算，后续抓取会验证
            return

    # 没拿到会话，尽量取到页面上的错误提示
    detail = ""
    for sel in ("#phoneMsg", "#pwdMsg", ".msg-error", "#messgerErr"):
        try:
            t = page.locator(sel).first.inner_text(timeout=1000).strip()
            if t:
                detail = t
                break
        except Exception:
            continue
    raise LoginError(f"登录未成功（可能密码有误、需要验证码或二次验证）：{detail or page.url[:120]}")


# ---------- 抓取 ----------

COURSE_JS = """() => Array.from(document.querySelectorAll('li.course')).map(li => ({
    name: ((li.querySelector('h3 a') || {}).innerText || '').trim(),
    courseid: li.getAttribute('courseid'),
    clazzid: li.getAttribute('clazzid'),
    personid: li.getAttribute('personid')
})).filter(c => c.courseid && c.clazzid)"""

TASK_JS = """() => Array.from(document.querySelectorAll('li[data1]')).map(li => ({
    taskref: li.getAttribute('data1') || '',
    url: li.getAttribute('data') || '',
    title: ((li.querySelector('p') || {}).innerText || '').trim(),
    spans: Array.from(li.querySelectorAll('span')).map(s => s.innerText.trim()).filter(Boolean),
    gray: !!li.querySelector('img[src*="gray"]')
}))"""

_LEFT_RE = re.compile(r"剩余\s*(?:(\d+)\s*天)?\s*(?:(\d+)\s*小时)?\s*(?:(\d+)\s*分)?")
_DATED_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?")


def parse_remaining(text, base=None):
    """把「剩余21小时52分钟」换算成绝对截止时刻；解析不了返回 None。"""
    if not text:
        return None
    m = _LEFT_RE.search(text)
    if not m:
        return None
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    if not any((d, h, mi)):
        return None
    return (base or now()) + timedelta(days=d, hours=h, minutes=mi)


def parse_deadline(text, base=None):
    """优先找绝对时间（2026-11-10 23:59），没有就用相对剩余时间。"""
    if not text:
        return None
    m = _DATED_RE.search(text)
    if m:
        y, mo, d, hh, mm = m.groups()
        try:
            return datetime(int(y), int(mo), int(d), int(hh or 23), int(mm or 59), tzinfo=CST)
        except ValueError:
            return None
    return parse_remaining(text, base)


def _submitted(spans, gray):
    """判断是否已提交。

    学习通列表里的状态文字：
      「待批阅」「已批阅」「已完成」「已交」→ 已交
      「待提交」「未提交」「未完成」        → 未交
      「剩余 X 小时/分钟」                → 还没到截止，能交，即未交
    同时给出 icon 是否为灰色：灰色表示任务已结束（通常已交或已过截止）。
    剩余时间优先级最高——能显示剩余时间就不可能是「交完了」。
    """
    joined = " ".join(spans)
    if _LEFT_RE.search(joined):
        return False
    if any(k in joined for k in ("待提交", "未提交", "未完成")):
        return False
    if any(k in joined for k in ("已提交", "待批阅", "已批阅", "已完成", "已交")):
        return True
    return gray


def _course_name(raw):
    """去掉「(2026-2027-1)-…」这类学期后缀，邮件里更好看。"""
    return re.sub(r"\(\d{4}-\d{4}-\d\)\s*-\s*[\d-]+$", "", raw or "").strip() or raw or "(未命名课程)"


def _clean_task_url(raw):
    """去掉链接里的 userId，避免把个人 ID 带进邮件和日志。"""
    q = dict(re.findall(r"([^?&=]+)=([^&]*)", (raw or "").replace("&amp;", "&")))
    if not q.get("taskrefId"):
        return raw or ""
    parts = [f"taskrefId={q['taskrefId']}", f"courseId={q.get('courseId', '')}",
             f"classId={q.get('clazzId', '')}"]
    if q.get("enc_task"):
        parts.append(f"enc_task={q['enc_task']}")
    return ("https://mooc1.chaoxing.com/mooc-ans/work/phone/task-work?" + "&".join(parts))


def _parse_tasks(tasks, course, base):
    items = []
    for t in tasks:
        title = (t.get("title") or "").strip() or "(未命名作业)"
        spans = t.get("spans") or []
        submitted = _submitted(spans, t.get("gray"))
        due = None
        for s in spans:
            due = parse_deadline(s, base)
            if due:
                break
        items.append({
            # 跨平台去重键：学习通和其余平台的数字 ID 会撞车，必须带前缀
            "id": f"{KEY}-{t.get('taskref') or abs(hash(title)) % 10**8}",
            "course": course,
            "course_id": "",
            "title": title,
            "due": due,
            "submitted": submitted,
            "status": " ".join(spans),
            "closed": False,
            "url": _clean_task_url(t.get("url")),
            "needs_online": True,
            "source": KEY,
            "platform": KEY,
        })
    return items


def _load_courses(page):
    """打开选课页并读出课程；会话失效时返回空列表。"""
    try:
        page.goto(COURSE_PAGE, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)
        if "passport2.chaoxing.com" in page.url:
            return []
        return page.evaluate(COURSE_JS) or []
    except Exception:
        return []


def fetch_raw(creds):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            ctx = browser.new_context(
                storage_state=str(paths.CHAOXING_STATE) if paths.CHAOXING_STATE.exists() else None,
                locale="zh-CN",
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            )
            page = ctx.new_page()

            courses = _load_courses(page) if paths.CHAOXING_STATE.exists() else []
            if not courses:
                # 没有会话或会话已失效：清掉旧 Cookie 重新登录
                ctx.clear_cookies()
                paths.CHAOXING_STATE.unlink(missing_ok=True)
                _do_login(page, creds["user"], creds["password"])
                courses = _load_courses(page)
            if not courses:
                raise LoginError(f"没读到课程列表（登录后仍被跳转，或选课页面改版）：{page.url[:120]}")

            ctx.storage_state(path=str(paths.CHAOXING_STATE))

            base = now()
            out = {"fetched_at": base.isoformat(), "courses": [], "tasks": {}}
            for c in courses:
                url = (f"{TASK_LIST}?courseId={c['courseid']}&classId={c['clazzid']}"
                       f"&cpi={c.get('personid') or 0}")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=40000)
                    page.wait_for_timeout(1200)
                    tasks = page.evaluate(TASK_JS)
                except Exception as e:
                    tasks = []
                    log(f"{now():%Y-%m-%d %H:%M} 学习通课程「{c['name']}」作业读取失败：{e}")
                out["courses"].append(c)
                out["tasks"][c["courseid"]] = tasks
            return out
        finally:
            browser.close()


def normalize(raw):
    base = None
    try:
        base = datetime.fromisoformat(raw.get("fetched_at"))
    except (TypeError, ValueError):
        base = now()
    items = []
    for c in raw.get("courses") or []:
        tasks = (raw.get("tasks") or {}).get(c["courseid"]) or []
        items.extend(_parse_tasks(tasks, _course_name(c.get("name")), base))
    return items


def fetch():
    paths.ensure()
    creds = load_creds()
    if not creds:
        raise NotConfigured("尚未保存学习通账号")
    return normalize(fetch_raw(creds))


def manual_login(timeout_sec=300):
    """打开有头浏览器让用户自己扫码/登录，把会话存下来。

    用于需要验证码、二次验证，或者不想把密码交给程序的情况。
    返回 True 表示已拿到会话。
    """
    import time

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = None
        for channel in ("msedge", "chrome", None):
            try:
                kw = {"headless": False}
                if channel:
                    kw["channel"] = channel
                browser = p.chromium.launch(**kw)
                break
            except Exception:
                continue
        if browser is None:
            raise LoginError("找不到可用浏览器")

        try:
            ctx = browser.new_context(locale="zh-CN", viewport={"width": 1400, "height": 900})
            page = ctx.new_page()
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            print("请在弹出的窗口里登录学习通，登录成功后会自动继续…")
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                if _logged_in(ctx):
                    paths.ensure()
                    ctx.storage_state(path=str(paths.CHAOXING_STATE))
                    print("登录态已保存。")
                    return True
                page.wait_for_timeout(1500)
            print("等待超时，未检测到登录。")
            return False
        finally:
            browser.close()


if __name__ == "__main__":
    # 手动跑一轮，用于排查；--login 打开窗口手动扫码登录
    if "--login" in sys.argv:
        try:
            sys.exit(0 if manual_login() else 1)
        except Exception as e:
            print("手动登录失败:", type(e).__name__, e)
            sys.exit(1)
    try:
        items = fetch()
    except NotConfigured:
        print("尚未配置学习通账号。运行：python config_tool.py --account")
        sys.exit(2)
    except Exception as e:
        print("抓取失败:", type(e).__name__, e)
        sys.exit(1)
    print(f"{now():%Y-%m-%d %H:%M} 抓到 {len(items)} 个作业")
    for a in sorted(items, key=lambda x: (x["due"] or datetime.max.replace(tzinfo=CST))):
        due = f"{a['due']:%m-%d %H:%M}" if a["due"] else "无截止"
        print(f"  [{'已交' if a['submitted'] else '未交'}] {a['course']} / {a['title']}  截止 {due}  {a['url']}")
