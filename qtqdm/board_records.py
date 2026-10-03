"""Persistent run metadata and raw metric samples, using only SQLite."""

import json
import os
from pathlib import Path
import sqlite3
from threading import Lock
from time import time
from uuid import uuid4


def process_token(pid):
    """Process creation identity, so a reused PID is not mistaken for its owner."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # PID no longer exists.
                return None
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            code = wintypes.DWORD()
            times = [ctypes.c_ulonglong() for _ in range(4)]
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or not kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in times]):
                raise ctypes.WinError(ctypes.get_last_error())
            return str(times[0].value) if code.value == 259 else None
        finally:
            kernel.CloseHandle(handle)
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except FileNotFoundError:
        return None


def archive_progress(progress):
    """Flush the final result from the child, even when it finishes between polls."""
    record_id, path = os.environ.get('TQDMBOARD_RECORD_ID'), os.environ.get('TQDMBOARD_RECORDS_PATH')
    if not record_id or not path:
        return
    store = RunRecords(path)
    try:
        data = progress.snapshot()
        data.pop('console', None)
        cursor = 0
        while True:
            page = progress.history_since(cursor)
            store.training(record_id, data, page)
            cursor = page['next_update']
            if not page['has_more']:
                break
    finally:
        store.close()


class RunRecords:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, started REAL, ended REAL, state TEXT,
                    exit_code INTEGER, config TEXT, log_path TEXT, training TEXT,
                    cursor INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS points (
                    run_id TEXT, metric TEXT, update_id INTEGER, point TEXT,
                    PRIMARY KEY (run_id, metric, update_id));
            """)
            columns = {row['name'] for row in self._db.execute('PRAGMA table_info(runs)')}
            for name, kind in [('owner_pid', 'INTEGER'), ('owner_token', 'TEXT'), ('pid', 'INTEGER'), ('pid_token', 'TEXT')]:
                if name not in columns:
                    self._db.execute(f'ALTER TABLE runs ADD COLUMN {name} {kind}')

    def start(self, config, log_path):
        record_id = uuid4().hex
        with self._lock, self._db:
            self._db.execute("INSERT INTO runs(id,started,state,config,log_path,owner_pid,owner_token) VALUES(?,?,'running',?,?,?,?)",
                             (record_id, time(), json.dumps(config), str(log_path), os.getpid(), process_token(os.getpid())))
        return record_id

    def attach_process(self, record_id, pid):
        try:
            token = process_token(pid)
        except OSError:
            token = None
        with self._lock, self._db:
            self._db.execute('UPDATE runs SET pid=?,pid_token=? WHERE id=?', (pid, token, record_id))

    def recover(self):
        """Board-only recovery. Child archival and other live Boards are untouched."""
        with self._lock:
            rows = self._db.execute("SELECT id,owner_pid,owner_token,pid,pid_token FROM runs WHERE ended IS NULL AND state IN ('running','unknown','detached')").fetchall()
        identities = {}
        def identity(pid):
            if pid not in identities:
                identities[pid] = process_token(pid) if pid is not None else None
            return identities[pid]
        for row in rows:
            try:
                if row['owner_token'] is None:
                    state = 'unknown'  # Legacy record: no evidence of process exit.
                elif identity(row['owner_pid']) == row['owner_token']:
                    continue
                elif row['pid'] is None:
                    state = 'unknown'  # Owner disappeared before child identity was saved.
                elif identity(row['pid']) is None:
                    state = 'interrupted'
                elif row['pid_token'] is None:
                    state = 'unknown'
                elif identity(row['pid']) == row['pid_token']:
                    state = 'detached'
                else:
                    state = 'interrupted'
            except OSError:
                continue  # No permission to prove that the process has disappeared.
            with self._lock, self._db:
                self._db.execute("UPDATE runs SET state=? WHERE id=? AND ended IS NULL", (state, row['id']))

    def training_snapshot(self, record_id):
        with self._lock:
            row = self._db.execute('SELECT training,cursor FROM runs WHERE id=?', (record_id,)).fetchone()
        if row is None or row['training'] is None:
            return None
        data = json.loads(row['training'])
        data['history_updates'] = row['cursor']
        return data

    def finish(self, record_id, state, code):
        with self._lock, self._db:
            self._db.execute("UPDATE runs SET ended=?,state=?,exit_code=? WHERE id=?",
                             (time(), state, code, record_id))

    def training(self, record_id, data, page=None):
        with self._lock, self._db:
            self._db.execute('BEGIN IMMEDIATE')
            row = self._db.execute('SELECT training FROM runs WHERE id=?', (record_id,)).fetchone()
            previous = json.loads(row['training']) if row and row['training'] else {}
            older = data.get('completed', 0) < previous.get('completed', 0) or (
                previous.get('control', {}).get('finished') and not data.get('control', {}).get('finished'))
            if not older:
                self._db.execute("UPDATE runs SET training=? WHERE id=?", (json.dumps(data), record_id))
            if page:
                rows = [(record_id, name, point[3], json.dumps(point))
                        for name, points in page['charts'].items() for point in points]
                self._db.executemany("INSERT OR IGNORE INTO points VALUES(?,?,?,?)", rows)
                self._db.execute("UPDATE runs SET cursor=MAX(cursor,?) WHERE id=?", (page['next_update'], record_id))

    def list(self):
        with self._lock:
            rows = self._db.execute("SELECT id,started,ended,state,exit_code,config,json_extract(training,'$.state') AS training_state FROM runs ORDER BY started DESC").fetchall()
        return [{**dict(row), 'config': json.loads(row['config'])} for row in rows]

    def get(self, record_id):
        with self._lock:
            row = self._db.execute("SELECT * FROM runs WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise ValueError('Run record not found')
        result = dict(row)
        result['config'] = json.loads(row['config'])
        data = json.loads(row['training']) if row['training'] else None
        if data:
            data['history_updates'] = row['cursor']
        result['training'] = {'data': data, 'connected': False}
        try:
            with open(row['log_path'], 'rb') as log:
                log.seek(0, 2)
                size = log.tell()
                log.seek(max(0, size - 65536))
                text = log.read().decode('utf-8', errors='replace')
                text = text.replace('\r\n', '\n').replace('\r', '\n')
            console_error = None
        except OSError as error:
            text, size, console_error = '', 0, str(error)
        result['console'] = {'text': text, 'version': size, 'trimmed_chars': max(0, size - 65536),
                             'path': row['log_path'], 'error': console_error}
        return result

    def history(self, record_id, after=0):
        if after < 0:
            raise ValueError('History cursor must be nonnegative')
        with self._lock:
            row = self._db.execute('SELECT cursor FROM runs WHERE id=?', (record_id,)).fetchone()
            if row is None:
                raise ValueError('Run record not found')
            end = min(after + 2000, row['cursor'])
            cursor = row['cursor']
            rows = self._db.execute('SELECT metric,point FROM points WHERE run_id=? AND update_id>? AND update_id<=? ORDER BY update_id',
                                    (record_id, after, end)).fetchall()
        charts = {}
        for row in rows:
            charts.setdefault(row['metric'], []).append(json.loads(row['point']))
        return {'charts': charts, 'next_update': end, 'has_more': end < cursor}

    def close(self):
        with self._lock:
            self._db.close()
