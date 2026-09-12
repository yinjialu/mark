import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugins/codex-marks/scripts'))
sys.path.insert(0, str(ROOT / 'integration/src'))
import capture
import library


class SourceLabelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mark-source-labels-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'sessions/2026/09/08').mkdir(parents=True)
        self.thread = '11111111-2222-3333-4444-555555555555'
        self.turn = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        self.message = 'msg_saved'
        records = [
            {'type': 'session_meta', 'payload': {'id': self.thread, 'cwd': '/project'}},
            {'type': 'turn_context', 'payload': {'turn_id': self.turn}},
            {'type': 'response_item', 'payload': {'type': 'message', 'id': 'question', 'role': 'user', 'content': [{'type': 'input_text', 'text': '定位问题'}]}},
            {'type': 'response_item', 'payload': {'type': 'message', 'id': self.message, 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '保存内容'}]}},
        ]
        path = self.root / 'sessions/2026/09/08' / ('rollout-' + self.thread + '_' + self.turn + '.jsonl')
        path.write_text('\n'.join(json.dumps(item) for item in records) + '\n')

    def test_turn_is_found_when_history_filename_has_a_suffix(self):
        labels = capture.source_labels(self.root, self.thread, self.message)
        self.assertEqual(labels['turn_id'], self.turn)
        self.assertEqual(labels['turn_title'], '定位问题')

    def test_library_enriches_an_existing_mark_without_a_turn(self):
        mark = {'id': 'id', 'title': 'title', 'quote': '保存内容', 'thread_id': self.thread,
                'anchor': {'message_id': self.message, 'coordinate_space': 'rendered_message_text'},
                'tags': [], 'note': '', 'created_at': '2026-09-08T00:00:00Z', 'deleted_at': None}
        with patch.dict(os.environ, {'CODEX_MARKS_SOURCE_ROOT': str(self.root)}):
            result = library.summary(mark)
        self.assertEqual(result['anchor']['turn_id'], self.turn)
        self.assertEqual(result['anchor']['turn_title'], '定位问题')


if __name__ == '__main__':
    unittest.main()
