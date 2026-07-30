import os, sys
import logging
import subprocess
import traceback
from playwright.sync_api import sync_playwright
from utils.config import DEBUG, get_environment, Environment

logger = logging.getLogger("app")

PLAYWRIGHT_BROWSERS_PATH = "../chrome"

def should_launch_headed(env):
    if env != Environment.LOCAL or not DEBUG:
        return False

    if os.name == "nt":
        return True

    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))

def install_browser():
    """
    安装 Chromium 浏览器
    """
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
        print("浏览器安装完成，请重新运行程序。")
    except subprocess.CalledProcessError as e:
        print(f"发生未知错误：{e}")


def get_browser():
    """
    启动浏览器实例
    :return: 浏览器实例
    """

    env = get_environment()
    headless = not should_launch_headed(env)

    if env == Environment.LOCAL:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.abspath(
            os.path.join(os.path.dirname(__file__), PLAYWRIGHT_BROWSERS_PATH)
        )
    elif env == Environment.PACKED:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.abspath(
            os.path.join(os.path.dirname(sys.executable), PLAYWRIGHT_BROWSERS_PATH)
        )

    try:
        logger.info(f"准备启动浏览器，环境={env}，headless={headless}")
        logger.debug(f"PLAYWRIGHT_BROWSERS_PATH={os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '<default>')}")
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=headless)
        logger.info("浏览器启动完成")
        return playwright, browser
    except Exception as e:
        # 捕获浏览器启动错误
        if "Executable doesn't exist" in str(e) and env != Environment.GITHUBACTION:
            print("浏览器可执行文件不存在！")
            install_browser()
            sys.exit(1)
        else:
            traceback.print_exc()
