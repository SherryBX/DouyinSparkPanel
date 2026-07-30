import unittest

import core.tasks as tasks


class ChatReadyTests(unittest.TestCase):
    def test_titles_are_not_ready_when_only_numeric_placeholders_exist(self):
        titles = [
            '3747554021092027',
            '2990280684347149',
            '1389382831964263',
            '96594820721',
        ]
        self.assertFalse(tasks.conversation_titles_ready(titles, ['1055062468', '41681274192']))

    def test_titles_are_ready_when_real_names_appear(self):
        titles = ['皇帝大人🍟', '马宇浩', '彭城', '嘴王']
        self.assertTrue(tasks.conversation_titles_ready(titles, ['1055062468', '41681274192']))

    def test_titles_are_ready_when_target_numeric_id_is_present(self):
        titles = ['1055062468', '41681274192']
        self.assertTrue(tasks.conversation_titles_ready(titles, ['1055062468', '41681274192']))


if __name__ == '__main__':
    unittest.main()
