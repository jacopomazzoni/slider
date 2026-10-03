"""Opt-in updates from one operator-configured public GitHub repository."""
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import sqlite3
import subprocess
import sys
import time

import requests
from django.conf import settings
from django.core.cache import cache


class UpdateError(Exception):
    pass


def git(*args, timeout=30):
    result = subprocess.run(['git', *args], cwd=settings.BASE_DIR, text=True,
                            capture_output=True, timeout=timeout,
                            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    if result.returncode:
        raise UpdateError(result.stderr.strip()[-1500:] or 'Git operation failed.')
    return result.stdout.strip()


def source():
    repo = settings.SLIDERCMS_UPDATE_REPOSITORY.strip()
    branch = settings.SLIDERCMS_UPDATE_BRANCH.strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise UpdateError('Set SLIDERCMS_UPDATE_REPOSITORY=owner/repository in .env first.')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', branch) or '..' in branch:
        raise UpdateError('Invalid update branch in .env.')
    return repo, branch


def private_path(name):
    parts = PurePosixPath(name).parts
    return (any(p in {'data', 'media', 'logs', 'emails', 'backups', 'updates', '__pycache__'}
                or p.startswith('.venv') for p in parts)
            or name == 'templates/dateline_announcements.json'
            or any(p == '.secret_key' or (p.startswith('.env') and p != '.env.example') for p in parts)
            or bool(re.search(r'\.(sqlite3.*|db|pyc|zip|pem|key)$', name)))


def clean_checkout():
    if Path(git('rev-parse', '--show-toplevel')).resolve() != Path(settings.BASE_DIR).resolve():
        raise UpdateError('Updates require a Git clone with manage.py at its root.')
    if git('status', '--porcelain', '--untracked-files=normal'):
        raise UpdateError('Local code changes exist. Commit/deploy them before updating; nothing will be overwritten.')
    if any(private_path(p) for p in git('ls-files').splitlines()):
        raise UpdateError('Private runtime files are still tracked by Git. Remove them from the index first.')


def update_dir():
    path = Path(settings.DATA_DIR) / 'updates'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def status_write(state, message, **extra):
    path = update_dir() / 'status.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'state': state, 'message': message, 'time': time.time(), **extra}))
    tmp.replace(path)


def status_read():
    try:
        status = json.loads((update_dir() / 'status.json').read_text())
        if status['state'] == 'running' and time.time() - status['time'] > 2400:
            status.update(state='failed', message='Update interrupted. Inspect data/updates/update.log before restarting.')
        return status
    except (OSError, ValueError, KeyError):
        return {}


def check_update():
    repo, branch = source()
    key = f'github-update:{repo}:{branch}'
    remote = cache.get(key)
    if remote is None:
        response = requests.get(f'https://api.github.com/repos/{repo}/commits',
                                params={'sha': branch, 'per_page': 1}, timeout=(3, 8),
                                headers={'Accept': 'application/vnd.github+json',
                                         'User-Agent': 'sliderCMS-updater'})
        response.raise_for_status()
        payload = response.json()
        remote = payload[0].get('sha', '') if isinstance(payload, list) and payload and isinstance(payload[0], dict) else ''
        if not isinstance(remote, str) or not re.fullmatch(r'[0-9a-f]{40}', remote):
            raise UpdateError('GitHub returned an invalid commit.')
        cache.set(key, remote, 300)
    current = git('rev-parse', 'HEAD')
    reason = ''
    try:
        if not settings.SLIDERCMS_UPDATES_ENABLED:
            raise UpdateError('Installation is disabled. Enable SLIDERCMS_UPDATES_ENABLED in .env on the server.')
        clean_checkout()
        runtime = json.loads((Path(settings.LOG_DIR) / 'runtime.json').read_text())
        if runtime['pid'] != os.getpid():
            raise UpdateError('Start this server with scripts/start_slidercms.sh to enable managed updates.')
    except (UpdateError, OSError, ValueError, KeyError) as error:
        reason = str(error)
    return {'current': current, 'latest': remote, 'available': current != remote,
            'can_install': current != remote and not reason, 'reason': reason,
            'repository': repo, 'branch': branch}


def launch_update(sha):
    info = check_update()
    if not info['can_install'] or sha != info['latest']:
        raise UpdateError(info['reason'] or 'Update changed or is already installed. Check again.')
    lock = (update_dir() / 'update.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise UpdateError('An update is already running.')
    try:
        status_write('running', 'Update queued. The server will briefly go offline.', sha=sha)
        with (update_dir() / 'update.log').open('a') as output:
            subprocess.Popen([sys.executable, str(settings.BASE_DIR / 'manage.py'),
                              'apply_update', sha, '--lock-fd', str(lock.fileno())],
                             cwd=settings.BASE_DIR, stdin=subprocess.DEVNULL,
                             stdout=output, stderr=output, start_new_session=True,
                             pass_fds=(lock.fileno(),))
    except Exception:
        status_write('failed', 'Could not start the update worker.')
        raise
    finally:
        lock.close()


def stop_managed(pid, marker):
    if pid <= 1 or pid == os.getpid():
        raise UpdateError('Invalid managed process ID.')
    command = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout
    if not command.strip():
        return
    if marker not in command or str(settings.BASE_DIR) not in command:
        raise UpdateError('Managed PID no longer belongs to the expected process; refusing to stop it.')
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(.1)
    raise UpdateError('A backend process did not stop. No forced kill was attempted.')


def run_update(sha):
    """Run in a detached process, never inside the HTTP request or Celery worker."""
    if not settings.SLIDERCMS_UPDATES_ENABLED or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise UpdateError('Updates disabled or invalid revision.')
    repo, branch = source()
    clean_checkout()
    old = git('rev-parse', 'HEAD')
    git('fetch', '--no-tags', f'https://github.com/{repo}.git', branch, timeout=120)
    if git('rev-parse', 'FETCH_HEAD') != sha:
        raise UpdateError('GitHub changed since the check. Check again before installing.')
    git('merge-base', '--is-ancestor', old, sha)
    if any(private_path(p) for p in git('ls-tree', '-r', '--name-only', sha).splitlines()):
        raise UpdateError('Incoming commit contains private/runtime files. Update refused.')
    runtime = json.loads((Path(settings.LOG_DIR) / 'runtime.json').read_text())
    # Save recovery metadata before any backend shutdown or code change.
    backup = update_dir() / time.strftime('backup-%Y%m%d-%H%M%S')
    backup.mkdir(mode=0o700)
    (backup / 'revision.txt').write_text(old + '\n')
    time.sleep(2)  # Allow the initiating HTTP response and audit log to finish.
    stop_managed(int(runtime['pid']), 'manage.py runserver')
    celery_pid = Path(settings.LOG_DIR) / 'celery.pid'
    if celery_pid.exists():
        stop_managed(int(celery_pid.read_text()), 'celery')
        celery_pid.unlink()
    from django.db import connections
    connections.close_all()
    with sqlite3.connect(str(settings.DATABASES['default']['NAME'])) as source_db:
        with sqlite3.connect(str(backup / 'db.sqlite3')) as backup_db:
            source_db.backup(backup_db)
    status_write('running', 'Backup complete; installing code and dependencies.', backup=str(backup))
    git('merge', '--ff-only', sha)
    commands = [
        [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
        [sys.executable, 'manage.py', 'check'],
        [sys.executable, 'manage.py', 'migrate', '--noinput'],
        [sys.executable, 'manage.py', 'collectstatic', '--noinput'],
    ]
    for command in commands:
        status_write('running', f'Running {" ".join(command[1:])}', backup=str(backup))
        subprocess.run(command, cwd=settings.BASE_DIR, check=True, timeout=1200)
    # Keep Chromium/X11 running while restarting just the managed backend.
    subprocess.run(['bash', 'scripts/start_slidercms.sh', '--backend-only'],
                   cwd=settings.BASE_DIR, check=True, timeout=180,
                   env={**os.environ, 'HOST': runtime['host'], 'PORT': runtime['port']})
    status_write('success', 'Update installed. Refresh this page.', sha=sha, backup=str(backup))
