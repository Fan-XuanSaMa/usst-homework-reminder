# 上理作业提交提醒

> 一个住在你电脑里的 DDL 守门员。
> 它替你登录一网畅学，把「快截止又没交」的作业打包成一封邮件，每天最多喊你一次。

## 它能干什么

| 它会 | 它不会 |
|---|---|
| 自动登录，省得你每天输密码 | 帮你写作业 |
| 翻遍课程，找出没交又快到期的作业 | 帮你交作业 |
| 发一封汇总邮件到你邮箱 | 把数据传到第三方服务器 |
| 在托盘里蹲着，图标变红表示有情况 | 半夜夺命连环催（24 小时最多一封） |
| 登录失败时发故障邮件 | 假装自己没失败 |

程序只读作业信息，不改课程、不提交任何东西。

## 三分钟装好

需要 Windows 10/11、Python 3.10+，以及 Edge 或 Chrome（有一个就行，不用另装浏览器）。

```bat
git clone https://github.com/Fan-XuanSaMa/usst-homework-reminder.git
cd usst-homework-reminder
pip install playwright pystray pillow

python config_tool.py --account    # 学号 + 密码
python tronclass.py                # 试抓一次，确认账号没问题
python config_tool.py --email      # 发件邮箱 + 授权码
python remind.py --test-email      # 试发一封
python install.py                  # 托盘 + 开机自启
```

| 步骤 | 成功的样子 |
|---|---|
| `--account` | 只问学号、密码。输密码时屏幕没反应是正常的，不是卡了 |
| `tronclass.py` | 打印「抓到 N 个作业」。N=0 也别急着骂程序，可能老师真没布置 |
| `--email` | 只问发件邮箱、授权码、收件邮箱。收件邮箱直接回车，就等于发件邮箱 |
| `--test-email` | 邮箱收到测试信。没收到先翻垃圾箱，QQ 邮箱对谁都一样严格 |
| `install.py` | 任务栏右下角多一个蓝色图标 |

> 没配完就跑 `install.py`，它会直接告诉你还缺哪一步，不用猜。
> 提示「找不到可用浏览器」时，执行 `python -m playwright install chromium`。

## 它什么时候会烦你

一句话：**5 天内要交、还没交，每天一封汇总；其他情况闭嘴。**

| 作业情况 | 提醒吗 |
|---|---|
| 没交，距离截止 5 天以内 | ✅ 每天一封 |
| 没交，距离截止还早 | ❌ 等进入 5 天窗口再说 |
| 没交，但已经过了截止 | ❌ 过期不候，提醒也没用 |
| 已经交了 | ❌ 不邀功 |
| 老师发了但还没设截止时间 | ✅ 下一封里列为「新作业」 |
| 在静默名单里 | ❌ 你说了算 |

频率是**滚动 24 小时最多一封**。23:50 收到一封，第二天 00:05 不会再来一封——它不按自然日算，别想卡它 bug。

一封邮件大概长这样：

```
主题：[作业提醒] 2 个作业即将截止

【即将截止】
[某门课程] 第二次作业
    截止：11月08日 23:59（剩余 4 天 3 小时）
    https://1906.usst.edu.cn/course/000000/homework/000000

[另一门课程] 第三次作业
    截止：11月06日 18:00（剩余 1 天 21 小时）
    https://1906.usst.edu.cn/course/000000/homework/000000

—— 上理作业提醒（每天一封）
```

想改提醒窗口和检查频率，编辑项目里的 `config.json`：

| 字段 | 默认 | 含义 |
|---|---|---|
| `remind_days_before` | `5` | 提前几天开始提醒，改 `3` 就是只提醒最后 3 天 |
| `check_interval_minutes` | `15` | 多久看一次。只影响发现新作业的快慢，不增加邮件数量 |

## 配置：账号和邮箱各管各的

以前是一个大问卷，现在拆成两个小开关：

| 想配什么 | 命令 |
|---|---|
| 学号 / 密码 | `python config_tool.py --account` |
| 发件邮箱 / 授权码 / 收件邮箱 | `python config_tool.py --email` |
| 看看配成什么样（自动打码） | `python config_tool.py --show` |

只改邮箱不会动账号，只改账号也不会动邮箱。不带参数运行 `python config_tool.py`，它只问还缺的那一项，已经配好的不重复盘问。

配置存在两个地方：

| 内容 | 位置 |
|---|---|
| 提醒天数、检查间隔 | 项目目录 `config.json`（可以随便看） |
| 账号、授权码、邮箱 | `%APPDATA%\usst-homework-reminder\secrets.dat`（DPAPI 加密） |

`secrets.dat` 只有当前 Windows 账户能解开。拷到别的电脑、换个账户、重装系统，都会变成一堆无法解读的字节——这不是 bug，是设计。

账号按平台分开存，以后接别的平台也不会打架：

```
secrets.dat
├── accounts
│   └── usst       ← 一网畅学的学号 / 密码
└── email          ← 发件邮箱 / 授权码 / 收件邮箱 / 服务器
```

`--show` 的输出长这样，敏感项全是星号：

```
== 作业平台账号 ==
  一网畅学  ： 253****118  密码 03*****cf（9 位）

== 提醒邮箱 ==
  发件邮箱： ab****@qq.com
  授权码  ： ab************cd
  服务器  ： smtp.qq.com 465
```

想清空：

```bat
python config_tool.py --reset-account   # 只清账号和登录状态
python config_tool.py --reset-email     # 只清邮箱
python config_tool.py --reset           # 全清，从头再来
```

从旧版本升级：旧明文配置会在 `install.py` 首次运行时自动迁移，也可以手动 `python config_tool.py --import`。旧的 `secrets.dat` 读取时会自动升级结构，不用重新输密码。

## 邮箱授权码：全流程最容易卡的一步

大部分邮箱不让你用登录密码发信，得单独申请一个「授权码」。它不是密码，忘了可以重新生成，旧的立刻作废。

### QQ 邮箱（推荐）

1. 登录 [mail.qq.com](https://mail.qq.com)
2. **设置** → **账号**（新版是「账号与安全」→「安全设置」）
3. 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」
4. 开启 **POP3/SMTP服务** 或 **IMAP/SMTP服务**
5. 按提示发短信验证，页面给你 16 位授权码（形如 `abcdabcdabcdabcd`，没有空格）
6. 运行 `python config_tool.py --email`，填发件邮箱、授权码，收件邮箱直接回车

服务器和端口不用填，程序按邮箱域名自动识别（QQ → `smtp.qq.com:465`）。

### 163 邮箱

登录 [mail.163.com](https://mail.163.com)，**设置** → **POP3/SMTP/IMAP**，开启 SMTP 服务并设置授权密码。然后同样跑 `--email`。

### 学校邮箱

先确认学校邮箱开不开 SMTP。开的话，服务器通常是 `smtp.` + 邮箱域名，端口 465。不确定就问信息办，别问程序。

### 发不出去时

| 报错 | 大概率是 |
|---|---|
| `Authentication failed` / `535` | 授权码错了，或者 SMTP 服务压根没开 |
| `Connection refused` / 超时 | 端口被网络挡了，换手机热点试试 |
| `UnicodeEncodeError` | 授权码里混了中文或全角字符，重新复制 |

## 日常使用

托盘图标右键，能干这些：

| 菜单项 | 作用 |
|---|---|
| 未提交 N 个 | 只显示，点不动 |
| 作业名（剩 X 天） | 点一下直接打开作业页面 |
| 立即检查 | 马上查一轮（不会强行发信） |
| 打开一网畅学 | 打开课程首页 |
| 查看日志 | 用记事本打开运行记录 |
| 编辑静默名单 | 打开静默规则文件 |
| 静音到明天 8:00 | 今天彻底闭嘴 |
| 退出 | 停止程序 |

图标颜色：**蓝色** = 暂时安全；**红色** = 5 天内有未交作业，该动了。

常用命令：

| 想做 | 命令 |
|---|---|
| 只看抓到了什么 | `python tronclass.py` |
| 预览邮件但不发 | `python remind.py --dry-run` |
| 正常检查并发信 | `python remind.py` |
| 单独测邮箱 | `python remind.py --test-email` |
| 停掉托盘 | `python install.py --stop` |
| 取消开机自启 | `python install.py --uninstall` |

### 不想被某个作业烦

托盘右键 → **编辑静默名单**。一行一条规则，空格隔开的词得**全部命中**才生效：

```
# 只静默这门课的第三次作业
某门课程 第三次

# 静默这门课的所有作业
某门课程

# 静默所有实验课
实验
```

删掉那一行就恢复提醒，不用重启，下一轮检查生效。

### 看它最近干了什么

托盘右键 → **查看日志**，或者直接打开 `%APPDATA%\usst-homework-reminder\reminder.log`。

每轮一行，例如：

```
2026-11-04 16:48 检查完成：共 7 个作业，未提交 6 个（5 天内 3，无截止 0），静默 0 个，发送 0 封，距上次提醒不足 24 小时，今天不再发送
```

## 出问题了

| 现象 | 怎么办 |
|---|---|
| 收到「系统故障」邮件 | 密码改了 → `--account` 重填；学校页面改版 → 手动登录看看要不要验证码；网络抽风 → 等 15 分钟自动重试 |
| 提示「尚未保存账号密码」 | `python config_tool.py --account` |
| 提示「尚未配置提醒邮箱」 | `python config_tool.py --email`（只影响发信，不影响抓取） |
| 提示「无法读取凭据文件」 | 换了电脑 / 账户 / 系统，解不开了。`--reset-account` 后重新 `--account` |
| 抓取正常但作业数是 0 | 先上网页确认老师真布置了；网页有而程序没有，跑 `python tronclass.py` 看报错 |
| 托盘图标不见了 | 任务管理器看有没有 `pythonw.exe`；启动文件夹里有没有 `usst_homework_reminder.vbs`；没有就重跑 `install.py` |
| 关机 / 睡眠错过检查 | 不补发。醒来后看的是最新状态，不会拿旧数据吓你 |

## 隐私：你的密码不归我管

- 账号和授权码用 **Windows DPAPI** 加密，只有这台电脑的这个 Windows 账户能解开；
- Cookie、作业数据、日志、静默名单全在 `%APPDATA%`，不在项目目录；
- 项目目录里没有任何密码、Cookie 或个人作业数据，可以直接分享；
- 对外只连两个地方：一网畅学，和你自己的 SMTP 服务器。没有中间商。

更完整的威胁模型和泄露处置，见 [SECURITY.md](SECURITY.md)。

## 文件都在哪

项目目录（可以分享）：

| 文件 | 作用 |
|---|---|
| `tronclass.py` | 登录 + 抓一网畅学的作业 |
| `platforms.py` | 平台注册表，决定启用哪些平台 |
| `remind.py` | 判断该不该提醒 + 发邮件 |
| `tray.py` | 托盘常驻 |
| `install.py` | 安装、停止、卸载 |
| `config_tool.py` | 配置工具 |
| `paths.py` / `secrets_store.py` | 路径管理 / DPAPI 读写 |
| `config.json` | 提醒天数、检查间隔（无账号密码） |
| `README.md` / `SECURITY.md` / `LICENSE` | 你现在看的这些 |

个人数据目录（**不要分享**）：`%APPDATA%\usst-homework-reminder\`

| 文件 | 内容 |
|---|---|
| `secrets.dat` | 账号、密码、邮箱、授权码（加密） |
| `browser_state.json` | 登录 Cookie，等于登录态 |
| `_browser_raw.json` | 抓到的课程和作业 |
| `sent_log.json` | 发送记录，用来保证每天一封 |
| `mute.txt` | 静默名单（可能含课程名） |
| `reminder.log` | 运行日志 |
| `daemon.pid` / `daemon.stop` / `mute.until` | 运行控制 |

## 想接别的作业平台？

一网畅学只是 `platforms.py` 里的一个条目。新增平台：写一个模块，提供 `KEY`、`NAME`、`HOME`、`CREDS`、`load_creds()`、`fetch()`，再把模块名加进 `PLATFORMS` 列表。配置工具、托盘、提醒逻辑都不用改。

细节看代码里的注释，或者直接照抄 `tronclass.py`。

## 给好奇的人：技术细节

- 一网畅学底层是 **TronClass**，认证走 Keycloak → CAS → ids6；
- 用到的接口：
  - `GET /api/user/recently-visited-courses` — 课程列表
  - `GET /api/courses/{id}/homework-activities` — 作业和截止时间
  - `GET /api/course/{id}/homework/submission-status` — 提交状态
- 接口返回 UTC，程序统一换成北京时间（UTC+8）。

## 许可

[MIT License](LICENSE)。保留版权声明和许可声明，随便用、随便改，商用也行。

```
Copyright (c) 2026 USST Homework Reminder contributors
```

> 仅供个人学习自用。用自动化程序访问学校平台前，先确认符合学校规定。因使用本程序导致的账号异常、数据问题，作者不背锅——毕竟它连作业都不帮你交。
