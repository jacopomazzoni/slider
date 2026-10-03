"""Initialize private deployment configuration without replacing existing values."""
import argparse
import os
from pathlib import Path
import re

from dotenv import dotenv_values, set_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', default='')
    parser.add_argument('--branch', default='')
    parser.add_argument('--enable-updates', action='store_true')
    args = parser.parse_args()
    if args.repository and not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
        parser.error('Repository must be owner/repository, not a URL.')
    root = Path(__file__).resolve().parent.parent
    path = root / '.env'
    path.touch(mode=0o600, exist_ok=True)
    os.chmod(path, 0o600)
    current = dotenv_values(path)
    defaults = {
        'SLIDERCMS_DATA_DIR': '.' if (root / 'db.sqlite3').exists() else 'data',
        'SLIDERCMS_DEBUG': '1',
        'SLIDERCMS_UPDATE_REPOSITORY': '',
        'SLIDERCMS_UPDATE_BRANCH': 'main',
        'SLIDERCMS_UPDATES_ENABLED': '0',
    }
    for key, value in defaults.items():
        if key not in current:
            set_key(path, key, value)
    if args.repository:
        set_key(path, 'SLIDERCMS_UPDATE_REPOSITORY', args.repository)
    if args.branch:
        set_key(path, 'SLIDERCMS_UPDATE_BRANCH', args.branch)
    if args.enable_updates:
        set_key(path, 'SLIDERCMS_UPDATES_ENABLED', '1')


if __name__ == '__main__':
    main()
