# -*- coding: utf-8 -*-
"""作业平台注册表。

每个平台对应一个模块，提供：
    KEY      凭据里的键名（accounts[KEY]）
    NAME     显示名
    HOME     平台首页
    CREDS    需要填写的字段 [(键, 提示, 是否隐藏输入)]
    load_creds() -> dict|None   读凭据，缺失返回 None
    fetch()                     抓取作业，返回统一结构

新增平台只需：写一个模块 + 在 PLATFORMS 里登记一行，
账号配置、抓取、提醒、托盘都不用改。
"""
import importlib

# 当前启用的平台。接入新平台时往这里追加模块名即可。
PLATFORMS = ["tronclass"]


class NotConfigured(RuntimeError):
    """尚未保存账号密码。属于正常状态，不触发故障告警。"""


def enabled():
    """返回已启用平台的模块列表（导入失败的直接跳过）。"""
    out = []
    for name in PLATFORMS:
        try:
            out.append(importlib.import_module(name))
        except Exception as e:  # 平台模块坏了不应拖垮整个程序
            print(f"（平台 {name} 加载失败：{type(e).__name__}: {e}）")
    return out


def configured():
    """返回已经配好账号的平台模块。"""
    out = []
    for m in enabled():
        try:
            if m.load_creds():
                out.append(m)
        except Exception:
            continue
    return out


def get(key):
    for m in enabled():
        if getattr(m, "KEY", "") == key:
            return m
    return None
