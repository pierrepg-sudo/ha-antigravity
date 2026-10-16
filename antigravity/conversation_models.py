"""Use the CLI's own model catalog; keep explicit preferences per conversation."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import native_connection as native
import saved_conversations as saved

_catalog = (0, [])


def parse_catalog(text):
    # CLI reports may put the name first, use a single tab, or draw a table.
    text = re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)', '', text)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    options = {}
    slug = r'[a-z0-9]+(?:[._:-][a-z0-9]+)+'
    for line in text.splitlines():
        cells = [c.strip(' `') for c in re.split(r'\t+|\s{2,}|[│|]', line.strip()) if c.strip(' `')]
        ids = [c for c in cells if re.fullmatch(slug, c) and len(c) <= 150 and c not in ('model-id', 'model_id')]
        if not ids:
            match = re.fullmatch(r'(' + slug + r')\s+(.+)', line.strip())
            if match:
                ids, cells = [match[1]], [match[1], match[2]]
        if len(ids) == 1:
            model = ids[0]
            if model in ('model-id', 'model_id'):
                continue
            labels = [c for c in cells if c != model and re.search('[A-Z]', c)]
            options[model] = {'id': model, 'name': labels[0][:180] if labels else model}
    return list(options.values())


def catalog():
    global _catalog
    if time.monotonic() - _catalog[0] < 60 and _catalog[1]:
        return _catalog[1]
    try:
        result = subprocess.run(['/data/home/.local/bin/agy', 'models'], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise native.NativeError('Model catalog unavailable. Check Google sign-in and try again.') from None
    if result.returncode:
        raise native.NativeError('Sign in to the CLI to load its available models.')
    options = parse_catalog(result.stdout)
    if not options and isinstance(result.stderr, str):
        options = parse_catalog(result.stderr)
    if not options:
        raise native.NativeError('The installed CLI returned an unsupported model catalog format.')
    _catalog = time.monotonic(), options
    return options


def active_id():
    try:
        path = saved.ROOT / 'cache/last_conversations.json'
        value = json.loads(path.read_text())
        cid = value.get('/opt/antigravity-workspace', '')
        return cid if isinstance(cid, str) and saved.UUID.fullmatch(cid) else ''
    except (OSError, ValueError, AttributeError):
        return ''


def preferences():
    try:
        value = json.loads(native.STATE.with_name('ha-conversation-models.json').read_text())
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise native.NativeError('Saved model preferences could not be read.') from None


def remember(cid, model):
    from conversation_management import preference_lock
    with preference_lock():
        _remember(cid, model)


def _remember(cid, model):
    value = preferences()
    if model:
        value[cid] = model
    else:
        value.pop(cid, None)
    target = native.STATE.with_name('ha-conversation-models.json')
    fd, temporary = tempfile.mkstemp(prefix='.models-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def listing():
    cid = active_id()
    return {'id': cid, 'selected': preferences().get(cid, ''), 'models': catalog()}
