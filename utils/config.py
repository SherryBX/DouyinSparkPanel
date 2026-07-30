import os, sys
from enum import Enum
import json
import logging
from utils.logger import setup_logger
from utils import norm

logger = setup_logger(level=logging.DEBUG)

DEBUG = True
config = None
userData = None


class Environment(Enum):
    GITHUBACTION = "GITHUB_ACTION"
    LOCAL = "LOCAL"
    PACKED = "PACKED"

    def __str__(self):
        return self.value


def get_environment():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Environment.PACKED
    elif os.getenv("GITHUB_ACTIONS") == "true":
        return Environment.GITHUBACTION
    else:
        return Environment.LOCAL


def get_config():
    global config

    if config:
        return config

    config = {
        "proxyAddress": os.getenv("PROXY_ADDRESS", ""),
        "messageTemplate": os.getenv(
            "MESSAGE_TEMPLATE",
            "[盖瑞]今日火花[加一]\n—— [右边] 每日一言 [左边] ——\n[API]",
        ),
        "hitokotoTypes": json.loads(
            os.getenv("HITOKOTO_TYPES", '["文学","影视","诗词","哲学"]')
        ),
        "matchMode": os.getenv("MATCH_MODE", "nickname"),
        "browserTimeout": int(os.getenv("BROWSER_TIMEOUT", "120000")),
        "friendListTimeout": int(os.getenv("FRIEND_LIST_WAIT_TIME", "2000")),
        "taskRetryTimes": int(os.getenv("TASK_RETRY_TIMES", "3")),
        "logLevel": os.getenv("LOG_LEVEL", "DEBUG"),
    }

    return config


def sanitize_cookies(cookies):
    normalized = []
    for cookie in cookies:
        item = dict(cookie)
        if "sameSite" in item:
            item.pop("sameSite")
        normalized.append(item)
    return normalized


def scope_cookies_for_domain(cookies, domain):
    scoped = []
    for cookie in cookies:
        item = {
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": domain,
            "path": cookie.get("path", "/"),
            "secure": cookie.get("secure", True),
        }
        if "expires" in cookie:
            item["expires"] = cookie["expires"]
        if "httpOnly" in cookie:
            item["httpOnly"] = cookie["httpOnly"]
        same_site = cookie.get("sameSite")
        if same_site in ("Lax", "None", "Strict"):
            item["sameSite"] = same_site
        scoped.append(item)
    return scoped


def get_userData():
    global userData

    if userData:
        return userData

    tasks = json.loads(os.getenv("TASKS", "[]"))
    userData = []

    for task in tasks:
        username = task.get("username", "未知用户")
        unique_id = task.get("unique_id")
        if not unique_id:
            logger.warning(f"{username} 的任务 缺少 unique_id 字段，已跳过")
            continue
        cookies_key = f"cookies_{unique_id}".upper()
        cookies_str = os.getenv(cookies_key, "").encode("utf-8").decode("unicode_escape")
        if not cookies_str:
            logger.warning(f"{username} 的任务 缺少 {cookies_key} 环境变量，已跳过")
            continue
        try:
            cookies = json.loads(cookies_str)
        except json.JSONDecodeError:
            logger.warning(f"{username} 的任务 {cookies_key} 格式不正确，已跳过")
            continue

        userData.append(
            {
                "unique_id": unique_id,
                "username": username,
                "cookies": sanitize_cookies(cookies),
                "targets": [norm(t) for t in task.get("targets", [])],
            }
        )

    return userData
