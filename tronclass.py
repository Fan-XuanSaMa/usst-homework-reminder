# -*- coding: utf-8 -*-
"""上理一网畅学（TronClass）作业抓取。

流程：
1. Playwright 启动系统 Edge/Chrome（无头），用 config.json 的学号密码走统一身份认证；
2. 登录态保存在 browser_state.json，下次先用它，失效了才重新登录；
3. 在已登录的页面里调用站内接口，拉齐全课程的作业：
     /api/user/recently-visited-courses                  → 课程列表
     /api/courses/{id}/homework-activities               → 每门课的作业（含 deadline / submitted）
     /api/course/{id}/homework/submission-status         → 提交状态（submitted / 未提交 / 待批改…）
4. 输出统一的原始结构到 _browser_raw.json，交给 remind.py 判断策略。

只做抓取，不发提醒、不读配置文件以外的任何东西。
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import paths
import secrets_store as secrets

BASE = paths.BASE
STATE = paths.STATE
RAW = paths.RAW
LOG = paths.LOG

# ---- 平台元信息（platforms.py 通过它登记，config_tool 用它生成配置步骤）----
KEY = "usst"
NAME = "一网畅学"
HOME = "https://1906.usst.edu.cn"
CREDS = [
    ("user", "学号", False),
    ("password", "密码", True),
]

CST = timezone(timedelta(hours=8))
LOGIN_ENTRY = "/login?next="
HOME_RE = re.compile(r"^https?://1906\.usst\.edu\.cn")

# 页面里执行的 JS：优先 fetch 站内接口，失败时返回明确错误
FETCH_JS = """
async (args) => {
  const base = args.base;
  const j = async (path) => {
    const r = await fetch(base + path, {
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "include",
    });
    const text = await r.text();
    let body;
    try { body = JSON.parse(text); } catch { body = text.slice(0, 300); }
    return { status: r.status, body };
  };
  const out = { courses: null, courses_err: null, homeworks: {} };
  const c = await j("/api/user/recently-visited-courses");
  if (c.status !== 200) { out.courses_err = c; return out; }
  out.courses = (c.body.visited_courses || []).map(x => ({
    id: x.id, name: x.name, code: x.course_code, url: x.url,
  }));
  for (const course of out.courses) {
    const hw = await j(`/api/courses/${course.id}/homework-activities?conditions=%7B%22itemsSortBy%22:%7B%22predicate%22:%22module%22,%22reverse%22:false%7D%7D`);
    const st = await j(`/api/course/${course.id}/homework/submission-status?no-intercept=true`);
    out.homeworks[String(course.id)] = {
      list: hw, status: st,
    };
  }
  return out;
}
"""


def log(msg):
    paths.LOG.parent.mkdir(parents=True, exist_ok=True)
    with paths.LOG.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def now():
    return datetime.now(CST)


def parse_due(iso):
    """TronClass 时间形如 2026-10-27T15:59:00Z（UTC）。"""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(CST)
    except ValueError:
        return None


class LoginError(RuntimeError):
    """自动登录失败（密码错、验证码、门户改版等）。"""


class NotConfigured(LoginError):
    """尚未填账号密码。属于正常状态，不触发故障告警。"""


def _launch(p):
    """依次尝试系统 Edge、Chrome，最后退回 Playwright 自带 Chromium。"""
    last = None
    for channel in ("msedge", "chrome", None):
        try:
            kw = {"headless": True}
            if channel:
                kw["channel"] = channel
            return p.chromium.launch(**kw)
        except Exception as e:  # 该浏览器没装
            last = e
    raise LoginError(f"找不到可用浏览器：{last}")


def _do_login(page, user, pwd):
    page.goto("https://1906.usst.edu.cn" + LOGIN_ENTRY, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_selector("#username", timeout=30000)
    except Exception:
        raise LoginError(f"没等到统一身份认证表单，当前地址：{page.url}")
    page.fill("#username", user)
    page.fill("#password", pwd)
    btn = page.locator("#login_submit, .auth_login_btn, button[type=submit]")
    if btn.count():
        btn.first.click()
    else:
        page.keyboard.press("Enter")
    page.wait_for_timeout(4000)
    if not HOME_RE.match(page.url):
        # 仍在认证域通常意味着账号密码错误 / 需要验证码
        detail = page.url[:120]
        try:
            err = page.locator("#showErrorTip, .authError, .login-error").first.inner_text(timeout=2000)
        except Exception:
            err = ""
        raise LoginError(f"登录未跳回门户（可能密码有误或需要验证码）：{err or detail}")


def fetch_raw(user, pwd):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            ctx = browser.new_context(
                storage_state=str(STATE) if STATE.exists() else None,
                locale="zh-CN",
                viewport={"width": 1366, "height": 900},
            )
            page = ctx.new_page()

            logged_in = False
            if STATE.exists():
                try:
                    page.goto("https://1906.usst.edu.cn/user/index", wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2500)
                    logged_in = bool(HOME_RE.match(page.url)) and "authserver" not in page.url
                except Exception:
                    logged_in = False

            if not logged_in:
                _do_login(page, user, pwd)
                page.goto("https://1906.usst.edu.cn/user/index", wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)

            raw = page.evaluate(FETCH_JS, {"base": "https://1906.usst.edu.cn"})
            if raw.get("courses_err"):
                raise LoginError(f"课程列表接口异常：{raw['courses_err']}")

            ctx.storage_state(path=str(STATE))
            return raw
        finally:
            browser.close()


def normalize(raw):
    """把原始接口数据整理成统一作业列表。

    返回 [{
        id, course, course_id, title, due(datetime|None), submitted(bool),
        status(str), closed(bool), url, needs_online(bool), source
    }]
    """
    items = []
    for course in raw.get("courses") or []:
        cid, cname = course["id"], course["name"]
        bundle = (raw.get("homeworks") or {}).get(str(cid)) or {}
        hw_list = (bundle.get("list") or {}).get("body") or {}
        activities = hw_list.get("homework_activities") or []
        status_body = (bundle.get("status") or {}).get("body") or {}
        status_map = {}
        if isinstance(status_body, dict):
            for s in status_body.get("homework_activities") or []:
                status_map[s.get("id")] = s

        for a in activities:
            aid = a.get("id")
            st = status_map.get(aid, {})
            submitted = a.get("submitted")
            if submitted is None and st.get("status_code"):
                submitted = st.get("status_code") in ("submitted", "graded", "comment")
            due = parse_due(a.get("deadline") or a.get("end_time"))
            items.append({
                "id": aid,
                "course": cname,
                "course_id": cid,
                "title": (a.get("title") or "").strip() or "(未命名作业)",
                "due": due,
                "submitted": bool(submitted),
                "status": st.get("status") or a.get("submitted_status") or "",
                "closed": bool(a.get("is_closed")),
                "url": f"https://1906.usst.edu.cn/course/{cid}/homework/{aid}",
                "needs_online": True,
                "source": "homework-activities",
            })
    return items


def load_credentials():
    """从加密存储读取本平台账号；缺失时返回 None。"""
    user = secrets.get(f"accounts.{KEY}.user")
    pwd = secrets.get(f"accounts.{KEY}.password")
    if not user or not pwd:
        return None
    return {"user": user, "password": pwd}


# platforms.py 统一按这个名字取凭据
load_creds = load_credentials


def fetch_with(creds=None):
    """用给定凭据抓取。creds 为 None 时从加密存储读。"""
    paths.ensure()
    creds = creds or load_credentials()
    if not creds:
        raise NotConfigured("尚未保存账号密码")
    raw = fetch_raw(creds["user"], creds["password"])
    RAW.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    return normalize(raw)


def fetch():
    return fetch_with(load_credentials())


if __name__ == "__main__":
    # 手动跑一轮抓取，打印结果，用于排查
    try:
        items = fetch()
    except Exception as e:
        print("抓取失败:", type(e).__name__, e)
        sys.exit(1)
    print(f"{now():%Y-%m-%d %H:%M} 抓到 {len(items)} 个作业")
    for a in sorted(items, key=lambda x: (x["due"] or datetime.max.replace(tzinfo=CST))):
        due = f"{a['due']:%m-%d %H:%M}" if a["due"] else "无截止"
        print(f"  [{'已交' if a['submitted'] else '未交'}] {a['course']} / {a['title']}  截止 {due}  {a['url']}")
