# 上理作业提醒 · 使用手册

> 面向上海理工大学「一网畅学」平台（https://1906.usst.edu.cn）的本地作业提醒工具。
> 程序运行在你的电脑上，自动登录、读取作业、按截止时间发邮件提醒。

---

## 目录

1. [它能做什么](#1-它能做什么)
2. [提醒规则](#2-提醒规则)
3. [安装](#3-安装)
4. [配置](#4-配置)
5. [邮箱配置指南](#5-邮箱配置指南)
6. [日常操作](#6-日常操作)
7. [文件说明](#7-文件说明)
8. [故障排查](#8-故障排查)
9. [隐私与安全](#9-隐私与安全)
10. [许可](#许可)

---

## 1. 它能做什么

| 能力 | 说明 |
|---|---|
| 自动登录 | 用你的学号密码登录统一身份认证，登录状态会缓存，失效自动重新登录 |
| 自动找作业 | 遍历你在上的所有课程，读取每个作业的**截止时间**和**是否已提交** |
| 邮件提醒 | 遇到快截止的未交作业，发邮件到你的邮箱 |
| 托盘常驻 | 在任务栏托盘显示，右键可立即检查、直达作业页面 |
| 开机自启 | Windows 登录后自动启动，无窗口 |
| 静默名单 | 不想被提醒的作业可以单独关掉 |
| 故障告警 | 登录失败会发邮件通知你（每天最多一封） |

程序只读取作业信息，**不会替你提交作业**。

---

## 2. 提醒规则

### 一句话版

> **5 天内要交、还没交的作业，每天给你发一封汇总邮件。其他情况不打扰。**

### 判定表

| 作业情况 | 是否提醒 |
|---|---|
| 未提交，距离截止 **5 天以内**（含最后几小时） | ✅ 每天一封汇总 |
| 未提交，距离截止 **超过 5 天** | ❌ 不提醒（等进入 5 天窗口再说） |
| 未提交，但**已经过了截止时间** | ❌ 不提醒 |
| **已经提交** | ❌ 不提醒 |
| 老师发布了、但**还没设截止时间** | ✅ 在下一封汇总里列为「新作业」 |
| 在静默名单里 | ❌ 不提醒 |

### 频率

- **每 24 小时最多一封**，与检查次数、作业数量无关；
- 半夜 23:50 收到一封，第二天 00:05 **不会**再收到一封（按滚动 24 小时计算）；
- 一封邮件里会列出所有符合条件的作业，按截止时间排序。

### 一封典型邮件的样子

```
主题：[作业提醒] 2 个作业即将截止

【即将截止】
[某门课程] 第二次作业
    截止：11月08日 23:59（剩余 4 天 3 小时）
    https://1906.usst.edu.cn/course/000000/homework/000000

[另一门课程] 第三次作业
    截止：11月06日 18:00（剩余 1 天 21 小时）
    https://1906.usst.edu.cn/course/000000/homework/000000

【新作业（暂无截止时间）】
[实验类课程] 实验六预习
    暂无截止时间（老师可能还未设置）
    https://1906.usst.edu.cn/course/000000/homework/000000

—— 上理作业提醒（每天一封）
```

### 调整参数

编辑项目目录的 `config.json`：

| 字段 | 默认 | 含义 |
|---|---|---|
| `remind_days_before` | `5` | 提前几天开始提醒，改成 `3` 就是只提醒 3 天内的 |
| `check_interval_minutes` | `15` | 多久检查一次（不影响每天一封的邮件频率，只影响发现新作业的快慢） |

---

## 3. 安装

### 前置条件

- Windows 10 / 11
- Python 3.10 或更高版本
- 电脑上装了 **Edge 或 Chrome**（任选其一，程序会调用它登录，不用另外下载浏览器）

### 步骤

**第 1 步**：打开命令提示符（Win + R 输入 `cmd` 回车），克隆并进入项目目录：

```bat
git clone https://github.com/Fan-XuanSaMa/usst-homework-reminder.git
cd usst-homework-reminder
```

> 如果下载的是 ZIP 包，解压后 `cd /d "解压后的目录"` 即可。

**第 2 步**：安装依赖（只需一次）：

```bat
pip install playwright pystray pillow
```

**第 3 步**：配置账号（学号 + 密码）

```bat
python config_tool.py --account
```

只问两个问题：学号、密码。输密码时屏幕不显示字符，这是正常的。

> 配置会存到 `%APPDATA%\usst-homework-reminder\`，**不在项目目录里**。

**第 4 步**：验证能登录并抓到作业

```bat
python tronclass.py
```

看到「抓到 N 个作业」就说明账号配置正确。这一步不涉及邮箱。

**第 5 步**：配置提醒邮箱

```bat
python config_tool.py --email
```

只问三个问题：发件邮箱、授权码、收件邮箱（收件邮箱直接回车即等于发件邮箱）。
服务器地址和端口按邮箱域名自动识别，不用手填。

**第 6 步**：验证邮箱配置

```bat
python remind.py --test-email
```

**第 7 步**：先预览再正式跑一次

```bat
python remind.py --dry-run
python remind.py
```

`--dry-run` 只打印会发什么邮件，不真发、不消耗每天一封的额度。

**第 8 步**：启动托盘并注册开机自启

```bat
python install.py
```

任务栏右下角会出现一个蓝色图标。

> 如果没配完就跑 `install.py`，它会直接告诉你还差哪几步、该执行什么命令。

> 如果提示「找不到可用浏览器」，执行 `python -m playwright install chromium` 后重试。

---

## 4. 配置

### 两类配置分开存放

| 类型 | 位置 | 内容 |
|---|---|---|
| **非敏感设置** | 项目目录 `config.json` | 提醒天数、检查间隔 |
| **敏感凭据** | `%APPDATA%\usst-homework-reminder\secrets.dat` | 各平台账号（按平台分组）、发件邮箱、SMTP 授权码、收件邮箱 |

账号按平台分开存放，以后接入其他作业平台时互不影响：

```
secrets.dat
├── accounts
│   └── usst          ← 一网畅学的学号 / 密码
└── email             ← 发件邮箱 / 授权码 / 收件邮箱 / 服务器
```

`secrets.dat` 使用 **Windows DPAPI** 加密，**只有当前 Windows 账户能解密**。
文件被复制到其他电脑或其他账户后无法还原，因此可以放心地把它排除在代码仓库之外。

### 查看当前配置（自动打码）

```bat
python config_tool.py --show
```

输出示例：

```
配置目录： C:\Users\<用户名>\AppData\Roaming\usst-homework-reminder
凭据文件： ...\secrets.dat （DPAPI 加密）

== 作业平台账号 ==
  一网畅学  ： 253****118  密码 03*****cf（9 位）

== 提醒邮箱 ==
  发件邮箱： ab****@qq.com
  收件邮箱： ab****@qq.com
  授权码  ： ab************cd
  服务器  ： smtp.qq.com 465
```

### 修改配置

| 想改什么 | 命令 |
|---|---|
| 学号 / 密码 | `python config_tool.py --account` |
| 发件邮箱 / 授权码 / 收件邮箱 | `python config_tool.py --email` |
| 提醒天数 / 检查间隔 | 直接编辑项目目录的 `config.json` |

两项配置互不影响：只改邮箱不会动账号，只改账号也不会动邮箱。

### 清除凭据

```bat
python config_tool.py --reset-account   # 只清账号与登录状态
python config_tool.py --reset-email     # 只清邮箱配置
python config_tool.py --reset           # 全部清除
```

### 从旧版本升级

旧版本的账号密码曾以明文写在项目目录的 `config.json` 中。新版本会在首次运行 `python install.py`
时自动检测并迁移；也可以手动执行：

```bat
python config_tool.py --import
```

迁移后，账号密码进入加密存储，项目内的明文会被清除。旧版 `secrets.dat` 的凭据结构也会在读取时
自动升级为按平台分组，不需要重新输入。

---

## 5. 邮箱配置指南

程序通过 SMTP 发信。大部分邮箱（QQ、163、126、Gmail 等）**不能直接用登录密码**发信，需要用「授权码」。

### 方案 A：QQ 邮箱（推荐，最简单）

1. 用电脑浏览器登录 [mail.qq.com](https://mail.qq.com)；
2. 点右上角 **设置** → **账号**（新版为「账号与安全」→「安全设置」）；
3. 找到 **「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」**；
4. 开启 **「POP3/SMTP服务」** 或 **「IMAP/SMTP服务」**；
5. 按提示用手机发短信验证，页面会给出一串 **16 位授权码**（形如 `abcdabcdabcdabcd`，**没有空格**）；
6. 运行 `python config_tool.py --email`，只填三项：
   - 发件邮箱：你的 QQ 邮箱地址
   - 授权码：上一步拿到的 16 位码
   - 收件邮箱：接收提醒的地址，**直接回车**即等于发件邮箱

> 服务器和端口无需填写，按邮箱域名自动识别（QQ 邮箱 → `smtp.qq.com:465`）。

> 授权码只显示一次，请当场复制保存。忘了可以重新生成（旧码会立即失效）。

### 方案 B：163 网易邮箱

1. 登录 [mail.163.com](https://mail.163.com)；
2. 顶部 **设置** → **POP3/SMTP/IMAP**；
3. 开启 **SMTP服务**，按提示设置授权密码（同样不是登录密码）；
4. 在配置向导里填发件邮箱和授权码（收件邮箱可回车同发件邮箱），服务器自动识别。

### 方案 C：学校邮箱

先确认学校邮箱是否开放 SMTP。如果有，通常 `host` 是 `smtp.` + 学校邮箱域名，端口 `465`（SSL），
账号密码填学校邮箱自己的。具体以学校信息办说明为准。

### 验证配置

```bat
python remind.py --test-email
```

- 看到 `测试邮件已发送到 xxx` → 配置成功，去邮箱收信（可能在垃圾箱）；
- 报 `UnicodeEncodeError` / `UnicodeDecodeError` → 授权码里有中文或全角字符，重新复制；
- 报 `Authentication failed` 或 `535` → 授权码错，或 SMTP 服务没开启；
- 报 `Connection refused` / 超时 → `host` 或 `port` 填错，或网络/防火墙拦截了 465 端口。

### 常见问题

| 现象 | 原因与处理 |
|---|---|
| 收不到测试邮件 | 先查垃圾邮件箱；再确认收件邮箱没写错，可运行 `python config_tool.py --show` 核对 |
| QQ 邮箱提示「授权码无效」 | 重新生成一次授权码，注意不要带空格 |
| 公司/学校网络发不出去 | 换用手机热点试一次；部分内网封 465 端口 |
| 不想用自己的 QQ 邮箱 | 注册一个专用邮箱，或者用 163/126 的小号 |

---

## 6. 日常操作

### 托盘图标

右键任务栏的图标：

| 菜单项 | 作用 |
|---|---|
| 未提交 N 个 | 只显示，不能点 |
| 作业名称（剩 X 天） | 点击直接打开该作业页面 |
| 立即检查 | 马上检查一轮（不会强行发邮件） |
| 打开一网畅学 | 浏览器打开课程首页 |
| 查看日志 | 用记事本打开运行日志 |
| 编辑静默名单 | 打开静默名单文件（在个人数据目录中） |
| 静音到明天 8:00 | 今天不再发任何提醒邮件 |
| 退出 | 停止程序 |

图标颜色：

- **蓝色**：正常，没有 5 天内到期的未交作业；
- **红色**：有 5 天内到期的未交作业。

### 命令行

在项目目录打开 cmd：

| 想做 | 命令 |
|---|---|
| 只看抓取结果，不发邮件 | `python tronclass.py` |
| 预览今天会发什么邮件（不真发） | `python remind.py --dry-run` |
| 正常检查并发送 | `python remind.py` |
| 测试邮件配置 | `python remind.py --test-email` |
| 配置账号（学号+密码） | `python config_tool.py --account` |
| 配置邮箱（发件+授权码） | `python config_tool.py --email` |
| 查看配置（打码） | `python config_tool.py --show` |
| 只清账号 / 只清邮箱 | `python config_tool.py --reset-account` / `--reset-email` |
| 启动托盘 + 开机自启 | `python install.py` |
| 停止托盘 | `python install.py --stop` |
| 移除开机自启 | `python install.py --uninstall` |

> `python config_tool.py` 不带参数时，会只问你还缺的那一项，已配好的不会重问。

### 静默某个作业

右键托盘图标 → **编辑静默名单**，文件会打开。一行一条规则，空格分隔的多个关键词**全部命中**才静默：

```
# 只静默某门课的第三次作业
某门课程 第三次

# 静默某门课的所有作业（含以后发布的）
某门课程

# 静默所有实验课
实验
```

删除对应行即恢复提醒。改完不用重启程序，下一轮检查就生效。

> 静默名单存放在个人数据目录，因为其中可能包含你的课程名，不适合放在代码仓库里。

### 查看运行记录

右键托盘 → **查看日志**，或直接打开：

```
%APPDATA%\usst-homework-reminder\reminder.log
```

每轮一行，例如：

```
2026-11-04 16:48 检查完成：共 7 个作业，未提交 6 个（5 天内 3，无截止 0），静默 0 个，发送 0 封，距上次提醒不足 24 小时，今天不再发送
```

---

## 7. 文件说明

### 项目目录（可分享）

| 文件 | 作用 |
|---|---|
| `tronclass.py` | 登录 + 抓取作业（一网畅学平台模块） |
| `platforms.py` | 平台注册表，决定启用哪些作业平台 |
| `remind.py` | 提醒策略 + 发邮件 |
| `tray.py` | 托盘常驻程序 |
| `install.py` | 安装 / 停止 / 卸载 |
| `config_tool.py` | 配置向导（加密保存凭据） |
| `paths.py` | 统一管理文件位置 |
| `secrets_store.py` | DPAPI 加密读写 |
| `config.json` | 非敏感设置（无账号密码） |
| `config.example.json` | 设置模板 |
| `README.md` / `SECURITY.md` / `LICENSE` | 文档与许可 |

### 个人数据目录（**不可分享**）

位置：`%APPDATA%\usst-homework-reminder\`

| 文件 | 内容 |
|---|---|
| `secrets.dat` | 学号、密码、发件邮箱、授权码、收件邮箱（DPAPI 加密） |
| `browser_state.json` | 登录 Cookie（**等同于登录态**） |
| `_browser_raw.json` | 抓取到的课程与作业数据 |
| `sent_log.json` | 发送记录（用于「每天一封」） |
| `mute.txt` | 静默名单（可能含课程名） |
| `reminder.log` | 运行日志 |
| `daemon.pid` / `daemon.stop` / `mute.until` | 运行控制文件 |

---

## 8. 故障排查

### 收到「系统故障：登录或抓取失败」告警邮件

| 可能原因 | 处理 |
|---|---|
| 统一身份认证密码改了 | 运行 `python config_tool.py --account` 重新填写 |
| 认证页面改版 / 需要验证码 | 手动用浏览器登录一次 `https://1906.usst.edu.cn`，看看是否要验证码；如果学校改了页面，需要更新 `tronclass.py` 里的选择器 |
| 网络不稳定 | 等下一轮（15 分钟后）自动重试 |
| 一网畅学接口变更 | 运行 `python tronclass.py` 查看具体报错 |

### 提示「尚未保存账号密码」

运行 `python config_tool.py --account` 完成账号配置。

### 提示「尚未配置提醒邮箱」

运行 `python config_tool.py --email` 完成邮箱配置。这条只影响发信，不影响 `python tronclass.py` 抓取。

### 提示「无法读取凭据文件」

`secrets.dat` 是用当前 Windows 账户的密钥加密的，以下情况会解不开：

- 换了电脑 / 重装了系统；
- 换了 Windows 登录账户；
- 手动从别处拷贝了 `secrets.dat`。

处理方式：运行 `python config_tool.py --reset-account`，再 `python config_tool.py --account` 重新填写。

### 抓取正常但作业数是 0

- 确认老师确实发布了作业（登录网页看课程「作业」栏）；
- 如果网页上有但程序是 0，可能是接口路径变了，运行 `python tronclass.py` 看返回。

### 托盘图标不见了

- 检查任务管理器里有没有 `pythonw.exe`；
- 在开始菜单的「启动」文件夹里应有 `usst_homework_reminder.vbs`；
- 重新运行 `python install.py`。

### 电脑关机 / 睡眠期间

程序随之暂停，开机后自动恢复。漏掉的检查不补发，但下一轮会读取最新的作业状态，判断逻辑只看「当前时间与截止时间」，所以不会算错。

---

## 9. 隐私与安全

简要版：

- **账号密码与授权码用 Windows DPAPI 加密**，只有本机本账户能解密；
- 登录 Cookie、作业数据、日志、静默名单**全部存放在项目目录之外**；
- 项目目录里**不含任何**密码、Cookie 或个人作业数据，可安全分享；
- 程序只读取作业，不提交作业、不修改课程内容；
- 对外通信只有两条：登录一网畅学、通过你自己的 SMTP 发信给你自己。

完整的威胁模型、分享前检查清单、泄露后的处置步骤，见 [SECURITY.md](SECURITY.md)。

---

## 附：技术说明

- 平台识别：一网畅学基于 **TronClass**，认证走 Keycloak → CAS → ids6 统一身份认证；
- 抓取接口：
  - `GET /api/user/recently-visited-courses` — 课程列表
  - `GET /api/courses/{id}/homework-activities` — 作业与截止时间（`deadline`、`submitted`）
  - `GET /api/course/{id}/homework/submission-status` — 提交状态（`status_code`）
- 时间：接口返回 UTC，程序统一换算为北京时间（UTC+8）。

### 接入其他作业平台

代码已按平台插件化。一网畅学就是一个平台模块，新增平台不需要改抓取、提醒、托盘逻辑：

1. 新建模块（例如 `chaoxing.py`），提供：

| 属性 | 含义 |
|---|---|
| `KEY` | 凭据键名，如 `"chaoxing"` |
| `NAME` | 显示名，如 `"超星学习通"` |
| `HOME` | 平台首页 URL |
| `CREDS` | 需要填的账号字段，如 `[("user","手机号",False),("password","密码",True)]` |
| `load_creds()` | 返回账号 dict 或 `None`（未配置） |
| `fetch()` | 返回统一结构的作业列表 |

2. 在 `platforms.py` 的 `PLATFORMS` 列表里加上模块名。

之后 `config_tool.py --account` 会自动列出该平台，托盘菜单会出现对应入口，抓取结果与一网畅学合并计算提醒。
凭据分别存在 `secrets.dat` 的 `accounts.<KEY>` 下，互不干扰。

---

## 许可

本项目采用 [MIT License](LICENSE) 开源。

```
Copyright (c) 2026 USST Homework Reminder contributors

MIT License — 可自由使用、修改、分发，包括商业用途，唯一要求是保留版权声明和许可声明。
软件按「现状」提供，不附带任何担保。
```

> 说明：本项目仅供个人学习与自用。使用自动化程序访问学校平台前，请自行确认符合学校的相关规定；
> 因使用本程序导致的账号异常、数据问题等，作者不承担责任。
