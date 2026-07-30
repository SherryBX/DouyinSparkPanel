#!/usr/bin/env python3
"""抖音续火运行结果 → 飞书自定义机器人 Webhook。

参考 /opt/newapi-checkin/utils/notify.py 的 interactive 卡片风格，
用标准库 urllib 发送，不引入 httpx 依赖。

用法:
  python3 notify_run.py                 # 解析 cron.log 最近一次，按结果推送
  python3 notify_run.py --rc 0          # 附带进程退出码
  python3 notify_run.py --test          # 发送测试卡片
  python3 notify_run.py --dry-run       # 只打印 payload，不发送
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ENV_PATH = PROJECT_DIR / ".env"
CRON_LOG = PROJECT_DIR / "logs" / "cron.log"


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        out[k.strip()] = v
    return out


def plain(content: str) -> dict:
    return {"tag": "plain_text", "content": content}


def build_feishu_card(
    title: str,
    time_info: str,
    items: list[str],
    success_count: int,
    total_count: int,
    extra_notes: list[str] | None = None,
    theme: str | None = None,
) -> dict:
    if theme is None:
        if total_count <= 0:
            theme = "red" if success_count <= 0 else "orange"
        elif success_count == total_count:
            theme = "green"
        elif success_count > 0:
            theme = "orange"
        else:
            theme = "red"

    if total_count <= 0:
        status_line = "失败" if success_count <= 0 else "完成"
    elif success_count == total_count:
        status_line = "全部成功"
    elif success_count > 0:
        status_line = "部分成功"
    else:
        status_line = "全部失败"

    elements: list[dict] = [
        {"tag": "div", "text": plain("执行时间")},
        {"tag": "note", "elements": [plain(time_info)]},
        {"tag": "hr"},
        {"tag": "div", "text": plain("结果概览")},
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": plain("成功")},
                {"is_short": True, "text": plain(f"{success_count}/{total_count}")},
                {"is_short": True, "text": plain("失败")},
                {"is_short": True, "text": plain(f"{max(total_count - success_count, 0)}/{total_count}")},
                {"is_short": True, "text": plain("状态")},
                {"is_short": True, "text": plain(status_line)},
            ],
        },
    ]

    if items:
        elements.extend([
            {"tag": "hr"},
            {"tag": "div", "text": plain("明细")},
        ])
        for item in items:
            # 支持 "成功|好友名|正文" 或纯文本
            if "|" in item:
                parts = item.split("|", 2)
                status = parts[0].strip() or "信息"
                name = parts[1].strip() if len(parts) > 1 else ""
                body = parts[2].strip() if len(parts) > 2 else ""
            else:
                status, name, body = "信息", item, ""
            elements.append({
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": plain(name or "-")},
                    {"is_short": True, "text": plain(status)},
                ],
            })
            if body:
                elements.append({"tag": "note", "elements": [plain(body[:500])]})

    if extra_notes:
        elements.append({"tag": "hr"})
        for note in extra_notes:
            if note:
                elements.append({"tag": "note", "elements": [plain(note[:500])]})

    elements.extend([
        {"tag": "hr"},
        {"tag": "div", "text": plain("来源")},
        {"tag": "note", "elements": [plain("DouyinSparkPanel · DouYinSparkFlow 二开")]},
    ])

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": theme,
                "title": plain(title),
            },
            "elements": elements,
        },
    }


def send_feishu(webhook: str, payload: dict) -> None:
    if not webhook:
        raise ValueError("FEISHU_WEBHOOK 未配置")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Feishu HTTP {exc.code}: {err[:300]}") from exc

    raw = (raw or "").strip()
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Feishu 返回非 JSON: {raw[:300]}") from exc
    code = data.get("code", data.get("StatusCode", 0))
    if code != 0:
        raise RuntimeError(f"Feishu 返回错误: {raw[:500]}")


def parse_last_job(log_path: Path = CRON_LOG) -> dict:
    """从 cron.log 解析最近一次 job 块。"""
    result = {
        "time_info": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sent": [],
        "targets_total": 0,
        "failed": False,
        "error": "",
        "username": "",
        "raw_tail": [],
    }
    if not log_path.exists():
        result["failed"] = True
        result["error"] = "cron.log 不存在"
        return result

    with log_path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - 300_000))
        tail = fh.read().decode("utf-8", "replace")

    blocks: list[dict] = []
    current = None
    for line in tail.splitlines():
        if "job start" in line:
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
    if current is not None:
        blocks.append(current)
    if not blocks:
        result["failed"] = True
        result["error"] = "日志里没有找到 job 记录"
        return result

    block = blocks[-1]
    m = re.search(r"\[(.*?)\]", block.get("start") or "")
    if m:
        result["time_info"] = m.group(1)

    sent: list[str] = []
    errors: list[str] = []
    for line in block["lines"]:
        m = re.search(r"账号\s+(\S+)\s+已向好友\s+(\S+)\s+发送消息", line)
        if m:
            result["username"] = result["username"] or m.group(1)
            friend = m.group(2)
            if friend not in sent:
                sent.append(friend)
            continue
        m = re.search(r"目标数=(\d+)", line)
        if m:
            result["targets_total"] = max(result["targets_total"], int(m.group(1)))
            continue
        m = re.search(r"开始处理账号\s+(\S+)", line)
        if m:
            result["username"] = result["username"] or m.group(1)
        if "Traceback" in line or "TimeoutError" in line or "Error:" in line or "ERROR" in line:
            result["failed"] = True
            if "TimeoutError" in line or "Error" in line or "ERROR" in line:
                errors.append(line.split(" - ")[-1][:200])

    if block.get("end") is None:
        result["failed"] = True
        if not errors:
            errors.append("任务未正常结束（无 job end）")

    result["sent"] = sent
    if not result["targets_total"]:
        # 回退：从 .env TASKS 读
        try:
            env = load_env()
            tasks = json.loads(env.get("TASKS") or "[]")
            total = sum(len(t.get("targets") or []) for t in tasks)
            result["targets_total"] = total
        except Exception:
            result["targets_total"] = len(sent)

    result["error"] = " | ".join(dict.fromkeys(errors))[:400]
    result["raw_tail"] = block["lines"][-30:]
    return result


def summarize(job: dict, rc: int | None) -> tuple[str, dict]:
    sent = job.get("sent") or []
    total = int(job.get("targets_total") or 0)
    success = len(sent)
    failed = bool(job.get("failed")) or (rc not in (None, 0))
    if failed and success == 0:
        success_count = 0
    else:
        success_count = success
        # 若进程非 0 但发过消息，按部分成功
        if failed and success > 0 and total > success:
            pass
        elif failed and success > 0 and total <= success:
            total = success  # 避免 5/5 却标失败；用 extra note 说明 rc
            # 仍用 orange if rc bad? keep green if all sent
            failed = rc not in (None, 0) and success < max(total, 1)

    items = [f"成功|{name}|已发送续火消息" for name in sent]
    if job.get("error"):
        items.append(f"失败|错误|{job['error']}")
    if rc not in (None, 0) and not any(i.startswith("失败|") for i in items):
        items.append(f"失败|进程|退出码 {rc}")

    extra = []
    if job.get("username"):
        extra.append(f"账号: {job['username']}")
    if rc is not None:
        extra.append(f"退出码: {rc}")

    if total <= 0 and success_count > 0:
        total = success_count
    if total <= 0 and failed:
        total = 1
        success_count = 0

    title = "抖音续火"
    if success_count == total and total > 0 and rc in (None, 0) and not job.get("error"):
        title = "抖音续火成功"
    elif success_count > 0:
        title = "抖音续火部分成功"
    else:
        title = "抖音续火失败"

    payload = build_feishu_card(
        title=title,
        time_info=job.get("time_info") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        items=items,
        success_count=success_count,
        total_count=total,
        extra_notes=extra,
    )
    return title, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="推送抖音续火结果到飞书")
    parser.add_argument("--rc", type=int, default=None, help="主任务退出码")
    parser.add_argument("--test", action="store_true", help="发送测试卡片")
    parser.add_argument("--dry-run", action="store_true", help="只打印不发送")
    parser.add_argument("--webhook", default="", help="覆盖 FEISHU_WEBHOOK")
    args = parser.parse_args(argv)

    env = load_env()
    # 也允许系统环境变量覆盖
    webhook = (args.webhook or os.getenv("FEISHU_WEBHOOK") or env.get("FEISHU_WEBHOOK") or "").strip()

    if args.test:
        payload = build_feishu_card(
            title="抖音续火 · 测试通知",
            time_info=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            items=["成功|测试|飞书 Webhook 连通正常"],
            success_count=1,
            total_count=1,
            extra_notes=["来自 DouyinSparkPanel"],
            theme="blue",
        )
        title = "测试通知"
    else:
        job = parse_last_job()
        title, payload = summarize(job, args.rc)

    if args.dry_run or not webhook:
        print(json.dumps({"title": title, "webhook_set": bool(webhook), "payload": payload},
                         ensure_ascii=False, indent=2))
        if not webhook:
            print("FEISHU_WEBHOOK 未配置，跳过发送", file=sys.stderr)
            return 0
        if args.dry_run:
            return 0

    try:
        send_feishu(webhook, payload)
        print(f"[Feishu] 推送成功: {title}")
        return 0
    except Exception as exc:
        print(f"[Feishu] 推送失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
