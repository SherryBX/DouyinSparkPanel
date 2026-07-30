import os
import unittest
from unittest.mock import patch

import core.browser as browser


class DummyChromium:
    def __init__(self):
        self.launch_calls = []

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        return 'browser-instance'


class DummyPlaywright:
    def __init__(self):
        self.chromium = DummyChromium()

    def stop(self):
        pass


class DummyPlaywrightManager:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


class GetBrowserTests(unittest.TestCase):
    def test_local_server_without_display_uses_headless_mode(self):
        fake_playwright = DummyPlaywright()

        with patch.object(browser, 'sync_playwright', return_value=DummyPlaywrightManager(fake_playwright)),                  patch.object(browser, 'get_environment', return_value=browser.Environment.LOCAL),                  patch.object(browser, 'DEBUG', True):
            original_display = os.environ.pop('DISPLAY', None)
            try:
                browser.get_browser()
            finally:
                if original_display is not None:
                    os.environ['DISPLAY'] = original_display

        self.assertEqual(len(fake_playwright.chromium.launch_calls), 1)
        self.assertTrue(fake_playwright.chromium.launch_calls[0]['headless'])


if __name__ == '__main__':
    unittest.main()
