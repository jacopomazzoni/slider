import fcntl
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from posts import updates


class UpdateTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.override = override_settings(BASE_DIR=self.root, DATA_DIR=self.root / 'data',
            LOG_DIR=self.root / 'data/logs', SLIDERCMS_UPDATE_REPOSITORY='example/sliderCMS',
            SLIDERCMS_UPDATE_BRANCH='main', SLIDERCMS_UPDATES_ENABLED=True)
        self.override.enable()
        self.addCleanup(self.override.disable)
        cache.clear()

    def test_private_content_classification(self):
        for path in ['db.sqlite3', 'db.sqlite3-wal', 'media/a.png', 'data/a', '.env',
                     '.env.production', '.secret_key', 'a/__pycache__/b.pyc', 'updates/status.json',
                     'templates/dateline_announcements.json', 'backup.zip']:
            self.assertTrue(updates.private_path(path), path)
        for path in ['templates/static/logo.png', 'posts/models.py', '.env.example',
                     'posts/migrations/0001_initial.py']:
            self.assertFalse(updates.private_path(path), path)

    def test_source_rejects_urls_and_shell_arguments(self):
        with override_settings(SLIDERCMS_UPDATE_REPOSITORY='https://evil.example/repo'):
            with self.assertRaises(updates.UpdateError):
                updates.source()
        with override_settings(SLIDERCMS_UPDATE_BRANCH='--upload-pack=command'):
            with self.assertRaises(updates.UpdateError):
                updates.source()

    @patch('posts.updates.os.kill')
    @patch('posts.updates.subprocess.run')
    def test_stale_pid_cannot_stop_another_project(self, run, kill):
        run.return_value.stdout = '/another/project/.venv/bin/celery -A sliderCMS worker'
        with self.assertRaises(updates.UpdateError):
            updates.stop_managed(999999, 'celery')
        kill.assert_not_called()

    @patch('posts.updates.os.kill')
    def test_invalid_pid_cannot_signal_process_group(self, kill):
        for pid in [0, 1, -1, os.getpid()]:
            with self.assertRaises(updates.UpdateError):
                updates.stop_managed(pid, 'manage.py runserver')
        kill.assert_not_called()

    @patch('posts.updates.requests.get')
    @patch('posts.updates.git', return_value='a' * 40)
    @patch('posts.updates.clean_checkout')
    def test_checks_cached_and_requires_managed_process(self, clean, git, get):
        get.return_value.json.return_value = [{'sha': 'b' * 40}]
        log = self.root / 'data/logs'
        log.mkdir(parents=True)
        (log / 'runtime.json').write_text(json.dumps({'pid': os.getpid()}))
        self.assertTrue(updates.check_update()['can_install'])
        self.assertTrue(updates.check_update()['available'])
        self.assertEqual(get.call_count, 1)
        (log / 'runtime.json').write_text(json.dumps({'pid': -1}))
        self.assertFalse(updates.check_update()['can_install'])

    @patch('posts.updates.git')
    def test_dirty_tree_and_tracked_data_refused(self, git):
        git.side_effect = [str(self.root), ' M posts/views.py']
        with self.assertRaisesRegex(updates.UpdateError, 'Local code changes'):
            updates.clean_checkout()
        git.side_effect = [str(self.root), '', 'posts/views.py\nmedia/private.png']
        with self.assertRaisesRegex(updates.UpdateError, 'Private runtime'):
            updates.clean_checkout()

    @patch('posts.updates.check_update', return_value={'can_install': True, 'latest': 'b'*40})
    @patch('posts.updates.subprocess.Popen')
    def test_duplicate_update_lock(self, popen, check):
        with (updates.update_dir() / 'update.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(updates.UpdateError, 'already running'):
                updates.launch_update('b'*40)
        popen.assert_not_called()
        updates.launch_update('b'*40)
        self.assertEqual(popen.call_count, 1)
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertEqual(updates.status_read()['state'], 'running')

    @patch('posts.updates.clean_checkout')
    @patch('posts.updates.git')
    @patch('posts.updates.stop_managed')
    def test_changed_remote_refused_before_stopping_server(self, stop, git, clean):
        git.side_effect = ['a'*40, '', 'c'*40]
        with self.assertRaisesRegex(updates.UpdateError, 'changed since'):
            updates.run_update('b'*40)
        stop.assert_not_called()

    @patch('posts.updates.clean_checkout')
    @patch('posts.updates.git')
    @patch('posts.updates.stop_managed')
    def test_incoming_private_files_refused(self, stop, git, clean):
        git.side_effect = ['a'*40, '', 'b'*40, '', 'media/private.png']
        with self.assertRaisesRegex(updates.UpdateError, 'Incoming commit'):
            updates.run_update('b'*40)
        stop.assert_not_called()

    @patch('posts.updates.clean_checkout')
    @patch('posts.updates.git')
    @patch('posts.updates.stop_managed')
    @patch('posts.updates.time.sleep')
    @patch('posts.updates.subprocess.run')
    def test_update_backs_up_database_before_migrations(self, run, sleep, stop, git, clean):
        git.side_effect = ['a'*40, '', 'b'*40, '', 'manage.py\nposts/models.py', '']
        log = self.root / 'data/logs'
        log.mkdir(parents=True)
        (log / 'runtime.json').write_text(json.dumps({'pid': 123, 'host': '0.0.0.0', 'port': '8021'}))
        db = self.root / 'data/db.sqlite3'
        with sqlite3.connect(db) as conn:
            conn.execute('CREATE TABLE private_content (value TEXT)')
            conn.execute("INSERT INTO private_content VALUES ('keep me')")
        with override_settings(DATABASES={'default': {'NAME': str(db)}}):
            updates.run_update('b'*40)
        status = updates.status_read()
        with sqlite3.connect(Path(status['backup']) / 'db.sqlite3') as conn:
            self.assertEqual(conn.execute('SELECT value FROM private_content').fetchone()[0], 'keep me')
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(any('migrate' in command for command in commands))
        self.assertEqual(commands[-1], ['bash', 'scripts/start_slidercms.sh', '--backend-only'])
        self.assertEqual(status['state'], 'success')


class UpdateAccessTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username='admin', password='test')
        self.user = get_user_model().objects.create_user(username='user', password='test')

    @patch('posts.update_views.check_update')
    @patch('posts.update_views.launch_update')
    def test_superuser_only_and_post_only(self, launch, check):
        for user in [None, self.user]:
            if user:
                self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('update_check')).status_code, 403)
            self.assertEqual(self.client.post(reverse('update_install')).status_code, 403)
        launch.assert_not_called()
        check.assert_not_called()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('update_install')).status_code, 405)
        response = self.client.post(reverse('update_install'), {'sha': 'a'*40})
        self.assertEqual(response.status_code, 202)

    def test_install_requires_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse('update_install'), {'sha': 'a'*40}).status_code, 403)

    def test_update_controls_not_on_public_home(self):
        self.assertNotContains(self.client.get('/'), 'software-update-title')
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/'), 'software-update-title')

    @patch('posts.management.commands.setup_site.call_command')
    def test_setup_preserves_existing_admin(self, command):
        call_command('setup_site', stdout=io.StringIO())
        command.assert_called_once_with('migrate', interactive=False)

    @patch('posts.management.commands.setup_site.call_command')
    def test_first_setup_prompts_and_noninteractive_fails_without_admin(self, command):
        self.admin.delete()
        with self.assertRaises(CommandError):
            call_command('setup_site', no_input=True, stdout=io.StringIO())
        call_command('setup_site', stdout=io.StringIO())
        self.assertEqual(command.call_args.args, ('createsuperuser',))
        self.assertTrue(command.call_args.kwargs['interactive'])
