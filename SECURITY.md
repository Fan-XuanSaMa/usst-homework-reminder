# 安全说明

本项目要在本机保存你的**校园账号密码**和**邮箱授权码**，并持有登录后的会话凭证。
下面说明它们存在哪里、如何保护，以及分享代码时哪些东西绝对不能外传。

---

## 1. 数据存在哪里

代码与个人数据**分离存放**：

| 内容 | 位置 | 保护方式 |
|---|---|---|
| 源码、README、LICENSE | 项目目录 | 可自由分享 |
| 各平台账号（按平台分组） | `%APPDATA%\usst-homework-reminder\secrets.dat` → `accounts.<平台>` | **Windows DPAPI 加密** |
| 发件邮箱、SMTP 授权码、收件人 | 同上文件 → `email` | **Windows DPAPI 加密** |
| 登录 Cookie | `%APPDATA%\usst-homework-reminder\browser_state.json` | 目录 ACL 仅当前用户 |
| 抓取到的课程与作业数据 | `%APPDATA%\usst-homework-reminder\_browser_raw.json` | 目录 ACL 仅当前用户 |
| 发送记录、运行日志、静默名单 | 同上目录 | 目录 ACL 仅当前用户 |

> `%APPDATA%` 通常展开为 `C:\Users\<你的用户名>\AppData\Roaming`。

数据目录在创建时会执行 `icacls /inheritance:r /grant:r <当前用户>:F`，
去掉继承权限，只保留当前 Windows 账户可读。

---

## 2. DPAPI 加密意味着什么

`secrets.dat` 使用 Windows 内置的 **DPAPI（数据保护 API）**、以当前用户身份加密：

- ✅ **拷到别的电脑** → 解不开；
- ✅ **被同一台电脑的其他 Windows 账户读取** → 解不开；
- ✅ **重装系统 / 重设账户密钥后** → 解不开（需要重新运行 `python config_tool.py --account` 和 `--email`）；
- ⚠️ **同一账户下有恶意程序运行** → 能调用同样的 API 解密。这是操作系统层面的边界，任何本地程序都无法超越。

因此它的实际效果是：**文件泄露 ≠ 密码泄露**。哪怕 `secrets.dat` 被发到网上，别人也拿不到你的密码。

---

## 3. 分享代码前必须检查的清单

### 绝对不要外传

| 文件 | 风险 |
|---|---|
| `%APPDATA%\usst-homework-reminder\` 整个目录 | 凭据 + 会话 + 个人作业数据 |
| `browser_state.json` | 里面的 Cookie **等同于已登录**，可直接冒充你操作平台 |
| `_browser_raw.json` | 你的全部课程、作业、提交状态 |
| `config.json`（若曾被你在旧版本中填过账号） | 旧版本为明文 |

### 发布到 GitHub 前的自检

```bat
:: 在项目目录执行，应全部输出「已忽略」
git check-ignore -v config.json
git check-ignore -v browser_state.json
git check-ignore -v secrets.dat
git check-ignore -v reminder.log

:: 查看实际将被提交的文件，逐个人工确认
git add -A --dry-run
```

### 已经公开过怎么办

1. 立即修改统一身份认证密码；
2. 重新生成邮箱 SMTP 授权码（旧码失效）；
3. 运行 `python config_tool.py --reset` 清除本机会话，再重新 `--account` 和 `--email`；
4. 若 `browser_state.json` 泄露过，第 1 步的改密码会使其立即失效。

---

## 4. 运行时的安全边界

| 项目 | 说明 |
|---|---|
| 对外网络通信 | 仅两条：登录 `1906.usst.edu.cn`，以及通过你自己的 SMTP 发信给你自己。无任何第三方服务器 |
| 上传 | 程序**只读**作业信息，不提交作业、不修改课程 |
| 日志 | 不记录密码、授权码、Cookie。`--show` 输出一律打码 |
| 命令行历史 | `config_tool.py` 用 `getpass` 读密码，**不进** cmd 历史文件 |
| 临时文件 | 写入使用临时文件 + 原子替换，失败不会留下半截数据 |

---

## 5. 已修复的历史问题

| 问题 | 状态 |
|---|---|
| 账号密码明文存在项目目录 `config.json` | ✅ 已迁移至 DPAPI 加密存储，项目内已清除 |
| 登录 Cookie 明文存在项目目录 | ✅ 已移至 `%APPDATA%` 并收紧 ACL |
| 个人作业数据存在项目目录 | ✅ 已移出 |
| README 中出现本地绝对路径与真实课程名 | ✅ 已脱敏 |
| 数据目录可被同机其他账户读取 | ✅ 已设置仅当前用户 ACL |

---

## 6. 报告安全问题

如果你发现本项目的安全问题，请通过仓库的 Issue 联系，**不要在公开 Issue 中附带任何真实凭据或 Cookie**。
