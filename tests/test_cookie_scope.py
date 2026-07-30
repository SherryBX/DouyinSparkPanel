import unittest

from utils.config import scope_cookies_for_domain


class CookieScopeTests(unittest.TestCase):
    def test_scope_cookies_for_domain_converts_url_cookie_to_shared_domain_cookie(self):
        cookies = [
            {
                "name": "sid_tt",
                "value": "abc",
                "url": "https://creator.douyin.com/"
            }
        ]

        scoped = scope_cookies_for_domain(cookies, '.douyin.com')

        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]['name'], 'sid_tt')
        self.assertEqual(scoped[0]['value'], 'abc')
        self.assertEqual(scoped[0]['domain'], '.douyin.com')
        self.assertEqual(scoped[0]['path'], '/')
        self.assertTrue(scoped[0]['secure'])
        self.assertNotIn('url', scoped[0])


if __name__ == '__main__':
    unittest.main()
