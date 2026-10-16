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
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', result.stdout)
    options = []
    for line in text.splitlines():
        match = re.fullmatch(r'\s*([a-z0-9][a-z0-9._:-]{1,150})\s{2,}(.{1,180})\s*', line)
        if match:
            options.append({'id': match[1], 'name': match[2].strip()})
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
