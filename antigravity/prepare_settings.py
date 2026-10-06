"""Choose inline rendering when no explicit rendering preference exists."""
import json
import os
from pathlib import Path


def prepare(path):
    try:
        settings = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(settings, dict):
            raise ValueError('Settings must be an object')
        if settings.get('altScreenMode', 'default') != 'default':
            return
        settings['altScreenMode'] = 'never'
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.scroll.tmp')
        temporary.write_text(json.dumps(settings, indent=2) + '\n')
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except (OSError, ValueError):
        print('Could not set inline rendering; existing settings were preserved.', flush=True)


if __name__ == '__main__':
    prepare(Path.home() / '.gemini/antigravity-cli/settings.json')
