"""Runtime paths shared by Django and standalone maintenance scripts."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
# Keep existing installations working; new installs separate writable state.
_default = BASE_DIR if (BASE_DIR / 'db.sqlite3').exists() else BASE_DIR / 'data'
DATA_DIR = Path(os.getenv('SLIDERCMS_DATA_DIR', str(_default))).expanduser()
if not DATA_DIR.is_absolute():
    DATA_DIR = BASE_DIR / DATA_DIR
DATA_DIR = DATA_DIR.resolve()
if BASE_DIR in DATA_DIR.parents and DATA_DIR != BASE_DIR / 'data' and BASE_DIR / 'data' not in DATA_DIR.parents:
    raise RuntimeError('SLIDERCMS_DATA_DIR must be data/ (or a subdirectory), the legacy project root, or outside the checkout.')
DATELINE_PATH = (BASE_DIR / 'templates' / 'dateline_announcements.json'
                 if DATA_DIR == BASE_DIR else DATA_DIR / 'dateline_announcements.json')
