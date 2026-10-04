import os
from pathlib import Path
import re
import subprocess
import tempfile

from django.conf import settings
from django.test import SimpleTestCase


class StartupHookTests(SimpleTestCase):
    def run_hook(self, contents=None, calls='start_extra_hook'):
        source = (settings.BASE_DIR / 'scripts/start_slidercms.sh').read_text()
        names = ['log', 'warn', 'write_pid', 'read_pid', 'is_pid_running', 'start_extra_hook']
        functions = '\n'.join(re.search(rf'^{name}\(\) \{{.*?^\}}', source, re.S | re.M)[0] for name in names)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / 'logs').mkdir()
            if contents is not None:
                (root / 'scripts/extra_startup.sh').write_text(contents)
            result = subprocess.run(['bash', '-c', 'set -Eeuo pipefail\n' + functions + '\n' + calls],
                env={**os.environ, 'PROJECT_DIR': directory, 'LOG_DIR': str(root / 'logs')},
                capture_output=True, text=True, timeout=10)
            marker = root / 'ran'
            return result, marker.read_text() if marker.exists() else ''

    def test_missing_hook_is_optional(self):
        result, _ = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_hook_failure_does_not_stop_launcher(self):
        result, _ = self.run_hook('exit 7\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Extra startup hook failed', result.stderr)

    def test_running_hook_is_not_duplicated(self):
        result, marker = self.run_hook('printf x >> "$PROJECT_DIR/ran"\nsleep 3\n',
            'start_extra_hook\nstart_extra_hook\nwait "$(cat "$LOG_DIR/extra_startup.pid")"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker, 'x')
        self.assertIn('already running', result.stdout)

    def test_hook_runs_after_backend_and_django_path_is_absolute(self):
        source = (settings.BASE_DIR / 'scripts/start_slidercms.sh').read_text()
        self.assertIn('"$PYTHON_BIN" "$PROJECT_DIR/manage.py" runserver', source)
        self.assertIn('  start_django\n  start_celery\n  start_extra_hook\n  start_kiosk_session', source)
