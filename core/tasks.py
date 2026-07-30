import os
import time
import traceback
from playwright.sync_api import Response

from utils import norm
from utils.logger import setup_logger
from utils.config import get_config, get_userData, scope_cookies_for_domain
from core.msg_builder import build_message
from core.browser import get_browser

config = get_config()
userData = get_userData()
logger = setup_logger(level=config.get("logLevel", "Info"))
userIDDict = {}

CONVERSATION_ITEM_SELECTOR = ".conversationConversationItemwrapper"
CONVERSATION_TITLE_SELECTOR = ".conversationConversationItemtitle"
CONVERSATION_LIST_SELECTOR = ".conversationConversationListwrapper"
CHAT_EDITOR_SELECTOR = ".messageEditorimChatEditorContainer"


def conversation_titles_ready(titles, targets):
    normalized_titles = [norm(title) for title in titles if norm(title)]
    normalized_targets = {norm(target) for target in targets if norm(target)}

    if not normalized_titles:
        return False

    if any(title in normalized_targets for title in normalized_titles):
        return True

    if any(not title.isdigit() for title in normalized_titles):
        return True

    return False


def save_debug_artifacts(page, prefix):
    os.makedirs('logs', exist_ok=True)
    png_path = f'logs/{prefix}.png'
    html_path = f'logs/{prefix}.html'
    try:
        page.screenshot(path=png_path, full_page=True)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(page.content())
        logger.info(f'已保存调试现场: {png_path}, {html_path}')
    except Exception as e:
        logger.warning(f'保存调试现场失败: {e}')


def handle_response(response: Response):
    global userIDDict
    if "aweme/v1/web/im/user/info" in response.url:
        try:
            json_data = response.json()
            for item in json_data.get("data", []):
                short_id = item.get("short_id")
                unique_id = item.get("unique_id")
                sec_uid = item.get("sec_uid", "")
                nickname = norm(item.get("nickname", ""))
                remark_name = norm(item.get("remark_name", nickname))
                userIDDict[remark_name] = [short_id, unique_id, sec_uid, nickname, remark_name]
        except Exception as e:
            tb = traceback.extract_tb(e.__traceback__)
            last = tb[-1]
            logger.warning(f"解析响应失败: {e}, 文件: {last.filename}, 行号: {last.lineno}, 函数: {last.name}")


def retry_operation(name, operation, retries=3, delay=2, *args, **kwargs):
    for attempt in range(retries):
        logger.debug(f"{name} 开始执行，第 {attempt + 1}/{retries} 次")
        try:
            result = operation(*args, **kwargs)
            logger.debug(f"{name} 执行成功，第 {attempt + 1}/{retries} 次")
            return result
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"{name} 失败，正在重试第 {attempt + 1} 次，错误：{e}")
                time.sleep(delay)
            else:
                logger.error(f"{name} 失败，已达到最大重试次数，错误：{e}")
                raise


def checkTargetName(targetName, targets):
    targetName = norm(targetName)
    if targetName in userIDDict:
        return next((v for v in userIDDict[targetName] if v and v in targets), None)
    if targetName in targets:
        return targetName
    return None


def wait_for_chat_ready(page, username, targets, timeout_ms=90000):
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        conv_count = page.locator(CONVERSATION_ITEM_SELECTOR).count()
        titles = page.locator(CONVERSATION_TITLE_SELECTOR).all_inner_texts()[:8] if conv_count > 0 else []
        if conv_count > 0 and conversation_titles_ready(titles, targets):
            logger.info(f"账号 {username} 会话列表已出现且标题已稳定，共 {conv_count} 项")
            logger.debug(f"账号 {username} 当前标题样本: {titles}")
            return
        body = page.locator('body').inner_text()[:300].replace('\n', ' | ')
        if conv_count > 0:
            logger.debug(f"账号 {username} 等待标题稳定，当前标题样本: {titles}")
        else:
            logger.debug(f"账号 {username} 等待聊天页就绪，body 片段: {body}")
        time.sleep(3)
    save_debug_artifacts(page, f'{username}-chat-ready-timeout')
    raise TimeoutError(f'账号 {username} 聊天页在 {timeout_ms}ms 内未就绪')


def scroll_and_select_user(page, username, targets):
    target_selector = CONVERSATION_ITEM_SELECTOR
    scrollable_friends_selector = CONVERSATION_LIST_SELECTOR

    logger.debug(f"账号 {username} 开始查找目标好友列表")
    logger.debug(f"账号 {username} 目标好友列表: {targets}")

    found_targets = set()
    remaining_targets = set(targets)
    empty_scroll_count = 0
    max_empty_scrolls = 10

    while True:
        target_elements = page.locator(target_selector).all()
        prev_found_count = len(found_targets)

        for element in target_elements:
            try:
                span = element.locator(CONVERSATION_TITLE_SELECTOR)
                targetName = span.inner_text()
                if targetName in found_targets:
                    continue
                found_targets.add(targetName)
                logger.debug(f"账号 {username} 找到好友 {targetName}")
                targetSymbol = checkTargetName(targetName, targets)
                if targetSymbol:
                    logger.info(f"账号 {username} 命中目标 {targetName}，匹配标识 {targetSymbol}")
                    element.click()
                    yield targetSymbol
                    if targetSymbol in remaining_targets:
                        remaining_targets.remove(targetSymbol)
                    if len(remaining_targets) == 0:
                        logger.info(f"账号 {username} 所有目标好友均已找到")
                        return
                    break
            except Exception:
                traceback.print_exc()
        else:
            new_found = len(found_targets) > prev_found_count
            if new_found:
                empty_scroll_count = 0
            else:
                empty_scroll_count += 1

            if empty_scroll_count >= max_empty_scrolls:
                logger.warning(f"账号 {username} 连续 {max_empty_scrolls} 次滚动未发现新好友")
                if len(remaining_targets) > 0:
                    logger.warning(f"账号 {username} 搜索结束，仍有以下好友未找到: {remaining_targets}")
                break

            scrollable_element = page.locator(scrollable_friends_selector).element_handle()
            if scrollable_element:
                scroll_top_before = page.evaluate('(element) => element.scrollTop', scrollable_element)
                page.evaluate('(element) => element.scrollTop += 800', scrollable_element)
                time.sleep(0.5)
                scroll_top_after = page.evaluate('(element) => element.scrollTop', scrollable_element)
                logger.debug(f"账号 {username} 滚动好友列表 (scrollTop: {scroll_top_before} -> {scroll_top_after})")
                time.sleep(1.5)
            else:
                logger.error(f"账号 {username} 未找到滚动容器，退出")
                save_debug_artifacts(page, f'{username}-scroll-container-missing')
                break


def do_user_task(browser, username, cookies, targets):
    logger.info(f"账号 {username} 准备创建浏览器上下文")
    context = browser.new_context()
    context.set_default_navigation_timeout(config['browserTimeout'])
    context.set_default_timeout(config['browserTimeout'])
    page = context.new_page()
    page.on('response', handle_response)

    try:
        scoped_cookies = scope_cookies_for_domain(cookies, '.douyin.com')
        logger.info(f"账号 {username} 准备注入跨子域 Cookie，共 {len(scoped_cookies)} 条")
        context.add_cookies(scoped_cookies)
        logger.info(f"账号 {username} Cookie 注入完成")

        logger.info(f"账号 {username} 准备打开抖音聊天页")
        retry_operation(
            '打开抖音网页聊天页面',
            page.goto,
            retries=config['taskRetryTimes'],
            delay=5,
            url='https://www.douyin.com/chat',
            wait_until='domcontentloaded',
        )
        logger.info(f"账号 {username} 聊天页打开完成，当前 URL: {page.url}")

        wait_for_chat_ready(page, username, targets, timeout_ms=config['browserTimeout'])
        logger.info(f"账号 {username} 开始查找并处理目标好友，共 {len(targets)} 个")

        for target_name in scroll_and_select_user(page, username, targets):
            logger.info(f"账号 {username} 已选中好友 {target_name}")
            chat_input_selector = CHAT_EDITOR_SELECTOR
            page.wait_for_selector(chat_input_selector, timeout=config['browserTimeout'])
            chat_input = page.locator(chat_input_selector)
            message = build_message()
            logger.debug(f"账号 {username} 生成消息内容完成，长度={len(message)}")
            for line in message.split('\n'):
                chat_input.type(line)
                if line != message.split('\n')[-1]:
                    chat_input.press('Shift+Enter')
            logger.info(f"账号 {username} 准备向好友 {target_name} 发送消息")
            logger.debug(f"账号 {username} 发送内容: {message}")
            chat_input.press('Enter')
            logger.info(f"账号 {username} 已向好友 {target_name} 发送消息")
            time.sleep(2)
    except Exception:
        save_debug_artifacts(page, f'{username}-failure')
        raise
    finally:
        logger.info(f"账号 {username} 关闭上下文")
        context.close()


def runTasks():
    logger.info('开始执行任务')
    logger.info('准备初始化浏览器')
    playwright, browser = get_browser()
    try:
        logger.debug('当前配置如下：')
        logger.debug(f"消息模板: {config.get('messageTemplate', '未找到消息模板')}")
        logger.debug(f"一言类型: {config['hitokotoTypes']}")
        for user in userData:
            logger.debug(f"用户: {user.get('username', '未知用户')}, 目标好友: {user['targets']}")

        for user in userData:
            cookies = user['cookies']
            targets = user['targets']
            username = user.get('username', '未知用户')
            logger.info(f"开始处理账号 {username}，目标数={len(targets)}，Cookie 数={len(cookies)}")
            do_user_task(browser, username, cookies, targets)
            logger.info(f"账号 {username} 任务完成")
    finally:
        browser.close()
        playwright.stop()
