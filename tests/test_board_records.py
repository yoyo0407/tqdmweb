import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
from unittest.mock import Mock, patch
from threading import Event
from urllib.request import Request, urlopen

from qtqdm.board import TqdmBoard
from qtqdm.board_records import RunRecords
from qtqdm.board_viewers import BoardViewers
from qtqdm.board_process import ProcessRunner
from qtqdm.board_training import TrainingBridge
from qtqdm import Qtqdm


class RecordTests(unittest.TestCase):
    def test_broken_stdin_does_not_prevent_exit_finalization(self):
        with TemporaryDirectory() as folder:
            records = Mock()
            runner = ProcessRunner(folder, records)
            process, reader = Mock(), Mock()
            process.wait.return_value = 0
            process.stdin.close.side_effect = BrokenPipeError('child exited')
            runner._process = process
            runner._finalize(process, reader, 'stable-record')
            records.finish.assert_called_once_with('stable-record', 'exited', 0)
            self.assertEqual(runner.state, 'exited')
            self.assertEqual(runner.exit_code, 0)

    def test_recovery_preserves_live_owners_and_does_not_invent_exit_codes(self):
        with TemporaryDirectory() as folder:
            store = RunRecords(Path(folder) / 'records.sqlite3')
            try:
                record_id = store.start({}, Path(folder) / 'output.log')
                store.recover()
                self.assertEqual(store.get(record_id)['state'], 'running')
                store.attach_process(record_id, os.getpid())
                # A different creation identity means the original owner no longer exists.
                with store._db:
                    store._db.execute("UPDATE runs SET owner_token='old-owner' WHERE id=?", (record_id,))
                store.recover()
                self.assertEqual(store.get(record_id)['state'], 'detached')
                with store._db:
                    store._db.execute("UPDATE runs SET pid_token='old-child' WHERE id=?", (record_id,))
                store.recover()
                record = store.get(record_id)
                self.assertEqual(record['state'], 'interrupted')
                self.assertIsNone(record['exit_code'])
                self.assertIsNone(record['ended'])
                legacy = store.start({}, Path(folder) / 'legacy.log')
                with store._db:
                    store._db.execute('UPDATE runs SET owner_token=NULL WHERE id=?', (legacy,))
                store.recover()
                self.assertEqual(store.get(legacy)['state'], 'unknown')
            finally:
                store.close()

    def test_old_finalizer_still_finishes_its_record_after_next_start(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / 'fast.py'
            script.write_text("print('done')", encoding='utf-8')
            store = RunRecords(root / 'records.sqlite3')
            runner = ProcessRunner(root, store)
            config = {'script': str(script), 'python': sys.executable, 'working_directory': str(root), 'arguments': ''}
            release = Event()
            first = []
            original = runner._finalize
            def delayed(process, reader, record_id):
                if record_id == first[0]:
                    release.wait(5)
                original(process, reader, record_id)
            # start() sets record_id before constructing the waiter.
            def wrapper(process, reader, record_id):
                if not first:
                    first.append(record_id)
                delayed(process, reader, record_id)
            runner._finalize = wrapper
            try:
                runner.start(config)
                runner._process.wait(timeout=5)
                runner.start(config)
                deadline = monotonic() + 5
                while runner.snapshot()['state'] != 'exited':
                    self.assertLess(monotonic(), deadline)
                    sleep(0.01)
                release.set()
                runner.close()
                for row in store.list():
                    self.assertEqual(row['exit_code'], 0)
                    self.assertEqual(row['state'], 'exited')
                    self.assertIsNotNone(row['ended'])
            finally:
                release.set()
                runner.close()
                store.close()

    def test_bridge_restores_final_result_and_history_after_fast_exit(self):
        with TemporaryDirectory() as folder:
            store = RunRecords(Path(folder) / 'records.sqlite3')
            record_id = store.start({}, Path(folder) / 'output.log')
            points = [[i / 10, i, i, i] for i in range(1, 3502)]
            data = {'completed': 3501, 'state': 'finished', 'control': {'finished': True}, 'history_updates': 3501}
            store.training(record_id, data, {'charts': {'loss': points}, 'next_update': 3501})
            store.finish(record_id, 'exited', 0)
            class Runner:
                def snapshot(self):
                    return {'job_id': 1, 'running': False, 'state': 'exited', 'record_id': record_id, 'dashboard_url': None}
            runner = Runner()
            bridge = TrainingBridge(runner, store)
            try:
                bridge.start()
                deadline = monotonic() + 5
                while bridge.snapshot(runner.snapshot())['data'] is None:
                    self.assertLess(monotonic(), deadline)
                    sleep(0.01)
                self.assertEqual(bridge.snapshot(runner.snapshot())['data']['state'], 'finished')
                self.assertEqual(bridge._history['loss'], points)
                self.assertFalse(bridge.snapshot(runner.snapshot())['connected'])
            finally:
                bridge.close()
                store.close()

    def test_board_wait_does_not_require_terminal_input(self):
        with patch.dict(os.environ, {'TQDMBOARD': '1'}), patch('builtins.input') as terminal_input:
            with Qtqdm(range(2), open_browser=False) as progress:
                list(progress)
            progress.wait()
            terminal_input.assert_not_called()
            self.assertIsNone(progress.server)

    def test_late_poll_cannot_overwrite_final_training_result(self):
        with TemporaryDirectory() as folder:
            store = RunRecords(Path(folder) / 'records.sqlite3')
            try:
                record_id = store.start({}, Path(folder) / 'missing.log')
                final = {'completed': 3, 'state': 'finished', 'control': {'finished': True}}
                store.training(record_id, final)
                store.training(record_id, {'completed': 2, 'state': 'running', 'control': {'finished': False}})
                store.training(record_id, {'completed': 3, 'state': 'running', 'control': {'finished': False}})
                self.assertEqual(store.get(record_id)['training']['data']['state'], 'finished')
            finally:
                store.close()

    def test_reopen_preserves_config_exit_console_and_sparse_history(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            log = root / 'output.log'
            log.write_text('result=42\n', encoding='utf-8')
            path = root / 'records.sqlite3'
            store = RunRecords(path)
            config = {'script': '測試.py', 'arguments': '--seed 42'}
            record_id = store.start(config, log)
            page = {'charts': {'score': [[0.1, 42, 1, 1], [2, 48, 3000, 3000]]}, 'next_update': 3000}
            store.training(record_id, {'history_updates': 3001, 'metrics': {'score': 48}}, page)
            store.training(record_id, {'history_updates': 3001, 'metrics': {'score': 48}}, page)
            store.finish(record_id, 'exited', 0)
            store.close()
            store = RunRecords(path)
            try:
                record = store.get(record_id)
                self.assertEqual(record['config'], config)
                self.assertEqual(record['exit_code'], 0)
                self.assertEqual(record['console']['text'], 'result=42\n')
                self.assertEqual(record['training']['data']['history_updates'], 3000)
                first = store.history(record_id)
                second = store.history(record_id, first['next_update'])
                self.assertTrue(first['has_more'])
                self.assertEqual(first['charts']['score'], [[0.1, 42, 1, 1]])
                self.assertEqual(second['charts']['score'], [[2, 48, 3000, 3000]])
                self.assertFalse(second['has_more'])
                with self.assertRaises(ValueError):
                    store.get('../not-a-run')
            finally:
                store.close()

    def test_fast_script_record_through_http_and_app_reopen(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / 'fast.py'
            script.write_text("print('result=42')", encoding='utf-8')
            path = root / 'records.sqlite3'
            board = TqdmBoard(root, records_path=path)
            board.runner.project_root = root
            url = board.start()
            try:
                config = {'script': str(script), 'python': sys.executable, 'working_directory': str(root), 'arguments': ''}
                board.runner.start(config)
                deadline = monotonic() + 5
                while board.runner.snapshot()['state'] != 'exited':
                    self.assertLess(monotonic(), deadline)
                    sleep(0.02)
                with urlopen(url + 'records') as response:
                    record_id = json.load(response)[0]['id']
            finally:
                board.close()
            board = TqdmBoard(root, records_path=path)
            url = board.start()
            try:
                with urlopen(url + 'record?id=' + record_id) as response:
                    record = json.load(response)
                self.assertEqual(record['exit_code'], 0)
                self.assertIn('result=42', record['console']['text'])
                self.assertEqual(record['config']['script'], str(script))
                self.assertIsNone(record['training']['data'])
            finally:
                board.close()


class ViewerTests(unittest.TestCase):
    def test_out_of_order_heartbeat_does_not_reopen_closed_tab(self):
        viewers = BoardViewers(grace=0)
        viewers.update('tab', sequence=1)
        viewers.update('tab', True, sequence=3)
        viewers.update('tab', sequence=2)
        self.assertTrue(viewers.should_close())
        viewers.update('tab', sequence=4)
        self.assertFalse(viewers.should_close())

    def test_reload_and_multiple_tabs_and_last_close(self):
        viewers = BoardViewers()
        with patch('qtqdm.board_viewers.monotonic', return_value=0):
            self.assertFalse(viewers.should_close())
            viewers.update('first')
            viewers.update('second')
            viewers.update('first', True)
            self.assertFalse(viewers.should_close())
            viewers.update('second', True)
            self.assertFalse(viewers.should_close())
        with patch('qtqdm.board_viewers.monotonic', return_value=2):
            viewers.update('refreshed')
        with patch('qtqdm.board_viewers.monotonic', return_value=5):
            self.assertFalse(viewers.should_close())
            viewers.update('refreshed', True)
            self.assertFalse(viewers.should_close())
        with patch('qtqdm.board_viewers.monotonic', return_value=8):
            self.assertTrue(viewers.should_close())

    def test_crashed_browser_lease_expires(self):
        viewers = BoardViewers()
        with patch('qtqdm.board_viewers.monotonic', return_value=0):
            viewers.update('tab')
        with patch('qtqdm.board_viewers.monotonic', return_value=89):
            self.assertFalse(viewers.should_close())
        with patch('qtqdm.board_viewers.monotonic', return_value=90):
            self.assertFalse(viewers.should_close())
        with patch('qtqdm.board_viewers.monotonic', return_value=93):
            self.assertTrue(viewers.should_close())
