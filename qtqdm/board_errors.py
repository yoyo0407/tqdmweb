"""A shared error summary for live and recorded runs."""


def failure_info(state, code, console, training=None, error=None):
    training = training or {}
    if state != 'failed' and training.get('state') != 'failed' and not error:
        return None
    text = console.get('text', '')
    marker = 'Traceback (most recent call last):'
    index = text.rfind(marker)
    traceback = text[index:] if index >= 0 else ''
    summary = training.get('error') or error
    if not summary and traceback:
        summary = next((line.strip() for line in reversed(traceback.splitlines()) if line.strip()), None)
    return {'summary': summary or f'Process exited with code {code}; no Python traceback was captured.',
            'traceback': traceback, 'log_path': console.get('path')}
