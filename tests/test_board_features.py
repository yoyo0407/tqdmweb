import csv
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
import zipfile

from qtqdm.board_process import ProcessRunner
from qtqdm.board_records import RunRecords


class BoardFeatureTests(unittest.TestCase):
    def test_rename_export_delete_and_active_record_guard(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            store = RunRecords(root / 'records.sqlite3')
            log = root / 'full.log'
            log.write_text('x' * 70000 + '\nresult=42\n', encoding='utf-8')
            try:
                record_id = store.start({'script': 'example.py'}, log)
                with self.assertRaisesRegex(ValueError, 'running'):
                    store.delete(record_id)
                store.rename(record_id, '實驗 seed 42')
                self.assertEqual(store.list()[0]['name'], '實驗 seed 42')
                store.training(record_id, {'metrics': {'loss': 1}}, {'charts': {'loss': [[0.5, 1, 1, 1]]}, 'next_update': 1})
                store.finish(record_id, 'exited', 0)
                with store.export(record_id) as file:
                    with zipfile.ZipFile(file) as archive:
                        self.assertEqual(set(archive.namelist()), {'record.json', 'metrics.csv', 'console.log'})
                        self.assertEqual(archive.read('console.log'), log.read_bytes())
                        metadata = json.loads(archive.read('record.json'))
                        self.assertEqual(metadata['name'], '實驗 seed 42')
                        rows = list(csv.reader(io.StringIO(archive.read('metrics.csv').decode())))
                        self.assertEqual(rows[1], ['loss', '0.5', '1', '1', '1'])
                store.delete(record_id)
                self.assertEqual(store.list(), [])
                self.assertTrue(log.is_file())
                store.training(record_id, {}, {'charts': {'loss': [[1, 2, 2, 2]]}, 'next_update': 2})
                self.assertEqual(store._db.execute('SELECT COUNT(*) FROM points').fetchone()[0], 0)
            finally:
                store.close()

    def test_failed_script_error_summary_traceback_and_log_survive_reopen(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / 'fail.py'
            script.write_text("raise RuntimeError('expected feature-test failure')", encoding='utf-8')
            path = root / 'records.sqlite3'
            store = RunRecords(path)
            runner = ProcessRunner(root, store)
            try:
                runner.start({'script': str(script), 'python': sys.executable, 'working_directory': str(root), 'arguments': ''})
                deadline = monotonic() + 5
                while runner.snapshot()['state'] != 'failed':
                    self.assertLess(monotonic(), deadline)
                    sleep(0.01)
                record_id = runner.record_id
                self.assertIn('expected feature-test failure', runner.snapshot()['failure']['summary'])
            finally:
                runner.close()
                store.close()
            store = RunRecords(path)
            try:
                record = store.get(record_id)
                self.assertEqual(record['exit_code'], 1)
                self.assertIn('RuntimeError', record['failure']['summary'])
                self.assertIn('Traceback', record['failure']['traceback'])
                self.assertTrue(Path(record['failure']['log_path']).is_file())
            finally:
                store.close()
