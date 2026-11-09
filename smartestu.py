# -*- coding: utf-8 -*-
"""数你最灵（smartestu.cn）作业抓取。

流程：
1. Playwright 无头启动系统 Edge/Chrome，会话存在 smartestu_state.json；
2. 会话失效时用「学校代码 + 学号 + 密码」登录（POST /api/auth/login）；
3. 先拿学生课程列表，再逐门课查作业：
     POST /api/homework/student/course/query        → 课程
     POST /api/homework/student/mark/queryHomeworks → 作业（含 endTime / submission_status）

学校默认上海理工大学（usst）。与学习通不同，这里的截止时间是绝对时间，
不需要靠「剩余 X 小时」现算。

第一学期要先让程序拿到一次会话：
    python smartestu.py --login     # 弹窗手动登录，之后自动复用会话
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone

import paths
import secrets_store as secrets

# ---- 平台元信息 ----
KEY = "smartestu"
NAME = "数你最灵"
HOME = "https://smartestu.cn"
SCHOOL_CODE = "usst"          # 上海理工大学
SCHOOL_NAME = "上海理工大学"
CREDS = [
    ("user", "学号（数你最灵的登录名，通常是学号）", False),
    ("password", "数你最灵密码", True),
]
# 有这句时，配置工具会提示可以跳过密码、改用浏览器登录
LOGIN_HINT = "python smartestu.py --login"

CST = timezone(timedelta(hours=8))

BASE = "https://smartestu.cn"
RAW = paths.SMARTESTU_RAW
LOGIN_URL = BASE + "/login"
ASSIGN_PAGE = BASE + "/assignment"
API_COURSES = BASE + "/api/homework/student/course/query"
API_HOMEWORKS = BASE + "/api/homework/student/mark/queryHomeworks"
API_SESSION = BASE + "/api/auth/session"
API_LOGIN = BASE + "/api/auth/login"

# 前端页面自带的协议头，服务端会校验；缺了会返回 426
PROTO_HEADERS = {
    "X-Auth-Protocol": "cookie-v1",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

COOKIE_HINT = "USER_TOKEN"    # 兜底用；以 /api/auth/session 的结果为准

# 各种时间字段：毫秒时间戳 / 秒时间戳 / ISO 字符串都有
_RELATIVE_RE = re.compile(r"剩余\s*(?:(\d+)\s*天)?\s*(?:(\d+)\s*小时)?\s*(?:(\d+)\s*分)?")

# 登录失败时的错误提示与页面地址可能回显学号，写日志/告警邮件前先打码
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_STUDENT_RE = re.compile(r"(?<!\d)(\d{2})\d{4,}(\d{2})(?!\d)")
_EMAIL_RE = re.compile(r"([\w.%+-])[\w.%+-]*(@[\w.-]+\.[a-z]{2,})", re.I)


def _mask_account(text):
    """把学号、手机号、邮箱打码，避免账号进入日志或故障告警邮件。"""
    text = text or ""
    text = _EMAIL_RE.sub(r"\1***\2", text)
    text = _PHONE_RE.sub(r"\1****\2", text)
    return _STUDENT_RE.sub(r"\1****\2", text)


class LoginError(RuntimeError):
    """自动登录失败（密码错、需要额外验证、页面改版等）。"""


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
    """账号密码是可选的：也可以只用 --login 存下的浏览器会话。"""
    user = secrets.get(f"accounts.{KEY}.user")
    pwd = secrets.get(f"accounts.{KEY}.password")
    if user and pwd:
        return {"user": user, "password": pwd,
                "school": secrets.get(f"accounts.{KEY}.school") or SCHOOL_CODE}
    if paths.SMARTESTU_STATE.exists():
        return {"session_only": True, "school": SCHOOL_CODE}
    return None


# ---------- 浏览器 ----------

def _launch(p, headless=True):
    last = None
    for channel in ("msedge", "chrome", None):
        try:
            kw = {"headless": headless}
            if channel:
                kw["channel"] = channel
            return p.chromium.launch(**kw)
        except Exception as e:
            last = e
    raise LoginError(f"找不到可用浏览器：{last}")


def _session_ok(page):
    """向服务端问一次当前会话，200 才算真的登录了。"""
    try:
        res = page.evaluate(
            """async (args) => {
                const r = await fetch(args.url, {
                    headers: {"X-Auth-Protocol": "cookie-v1"},
                    credentials: "include",
                    cache: "no-store",
                });
                return r.status;
            }""",
            {"url": API_SESSION},
        )
        return res == 200
    except Exception:
        return False


def _logged_in(ctx, page=None):
    """优先问服务端；没有页面对象时才退回到看 Cookie。"""
    if page is not None:
        return _session_ok(page)
    names = {c.get("name") or "" for c in ctx.cookies()}
    return any(COOKIE_HINT in n.upper() or n in ("token", "sid", "session") for n in names)


def _api(page, url, body):
    """在已登录的页面里发站内请求，返回 (状态码, 解析后的响应)。"""
    res = page.evaluate(
        """async (args) => {
            const r = await fetch(args.url, {
                method: "POST",
                headers: args.headers,
                credentials: "include",
                body: JSON.stringify(args.body ?? {}),
            });
            const text = await r.text();
            let data;
            try { data = JSON.parse(text); } catch { data = text.slice(0, 400); }
            return { status: r.status, data };
        }""",
        {"url": url, "headers": PROTO_HEADERS, "body": body},
    )
    return res.get("status"), res.get("data")


def _do_login(page, user, pwd, school):
    """走官方登录接口。字段沿用页面登录表单：schoolCode + schoolUserLocalId + password。"""
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    payload = {
        "schoolCode": school,
        "schoolUserLocalId": user,
        "schoolUserId": f"{school}-{user}",
        "password": pwd,
    }
    status, data = _api(page, API_LOGIN, payload)
    if status == 426:
        raise LoginError("数你最灵网站已更新，抓取模块需要同步更新")
    if status in (200, 201):
        return
    detail = ""
    if isinstance(data, dict):
        detail = data.get("message") or data.get("code") or ""
    raise LoginError(
        f"登录未成功（HTTP {status}；可能密码有误、需要邮箱验证或页面改版）：{_mask_account(str(detail))[:120]}"
    )


# ---------- 抓取 ----------

def _course_list(page):
    status, data = _api(page, API_COURSES, {})
    if status == 401:
        return []
    if status != 200:
        raise LoginError(f"课程列表接口异常（HTTP {status}）：{_mask_account(str(data)[:150])}")
    body = data.get("data") if isinstance(data, dict) else None
    if isinstance(body, list):
        return body
    if isinstance(data, list):
        return data
    return []


def _homeworks(page, course_ids, scene="homework", page_size=100):
    """返回扁平化的作业列表。

    返回结构是「课程 → 该课程的作业」，不是平铺的：
        data.courseHomeworkDTOList[].studentCourseHomeworkDTOList[]
    """
    out = []
    page_no = 1
    while True:
        body = {"courseIds": course_ids, "scene": scene, "pageNo": page_no, "pageSize": page_size}
        status, data = _api(page, API_HOMEWORKS, body)
        if status == 401:
            raise LoginError("作业列表接口返回未登录")
        if status != 200:
            raise LoginError(f"作业列表接口异常（HTTP {status}）：{_mask_account(str(data)[:150])}")
        pack = data.get("data") if isinstance(data, dict) else {}
        if not isinstance(pack, dict):
            break
        for course in pack.get("courseHomeworkDTOList") or []:
            cname = course.get("courseName") or ""
            for hw in course.get("studentCourseHomeworkDTOList") or []:
                hw = dict(hw)
                hw.setdefault("courseId", course.get("courseId"))
                hw.setdefault("courseName", cname)
                out.append(hw)
        if page_no >= (pack.get("pageTotal") or 1):
            break
        page_no += 1
    return out


def fetch_raw(creds):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            ctx = browser.new_context(
                storage_state=str(paths.SMARTESTU_STATE) if paths.SMARTESTU_STATE.exists() else None,
                locale="zh-CN",
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            )
            page = ctx.new_page()

            courses = []
            if paths.SMARTESTU_STATE.exists():
                try:
                    page.goto(ASSIGN_PAGE, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(2500)
                    courses = _course_list(page)
                except Exception:
                    courses = []

            if not courses:
                # 没有会话或已失效：清掉旧 Cookie 重新登录
                paths.SMARTESTU_STATE.unlink(missing_ok=True)
                ctx.clear_cookies()
                if creds.get("session_only"):
                    raise LoginError("数你最灵的登录已过期，请运行：python smartestu.py --login")
                _do_login(page, creds["user"], creds["password"], creds.get("school") or SCHOOL_CODE)
                page.goto(ASSIGN_PAGE, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
                courses = _course_list(page)
            if not courses:
                raise LoginError(f"没读到课程列表（登录后仍为空，或账号没有选课）：{_mask_account(page.url[:120])}")

            paths.ensure()
            ctx.storage_state(path=str(paths.SMARTESTU_STATE))

            ids = [c.get("id") for c in courses if c.get("id") is not None]
            raw = {
                "fetched_at": now().isoformat(),
                "courses": courses,
                "homeworks": _homeworks(page, ids, "homework"),
                "exams": _homeworks(page, ids, "online_exam"),
            }
            RAW.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
            return raw
        finally:
            browser.close()


# ---------- 解析 ----------

def parse_time(value):
    """毫秒/秒时间戳、ISO 字符串、'2026-11-10 23:59' 都能认。"""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e11:            # 毫秒
            ts /= 1000.0
        if ts <= 0:
            return None
        try:
            return datetime.fromtimestamp(ts, CST)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return parse_time(int(text))
    try:
        iso = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        return dt.astimezone(CST) if dt.tzinfo else dt.replace(tzinfo=CST)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=CST)
        except ValueError:
            continue
    return None


_SUBMITTED = ("submitted", "completed", "已提交", "已完成", "待批阅", "已批阅")
_PENDING = ("not_submitted", "pending", "未提交", "待提交", "未完成")


def _is_submitted(hw):
    """提交状态：接口给 submission_status，也有 compeleted 之类的布尔字段。"""
    for key in ("submission_status", "submissionStatus", "status"):
        v = hw.get(key)
        if isinstance(v, str) and v.strip():
            low = v.strip().lower()
            if low in _SUBMITTED:
                return True
            if low in _PENDING:
                return False
            text = v.strip()
            if any(k in text for k in ("待提交", "未提交", "未完成")):
                return False
            if any(k in text for k in ("已提交", "已完成", "待批阅", "已批阅")):
                return True
    for key in ("compeleted", "completed", "submitted"):
        v = hw.get(key)
        if isinstance(v, bool):
            return v
    return False


def _deadline(hw):
    """截止时间：优先个人延期，其次常规截止。"""
    for key in ("personalLateDeadlineAt", "endTime", "deadline", "dueAt", "end_time"):
        dt = parse_time(hw.get(key))
        if dt:
            # 9999-12-31 表示「不限时」，当作没有截止时间
            if dt.year >= 9999:
                return None
            return dt
    return None


def _clean_url(hw):
    """作业页是统一入口，链接里不带任何 ID，免得把个人参数带进邮件。"""
    return ASSIGN_PAGE


def normalize(raw):
    courses = {c.get("id"): c.get("name") or "(未命名课程)" for c in raw.get("courses") or []}
    items = []
    for scene, key in (("homework", "homeworks"), ("online_exam", "exams")):
        for hw in raw.get(key) or []:
            hid = hw.get("id") or hw.get("homeworkId")
            if hid is None:
                continue
            cid = hw.get("courseId")
            scene_of_hw = hw.get("scene") or scene
            title = (hw.get("name") or hw.get("homeworkName") or "").strip() or "(未命名作业)"
            if scene_of_hw == "online_exam":
                title = f"[线上考试] {title}"
            items.append({
                # 跨平台去重键：各平台的数字 ID 会撞车，必须带平台前缀
                "id": f"{KEY}-{scene_of_hw}-{hid}",
                "course": courses.get(cid) or hw.get("courseName") or "(未命名课程)",
                "course_id": cid,
                "title": title,
                "due": _deadline(hw),
                "submitted": _is_submitted(hw),
                "status": str(hw.get("submission_status") or hw.get("status") or ""),
                "closed": False,
                "url": _clean_url(hw),
                "needs_online": True,
                "source": KEY,
                "platform": KEY,
            })
    return items


def fetch():
    paths.ensure()
    creds = load_creds()
    if not creds:
        raise NotConfigured("尚未保存数你最灵账号")
    return normalize(fetch_raw(creds))


def manual_login(timeout_sec=300):
    """打开有头浏览器让用户自己登录（密码/邮箱验证/微信都行），把会话存下来。

    返回 True 表示已拿到会话。
    """
    import time

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _launch(p, headless=False)
        try:
            ctx = browser.new_context(locale="zh-CN", viewport={"width": 1400, "height": 900})
            page = ctx.new_page()
            page.goto(ASSIGN_PAGE, wait_until="domcontentloaded", timeout=60000)
            print("请在弹出的窗口里登录数你最灵，登录成功后会自动继续…")
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                if _logged_in(ctx, page):
                    paths.ensure()
                    ctx.storage_state(path=str(paths.SMARTESTU_STATE))
                    print("登录态已保存。")
                    return True
                page.wait_for_timeout(1500)
            print("等待超时，未检测到登录。")
            return False
        finally:
            browser.close()


if __name__ == "__main__":
    # 手动跑一轮，用于排查；--login 打开窗口手动登录
    if "--login" in sys.argv:
        try:
            sys.exit(0 if manual_login() else 1)
        except Exception as e:
            print("手动登录失败:", type(e).__name__, e)
            sys.exit(1)
    try:
        items = fetch()
    except NotConfigured:
        print("尚未配置数你最灵账号。运行：python config_tool.py --account")
        sys.exit(2)
    except Exception as e:
        print("抓取失败:", type(e).__name__, e)
        sys.exit(1)
    print(f"{now():%Y-%m-%d %H:%M} 抓到 {len(items)} 个作业")
    for a in sorted(items, key=lambda x: (x["due"] or datetime.max.replace(tzinfo=CST))):
        due = f"{a['due']:%m-%d %H:%M}" if a["due"] else "无截止"
        print(f"  [{'已交' if a['submitted'] else '未交'}] {a['course']} / {a['title']}  截止 {due}")
