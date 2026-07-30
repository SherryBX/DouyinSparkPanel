"""DouyinSparkPanel 控制面板后端。

替代原先的纯静态页面（python3 -m http.server），提供：
  * 统一登录鉴权（复用 newapi-checkin-panel 的 session 范式）
  * 粘贴 Cookie JSON 写入项目根目录 /.env
  * 配置读写、运行日志查看、手动执行

注意两处必须保持兼容的地方：
  1. /modules/*.sgmodule 必须继续免鉴权可访问 —— /opt/shadowrocket-rules 的
     定时任务会把订阅文件装到这里，Shadowrocket 客户端直接拉这个 URL。
  2. 写 COOKIES_* 时必须 ensure_ascii=True 且单行。消费端 utils/config.py:105 是
     `os.getenv(key).encode("utf-8").decode("unicode_escape")`，只有 \\uXXXX
     转义形式能正确还原非 ASCII；直接写 UTF-8 字节会被解成乱码。
"""

import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# --------------------------------------------------------------------------- 配置

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MODULES_DIR = BASE_DIR / "modules"

# 默认：panel/ 的上一级就是项目根（bot 与 panel 同仓）
# 可用环境变量 SPARKFLOW_DIR 覆盖（例如 /opt/DouyinSparkPanel）
SPARKFLOW_DIR = Path(os.getenv("SPARKFLOW_DIR") or BASE_DIR.parent).resolve()
TARGET_ENV = SPARKFLOW_DIR / ".env"
CRON_LOG = SPARKFLOW_DIR / "logs" / "cron.log"
RUNNER = SPARKFLOW_DIR / "run_douyin.sh"

# 1Panel 可选：没有则运行记录接口只返回空列表
ONEPANEL_DB = os.getenv("ONEPANEL_DB", "/opt/1panel/db/1Panel.db")
CRON_JOB_NAME = os.getenv("CRON_JOB_NAME", "抖音续火")

PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")
COOKIE_NAME = "panel_session"
SESSION_TTL = 7 * 24 * 3600

SESSION_COOKIE_NAMES = ("sessionid", "sessionid_ss", "sid_tt", "sid_guard", "uid_tt")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("panel")

app = FastAPI(title="DouyinSparkPanel 控制面板", docs_url=None, redoc_url=None)

# token -> 过期时间戳
SESSIONS: dict[str, float] = {}
SESSION_LOCK = threading.Lock()


# --------------------------------------------------------------------------- 鉴权


def _new_session() -> str:
    token = secrets.token_urlsafe(32)
    with SESSION_LOCK:
        now = time.time()
        # 顺手清理过期 token，避免无限增长
        for t in [t for t, exp in SESSIONS.items() if exp < now]:
            SESSIONS.pop(t, None)
        SESSIONS[token] = now + SESSION_TTL
    return token


def require_auth(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    with SESSION_LOCK:
        expires = SESSIONS.get(token or "")
        if expires is None or expires < time.time():
            SESSIONS.pop(token or "", None)
            raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return token  # type: ignore[return-value]


@app.post("/api/login")
def api_login(payload: dict, response: Response):
    if not PANEL_PASSWORD:
        raise HTTPException(status_code=500, detail="服务端未配置 PANEL_PASSWORD")
    if (payload or {}).get("password") != PANEL_PASSWORD:
        raise HTTPException(status_code=401, detail="密码错误")
    token = _new_session()
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=SESSION_TTL, httponly=True, samesite="lax", path="/",
    )
    return {"ok": True}


@app.post("/api/logout")
def api_logout(response: Response, token: str = Depends(require_auth)):
    with SESSION_LOCK:
        SESSIONS.pop(token, None)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/me")
def api_me(_: str = Depends(require_auth)):
    return {"ok": True}


# --------------------------------------------------------------------------- .env 读写


def read_env_text() -> str:
    if not TARGET_ENV.exists():
        return ""
    return TARGET_ENV.read_text(encoding="utf-8")


def parse_env(text: str) -> dict[str, str]:
    """极简 .env 解析。值不去引号 —— 该文件里的值本来就没有包引号。"""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value
    return out


def write_env_keys(updates: dict[str, str]) -> str:
    """就地更新指定 key，保留其余行原样。返回备份文件路径。

    值里的换行统一转成 \\n —— 消费端按单行读取。
    """
    text = read_env_text()
    backup = f"{TARGET_ENV}.bak.panel-{datetime.now():%Y%m%d-%H%M%S}"
    if TARGET_ENV.exists():
        shutil.copy2(TARGET_ENV, backup)

    lines = text.splitlines()
    remaining = dict(updates)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.partition("=")[0].strip()
        if key in remaining:
            value = str(remaining.pop(key)).replace("\r\n", "\\n").replace("\n", "\\n")
            lines[i] = f"{key}={value}"

    for key, value in remaining.items():
        value = str(value).replace("\r\n", "\\n").replace("\n", "\\n")
        lines.append(f"{key}={value}")

    TARGET_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("已写入 %s（备份 %s），更新 key: %s", TARGET_ENV, backup, list(updates))
    return backup


def decode_cookie_value(raw: str) -> list[dict]:
    """按消费端完全相同的方式解码 COOKIES_* 的值。"""
    if not raw:
        return []
    try:
        return json.loads(raw.encode("utf-8").decode("unicode_escape"))
    except Exception:  # noqa: BLE001
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return []


def encode_cookie_value(cookies: list[dict]) -> str:
    """序列化成消费端能正确还原的形式：单行 + ensure_ascii。

    ensure_ascii=True 产生 \\uXXXX 字面量，消费端的 unicode_escape 解码正好还原；
    若用 ensure_ascii=False，UTF-8 字节会被逐字节当 latin-1 解，直接变乱码。
    """
    return json.dumps(cookies, ensure_ascii=True, separators=(",", ":"))


def cookie_health(cookies: list[dict]) -> dict:
    """从 cookie 集合推断会话健康度。

    sid_guard 的值里编码了服务端签发时间与有效期，形如
    `<sessionid>|<签发时间戳>|<有效期秒>|<到期日文本>`，是最准的判断依据。
    """
    names = {c.get("name") for c in cookies}
    info: dict = {
        "count": len(cookies),
        "has_sessionid": "sessionid" in names,
        "issued_at": None,
        "expires_at": None,
        "days_left": None,
    }
    for cookie in cookies:
        if cookie.get("name") != "sid_guard":
            continue
        try:
            from urllib.parse import unquote

            parts = unquote(unquote(str(cookie.get("value", "")))).split("|")
            if len(parts) >= 3:
                issued, max_age = int(parts[1]), int(parts[2])
                info["issued_at"] = issued
                info["expires_at"] = issued + max_age
                info["days_left"] = round((issued + max_age - time.time()) / 86400, 1)
        except Exception:  # noqa: BLE001
            pass
        break
    return info


@app.get("/api/config")
def api_config(_: str = Depends(require_auth)):
    """返回当前配置。Cookie 只回统计与健康度，绝不回明文。"""
    env = parse_env(read_env_text())

    try:
        tasks = json.loads(env.get("TASKS", "[]") or "[]")
    except json.JSONDecodeError:
        tasks = []

    accounts = []
    for task in tasks:
        unique_id = task.get("unique_id", "")
        key = f"cookies_{unique_id}".upper()
        cookies = decode_cookie_value(env.get(key, ""))
        accounts.append({
            "username": task.get("username", ""),
            "unique_id": unique_id,
            "targets": task.get("targets", []),
            "cookies_key": key,
            "cookies": cookie_health(cookies),
        })

    return {
        "settings": {
            "messageTemplate": env.get("MESSAGE_TEMPLATE", ""),
            "hitokotoTypes": env.get("HITOKOTO_TYPES", "[]"),
            "matchMode": env.get("MATCH_MODE", "nickname"),
            "browserTimeout": env.get("BROWSER_TIMEOUT", "120000"),
            "friendListWaitTime": env.get("FRIEND_LIST_WAIT_TIME", "2000"),
            "taskRetryTimes": env.get("TASK_RETRY_TIMES", "3"),
            "logLevel": env.get("LOG_LEVEL", "Debug"),
        },
        "accounts": accounts,
        "env_path": str(TARGET_ENV),
    }


@app.put("/api/config")
def api_config_save(payload: dict, _: str = Depends(require_auth)):
    """保存基础配置与好友列表（不含 Cookie —— Cookie 只能通过扫码写入）。"""
    settings = (payload or {}).get("settings") or {}
    accounts = (payload or {}).get("accounts") or []

    updates: dict[str, str] = {}
    mapping = {
        "messageTemplate": "MESSAGE_TEMPLATE",
        "matchMode": "MATCH_MODE",
        "browserTimeout": "BROWSER_TIMEOUT",
        "friendListWaitTime": "FRIEND_LIST_WAIT_TIME",
        "taskRetryTimes": "TASK_RETRY_TIMES",
        "logLevel": "LOG_LEVEL",
    }
    for src, dst in mapping.items():
        if src in settings:
            updates[dst] = str(settings[src])

    if "hitokotoTypes" in settings:
        value = settings["hitokotoTypes"]
        if isinstance(value, str):
            value = json.loads(value or "[]")
        updates["HITOKOTO_TYPES"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    if accounts:
        tasks = [
            {
                "username": a.get("username", ""),
                "unique_id": a.get("unique_id", ""),
                "targets": [t for t in (a.get("targets") or []) if str(t).strip()],
            }
            for a in accounts
            if a.get("unique_id")
        ]
        updates["TASKS"] = json.dumps(tasks, ensure_ascii=False, separators=(",", ":"))

    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    backup = write_env_keys(updates)
    return {"ok": True, "backup": backup, "updated": sorted(updates)}



def parse_cookie_payload(raw):
    """兼容多种 Cookie 导出格式，统一成 list[dict]。

    支持：
      1. Cookie-Editor / EditThisCookie 数组
         [{"name":"sessionid","value":"...","domain":".douyin.com", ...}, ...]
      2. 名称-值映射对象
         {"sessionid":"...","sid_tt":"..."}
      3. 单个 cookie 对象
         {"name":"sessionid","value":"..."}
      4. document.cookie / 分号分隔
         "sessionid=...; sid_tt=..."
      5. 已是 list[dict]（JSON API 直传）
    """
    if raw is None or raw == "":
        raise ValueError("缺少 cookies")

    if isinstance(raw, list):
        parsed = raw
    elif isinstance(raw, dict):
        if "name" in raw and "value" in raw:
            parsed = [raw]
        else:
            # {name: value, ...}
            parsed = [
                {"name": str(k), "value": str(v), "domain": ".douyin.com", "path": "/"}
                for k, v in raw.items()
            ]
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("缺少 cookies")
        # 去掉可能的 JS 前缀
        if text.startswith("cookies =") or text.startswith("cookie ="):
            text = text.split("=", 1)[1].strip()
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            obj = None
        if obj is not None:
            return parse_cookie_payload(obj)
        # document.cookie / header 风格
        parsed = []
        for part in re.split(r";\s*", text):
            part = part.strip()
            if not part or "=" not in part:
                continue
            if part.lower().startswith(("path=", "domain=", "expires=", "max-age=", "secure", "httponly", "samesite=")):
                continue
            name, _, value = part.partition("=")
            parsed.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".douyin.com",
                "path": "/",
            })
        if not parsed:
            raise ValueError("Cookie JSON 解析失败")
    else:
        raise ValueError("cookies 格式不正确")

    cookies = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        # 兼容极少见的 Name/Value 大写字段
        name = item.get("name", item.get("Name"))
        value = item.get("value", item.get("Value"))
        if name is None or value is None:
            continue
        cookie = {
            "name": str(name),
            "value": str(value),
            "domain": str(item.get("domain") or item.get("Domain") or ".douyin.com"),
            "path": str(item.get("path") or item.get("Path") or "/"),
            "secure": bool(item.get("secure", item.get("Secure", True))),
        }
        if "httpOnly" in item:
            cookie["httpOnly"] = bool(item["httpOnly"])
        elif "HttpOnly" in item:
            cookie["httpOnly"] = bool(item["HttpOnly"])
        # Cookie-Editor 用 expirationDate（秒，可带小数）；Playwright 用 expires
        if "expirationDate" in item:
            try:
                cookie["expirationDate"] = float(item["expirationDate"])
                cookie["expires"] = float(item["expirationDate"])
            except (TypeError, ValueError):
                pass
        elif "expires" in item:
            try:
                cookie["expires"] = float(item["expires"])
            except (TypeError, ValueError):
                pass
        # sameSite：Cookie-Editor 常见 no_restriction / unspecified
        same = item.get("sameSite") or item.get("SameSite")
        if isinstance(same, str):
            low = same.lower()
            if low in ("no_restriction", "none"):
                cookie["sameSite"] = "None"
            elif low in ("lax", "strict"):
                cookie["sameSite"] = low.capitalize()
            # unspecified → 省略，让消费端默认
        cookies.append(cookie)

    if not cookies:
        raise ValueError("没有有效的 cookie 条目")
    return cookies


@app.post("/api/cookies")
def api_cookies_import(payload: dict, _: str = Depends(require_auth)):
    """手动导入 Cookie。兼容 Cookie-Editor / 映射对象 / document.cookie。"""
    unique_id = ((payload or {}).get("unique_id") or "").strip()
    raw = (payload or {}).get("cookies")
    if not unique_id:
        raise HTTPException(status_code=400, detail="缺少 unique_id")
    if not re.fullmatch(r"[A-Za-z0-9_]+", unique_id):
        raise HTTPException(status_code=400, detail="unique_id 只能包含字母、数字与下划线")

    try:
        cookies = parse_cookie_payload(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    health = cookie_health(cookies)
    if not health.get("has_sessionid") and not any(
        c["name"] in SESSION_COOKIE_NAMES for c in cookies
    ):
        raise HTTPException(
            status_code=400,
            detail="导入的 Cookie 里没有 sessionid / sid_tt / sid_guard，看起来不是已登录会话",
        )

    key = f"cookies_{unique_id}".upper()
    backup = write_env_keys({key: encode_cookie_value(cookies)})
    logger.info("手动导入 Cookie -> %s，共 %d 条", key, len(cookies))
    return {
        "ok": True,
        "key": key,
        "cookie_count": len(cookies),
        "health": health,
        "backup": backup,
    }



# --------------------------------------------------------------------------- 飞书通知


def get_feishu_webhook() -> str:
    env = parse_env(read_env_text())
    return (env.get("FEISHU_WEBHOOK") or "").strip()


@app.get("/api/notify")
def api_notify_get(_: str = Depends(require_auth)):
    return {"feishu_webhook": get_feishu_webhook()}


@app.put("/api/notify")
def api_notify_put(payload: dict, _: str = Depends(require_auth)):
    fw = str((payload or {}).get("feishu_webhook") or "").strip()
    if fw and not fw.startswith("http"):
        raise HTTPException(status_code=400, detail="webhook 应为 http(s) URL")
    backup = write_env_keys({"FEISHU_WEBHOOK": fw})
    return {"ok": True, "backup": backup, "feishu_webhook": fw}


@app.post("/api/notify/test")
def api_notify_test(_: str = Depends(require_auth)):
    fw = get_feishu_webhook()
    if not fw:
        raise HTTPException(status_code=400, detail="尚未配置 FEISHU_WEBHOOK")
    script = SPARKFLOW_DIR / "notify_run.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail="notify_run.py 不存在")
    try:
        proc = subprocess.run(
            ["/usr/bin/python3", str(script), "--test", "--webhook", fw],
            capture_output=True, text=True, timeout=30,
            cwd=str(SPARKFLOW_DIR),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"发送失败: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown error").strip()[-400:]
        raise HTTPException(status_code=500, detail=detail)
    return {"ok": True, "message": (proc.stdout or "").strip() or "已发送测试通知"}


# --------------------------------------------------------------------------- 运行日志


@app.get("/api/runs")
def api_runs(_: str = Depends(require_auth)):
    """运行索引取自 1Panel 的 job_records（含耗时/成败），输出取自 cron.log。

    注意 1Panel 每个任务只保留 7 条记录（retain_copies=7），且它自己那份
    stdout 日志是 0 字节 —— 因为 run_douyin.sh 自己做了 >> logs/cron.log 重定向。
    """
    runs = []
    try:
        con = sqlite3.connect(f"file:{ONEPANEL_DB}?mode=ro", uri=True)
        rows = con.execute(
            """SELECT r.start_time, r.interval, r.status, r.message
               FROM job_records r JOIN cronjobs c ON c.id = r.cronjob_id
               WHERE c.name = ? ORDER BY r.start_time DESC LIMIT 20""",
            (CRON_JOB_NAME,),
        ).fetchall()
        con.close()
        for start, interval, status, message in rows:
            runs.append({
                "start_time": start,
                "duration_s": round((interval or 0) / 1000, 1),
                "status": status,
                "message": message or "",
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 1Panel job_records 失败: %s", exc)

    return {"runs": runs, "schedule": read_cron_spec()}


@app.get("/api/logs")
def api_logs(limit: int = 3, _: str = Depends(require_auth)):
    """把 cron.log 按 job start / job end 哨兵切成块，返回最近几次。"""
    if not CRON_LOG.exists():
        return {"blocks": []}

    # 只读尾部，整个文件有 1MB+
    with CRON_LOG.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - 400_000))
        tail = fh.read().decode("utf-8", "replace")

    blocks, current = [], None
    for line in tail.splitlines():
        if "job start" in line:
            # 上一块还没收到 job end 就来了新的 start —— 说明那次运行崩了。
            # 必须先收下再开新块，否则失败记录会被静默丢弃。
            if current is not None:
                blocks.append(current)
            current = {"start": line.strip(), "end": None, "lines": []}
        elif current is not None:
            if "job end" in line:
                current["end"] = line.strip()
                blocks.append(current)
                current = None
            else:
                current["lines"].append(line.rstrip())
    if current is not None:          # 尾部未收尾 = 最后一次运行崩了或仍在跑
        blocks.append(current)

    picked = blocks[-max(1, min(limit, 10)):]
    for block in picked:
        lines = block["lines"]
        block["failed"] = block["end"] is None or any(
            m in ln for ln in lines for m in ("Traceback", "TimeoutError", "ERROR")
        )
        # 整块可能上万行 DEBUG，前端只需要够诊断的量
        block["total_lines"] = len(lines)
        block["lines"] = lines[-200:]
    picked.reverse()
    return {"blocks": picked}


def read_cron_spec() -> str:
    try:
        con = sqlite3.connect(f"file:{ONEPANEL_DB}?mode=ro", uri=True)
        row = con.execute("SELECT spec FROM cronjobs WHERE name=?", (CRON_JOB_NAME,)).fetchone()
        con.close()
        return row[0] if row else ""
    except Exception:  # noqa: BLE001
        return ""


# --------------------------------------------------------------------------- 手动执行

RUN_LOCK = threading.Lock()
RUN_STATE: dict = {"running": False, "started": None, "finished": None,
                   "returncode": None, "tail": ""}


def run_task_worker() -> None:
    try:
        proc = subprocess.run(
            ["bash", str(RUNNER)],
            capture_output=True, text=True, timeout=900,
            cwd=str(SPARKFLOW_DIR),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        with RUN_LOCK:
            RUN_STATE.update(running=False, finished=time.time(),
                             returncode=proc.returncode, tail=out[-4000:])
    except subprocess.TimeoutExpired:
        with RUN_LOCK:
            RUN_STATE.update(running=False, finished=time.time(),
                             returncode=-1, tail="执行超时（15 分钟）")
    except Exception as exc:  # noqa: BLE001
        with RUN_LOCK:
            RUN_STATE.update(running=False, finished=time.time(),
                             returncode=-1, tail=f"{type(exc).__name__}: {exc}")


@app.post("/api/run")
def api_run(_: str = Depends(require_auth)):
    with RUN_LOCK:
        if RUN_STATE["running"]:
            raise HTTPException(status_code=409, detail="任务正在运行中")
        RUN_STATE.update(running=True, started=time.time(),
                         finished=None, returncode=None, tail="")
    threading.Thread(target=run_task_worker, daemon=True).start()
    return {"ok": True}


@app.get("/api/run")
def api_run_status(_: str = Depends(require_auth)):
    with RUN_LOCK:
        return dict(RUN_STATE)


# --------------------------------------------------------------------------- 静态资源

# 免鉴权：Shadowrocket 订阅由客户端直接拉取，不能要求登录
if MODULES_DIR.is_dir():
    app.mount("/modules", StaticFiles(directory=str(MODULES_DIR)), name="modules")


@app.get("/api/health")
def api_health():
    return {"ok": True, "env_exists": TARGET_ENV.exists()}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.exception_handler(HTTPException)
def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
