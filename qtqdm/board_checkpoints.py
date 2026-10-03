"""Opt-in checkpoint inspection using the script's selected Python environment."""

import json
import os
from pathlib import Path
import subprocess


def checkpoint_contract(script):
    path = Path(script).with_suffix('.tqdmboard.json')
    if not path.is_file():
        raise ValueError('This script has no checkpoint interface. Add a .tqdmboard.json manifest or use its command-line arguments.')
    contract = json.loads(path.read_text(encoding='utf-8'))
    if contract.get('version') != 1 or contract.get('checkpoint_format') not in ('qtqdm-2048-v1', 'qtqdm-training-v1'):
        raise ValueError('Unsupported checkpoint interface manifest')
    if contract.get('resume_argument') != '--resume':
        raise ValueError('The checkpoint interface currently requires --resume')
    return contract


def inspect_checkpoint(config, path):
    contract = checkpoint_contract(config['script'])
    checkpoint = Path(path).expanduser().resolve(strict=True)
    if not checkpoint.is_file():
        raise ValueError('Choose a checkpoint file')
    worker = Path(__file__).with_name('board_checkpoint_worker.py')
    payload = {'contract': contract, 'path': str(checkpoint), 'argv': config['argv']}
    try:
        result = subprocess.run([config['python'], '-I', str(worker)], input=json.dumps(payload),
                                text=True, encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except subprocess.TimeoutExpired:
        raise ValueError('Checkpoint inspection timed out after 30 seconds') from None
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or 'Checkpoint inspection failed')
    report = json.loads(result.stdout)
    if not report.get('valid'):
        raise ValueError(report.get('error', 'Checkpoint inspection failed'))
    return {**report, 'path': str(checkpoint)}


def prepare_launch(config, path):
    if not path:
        return config
    if any(value == '--resume' or value.startswith('--resume=') for value in config['argv']):
        raise ValueError('Remove --resume from Arguments when using the Checkpoint picker')
    report = inspect_checkpoint(config, path)
    argv = [*config['argv'], '--resume', report['path']]
    return {**config, 'argv': argv, 'arguments': subprocess.list2cmdline(argv), 'checkpoint': report}
