"""Offline regression tests for the reviewed-description approval boundary."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import web


class PreviewSafetyTests(unittest.TestCase):
    def setUp(self):
        self.rules = [{'name': 'Handle', 'type': 'text', 'enabled': True,
                       'find': 'old.name', 'replace': 'new_name'}]
        self.videos = [{'id': str(n), 'snippet': {'title': f'Video {n}',
                        'description': 'Follow @old.name for original music.'},
                        'status': {'privacyStatus': 'public'}} for n in range(2)]
        self.progress = {'completed': {}, 'failed': {}, 'quota_by_pt_date': {}}
        self.patches = [
            patch.object(web, 'API_VIDEOS', self.videos),
            patch.object(web, 'STATE', {**web.STATE, 'phase': 'ready', 'channel': {'title': 'Demo', 'id': 'demo'}}),
            patch.object(web, 'BULK_PREVIEW', None),
            patch.object(web.bulkedit, 'load_rules', side_effect=lambda: self.rules),
            patch.object(web.ytdlp, 'load_cache', return_value={'videos': {}}),
            patch.object(web.main, 'load_progress', return_value=self.progress),
            patch.object(web.main, 'save_progress'),
            patch.object(web.main, 'build_service'),
            patch.object(web.main, 'write_backup', return_value=True),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def request(self, body):
        handler = object.__new__(web.Handler)
        handler.headers = {}
        handler.path = '/api/bulk/apply'
        handler._body = lambda: body
        handler._send = lambda code, payload: (code, payload)
        return handler.do_POST()

    def test_status_exposes_download_progress_and_completion(self):
        with patch.object(web.ytdlp, 'available', return_value=True), patch.object(web.ytdlp, 'version', return_value='mock'):
            web.STATE['download'] = {'id':'demo', 'status':'running', 'percent':'42.5%', 'folder':'downloads'}
            status = web.build_status()
            self.assertEqual(status['download']['percent'], '42.5%')
            self.assertIsNot(status['download'], web.STATE['download'])
            web.STATE['download']['status'] = 'complete'
            self.assertEqual(web.build_status()['download']['status'], 'complete')

    def test_desktop_session_requires_token(self):
        handler = object.__new__(web.Handler)
        handler.server = SimpleNamespace(server_port=8765)
        handler.headers = {}
        handler._send = lambda code, payload: (code, payload)
        with patch.object(web, 'ACCESS_TOKEN', 'test-session'):
            self.assertFalse(handler._authorized())
            handler.headers = {'X-Toolkit-Token': 'test-session'}
            self.assertTrue(handler._authorized())
            handler.headers['Origin'] = 'https://unrelated.example'
            self.assertFalse(handler._authorized())

    def test_selected_preview_and_apply_use_only_selected_video(self):
        preview = web.compute_preview(['1'])
        self.assertEqual([p['video_id'] for p in preview['pending']], ['1'])
        with patch.object(web.main, 'run_updates', return_value=(0, 0, 0, 0)) as update:
            web.job_bulk_apply(preview)
        self.assertEqual([v['id'] for v in update.call_args.args[3]], ['1'])
        self.assertEqual([p['video_id'] for p in update.call_args.args[4]], ['1'])
        self.assertEqual(web.main.write_backup.call_count, 1)

    def test_empty_selection_is_not_all_videos(self):
        self.assertEqual(web.compute_preview([])['pending'], [])

    def test_brand_assets_are_local_and_explicitly_allowed(self):
        handler = object.__new__(web.Handler)
        handler.headers = {}
        handler._send = lambda code, body, ctype='application/json': (code, body, ctype)
        for path, expected_type in [('/assets/brand.css', 'text/css; charset=utf-8'),
                                    ('/assets/ui/ui.css', 'text/css; charset=utf-8'),
                                    ('/assets/ui/ui.js', 'text/javascript; charset=utf-8'),
                                    ('/assets/channel-mark.svg', 'image/svg+xml'),
                                    ('/assets/fonts/LinkSans-LinkSansVF.woff2', 'font/woff2'),
                                    ('/assets/fonts/link-sans.css', 'text/css; charset=utf-8')]:
            handler.path = path
            code, body, ctype = handler.do_GET()
            self.assertEqual(code, 200)
            self.assertEqual(ctype, expected_type)
            self.assertGreater(len(body), 100)
        handler.path = '/assets/../token.json'
        self.assertEqual(handler.do_GET()[0], 404)
        web.main.build_service.assert_not_called()

    def test_review_context_matches_actual_result(self):
        before = 'Instagram: @old.name\nhttps://www.instagram.com/old.name'
        after = 'Instagram: @new_name\nhttps://www.instagram.com/new_name/'
        review = web.description_review(before, after)
        self.assertEqual(len(review), 1)
        self.assertEqual(''.join(p['text'] for p in review[0]['before']), before)
        self.assertEqual(''.join(p['text'] for p in review[0]['after']), after)
        self.assertTrue(any(p['changed'] for p in review[0]['after']))

    def test_rule_change_blocks_apply(self):
        preview = copy.deepcopy(web.compute_preview(['1']))
        self.rules[0]['replace'] = 'unexpected'
        web.BULK_PREVIEW = preview
        with patch.object(web, 'start') as start:
            code, _ = self.request({'confirm': 'UPDATE', 'preview_id': preview['preview_id']})
            self.assertEqual(code, 400)
            start.assert_not_called()

    def test_description_change_blocks_worker_before_backup(self):
        preview = web.compute_preview(['1'])
        self.videos[1]['snippet']['description'] = 'Changed elsewhere'
        web.job_bulk_apply(preview)
        web.main.write_backup.assert_not_called()
        web.main.build_service.assert_not_called()

    def test_confirmation_token_and_single_use(self):
        preview = web.compute_preview(['1'])
        web.BULK_PREVIEW = preview
        with patch.object(web, 'start') as start:
            self.assertEqual(self.request({'confirm': 'no', 'preview_id': preview['preview_id']})[0], 400)
            self.assertEqual(self.request({'confirm': 'UPDATE', 'preview_id': 'stale'})[0], 400)
            self.assertEqual(self.request({'confirm': 'UPDATE', 'preview_id': preview['preview_id']})[0], 200)
            self.assertIsNone(web.BULK_PREVIEW)
            start.assert_called_once_with(web.job_bulk_apply, preview)


if __name__ == '__main__':
    unittest.main()
