# DouyinSparkPanel

> **DouYinSparkFlow 二开** · 抖音网页版好友「火花」自动续火  
> 在上游脚本之上增加 **Web 控制面板**、**飞书 Webhook 通知** 与更易自托管的部署方式。

本仓库由 [SherryBX](https://github.com/SherryBX) 维护，基于开源项目 **DouYinSparkFlow** 二次开发。

## 致谢 / Tribute

核心自动化能力致敬并继承自上游：

- **原项目 / Upstream**：[2061360308/DouYinSparkFlow](https://github.com/2061360308/DouYinSparkFlow)
- 感谢原作者提供 Playwright 续火脚本、`TASKS` + `COOKIES_<UNIQUE_ID>` 配置结构、聊天页就绪检测等基础实现。

**DouyinSparkPanel = DouYinSparkFlow 的二开增强版**（控制面板 + 通知 + 运维整合），**不是**上游官方仓库。若你只需要 GitHub Actions 开箱即用或原版能力，请优先使用 / Star 上游项目。

## 功能

| 模块 | 说明 |
| --- | --- |
| 续火脚本 | Playwright 打开抖音网页聊天，按好友列表发送模板消息（支持每日一言） |
| 控制面板 | FastAPI + 静态前端：登录鉴权、粘贴 Cookie、改配置/好友、看日志、一键执行 |
| 飞书通知 | 任务结束后推送 interactive 结果卡片（自定义机器人 Webhook） |
| 定时 | 系统 cron / 1Panel / 亦可参考上游 GitHub Actions workflow |

## 目录结构

```text
DouyinSparkPanel/
├── main.py                 # 续火入口
├── run_douyin.sh           # 定时包装（写日志 + 飞书通知）
├── notify_run.py           # 解析最近一次运行并推飞书
├── core/                   # 浏览器与任务逻辑（源自 DouYinSparkFlow）
├── utils/
├── panel/                  # Web 控制面板（二开新增）
│   ├── app.py
│   ├── static/
│   └── .env.example
├── .env.example
├── requirements.txt
└── docs/                   # 上游文档与截图（保留参考）
```

## 快速开始

### 1. 环境

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置

```bash
cp .env.example .env
```

填写 `TASKS`、`COOKIES_<UNIQUE_ID>`、可选 `FEISHU_WEBHOOK` 等；或启动面板在网页里粘贴 Cookie / 改好友。

### 3. 执行一次

```bash
python main.py
# 或
bash run_douyin.sh
```

### 4. 控制面板（可选）

```bash
cp panel/.env.example panel/.env   # 设置 PANEL_PASSWORD
cd panel
# 默认把上一级当作项目根；也可: export SPARKFLOW_DIR=/path/to/DouyinSparkPanel
uvicorn app:app --host 127.0.0.1 --port 8771
```

打开 `http://127.0.0.1:8771` 登录。

### 5. 定时

```cron
30 8 * * *  /path/to/DouyinSparkPanel/run_douyin.sh
```

## 飞书通知

群内添加**自定义机器人** → Webhook 写入 `.env` 的 `FEISHU_WEBHOOK`，或在面板「飞书通知」保存。  
`run_douyin.sh` 结束会自动推送；面板可发测试卡片。

## Cookie

1. 本机登录 [douyin.com](https://www.douyin.com)  
2. Cookie-Editor → Export → JSON  
3. 面板粘贴写入，或写入 `.env` 单行  

导入兼容 Cookie-Editor 数组、name/value 映射、`document.cookie` 字符串。

## 相对上游的二开点

- Web **控制面板**（鉴权、Cookie、配置、日志、一键跑）
- **飞书 Webhook** 结果通知（`notify_run.py`）
- 更稳的 `run_douyin.sh`（失败也有 `job end` + 通知）
- 路径可移植（相对项目根 / `SPARKFLOW_DIR`）

## 免责声明

开源学习与个人自用；禁止商业、恶意刷量或违反平台规则。风险自担；请控制频率，仅用于少量好友火花维护。

## License

MIT · [LICENSE](LICENSE)

再次感谢 [2061360308/DouYinSparkFlow](https://github.com/2061360308/DouYinSparkFlow)。
