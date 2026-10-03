"""Export current source without Git history, private content, or local state."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from posts.updates import private_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    dest = args.destination.expanduser().resolve()
    if dest == ROOT or ROOT in dest.parents or dest.exists():
        parser.error('Choose a new directory outside the project.')
    paths = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT
    ).decode().split('\0')
    dest.mkdir(parents=True)
    count = 0
    for name in sorted(set(paths)):
        if not name or private_path(name):
            continue
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            continue
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        count += 1
    print(f'Exported {count} source files to {dest}. Git history and site content were excluded.')


if __name__ == '__main__':
    main()
