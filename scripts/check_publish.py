"""Fail publication checks if the Git index contains private runtime artifacts."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sliderCMS.settings')
from posts.updates import private_path

tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
blocked = [name for name in tracked if name and private_path(name)]
if blocked:
    print('Private files are tracked. Untrack them before publishing:\n' + '\n'.join(blocked))
    sys.exit(1)
print('Publication check passed: no known runtime artifacts in the Git index.')
