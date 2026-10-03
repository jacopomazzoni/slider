from contextlib import nullcontext
from datetime import datetime, time, timedelta
import fcntl
import io
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from posts.forms import ScreenPowerScheduleForm
from posts.models import ScreenPowerSchedule
from posts.tasks import apply_screen_power_schedule, schedule_target
from scripts import cec_control as cec


class CECHardwareTests(SimpleTestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'CEC_CLIENT_BIN': '/usr/bin/cec-client',
            'CEC_RETRIES': '1', 'CEC_POWER_ON_SETTLE_SECONDS': '0',
            'CEC_POWER_OFF_SETTLE_SECONDS': '0'}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    @patch('scripts.cec_control.subprocess.run')
    def test_zero_exit_with_error_is_not_success(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, 'ERROR: command was not acked', '')
        with self.assertRaises(cec.CECControlError):
            cec._run_cec_commands(['standby 0'], adapter='/dev/cec0')

    @patch('scripts.cec_control.subprocess.run')
    def test_adapter_type_and_tv_port_are_explicit(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '', '')
        with patch.dict(os.environ, {'CEC_HDMI_PORT': '2'}):
            cec._run_cec_commands(['on 0'], adapter='/dev/cec1')
        self.assertEqual(run.call_args.args[0], ['/usr/bin/cec-client', '-s', '-d', '1',
            '-t', 'p', '-o', 'sliderCMS', '-p', '2', '/dev/cec1'])
        self.assertEqual(run.call_args.kwargs['input'], 'on 0\n')

    @patch('scripts.cec_control.subprocess.run')
    def test_multiple_adapters_are_not_silently_guessed(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, 'com port: /dev/cec0\ncom port: /dev/cec1', '')
        with self.assertRaisesRegex(cec.CECControlError, 'Multiple CEC adapters'):
            cec.select_adapter()

    @patch('scripts.cec_control.os.access', return_value=False)
    def test_permissions_are_actionable(self, access):
        with patch.dict(os.environ, {'CEC_ADAPTER': '/dev/cec1'}):
            with self.assertRaisesRegex(cec.CECControlError, 'Cannot read/write'):
                cec.select_adapter()

    @patch('scripts.cec_control._run_cec_commands')
    @patch('scripts.cec_control.select_adapter', return_value='RPI')
    @patch('scripts.cec_control.adapter_lock', side_effect=nullcontext)
    def test_on_requires_confirmed_power_status(self, lock, adapter, run):
        run.return_value = subprocess.CompletedProcess([], 0, 'power status: on\n', '')
        cec.power_on()
        self.assertEqual([call.args[0] for call in run.call_args_list], [['on 0'], ['as'], ['pow 0']])

    @patch('scripts.cec_control._run_cec_commands')
    @patch('scripts.cec_control.select_adapter', return_value='RPI')
    @patch('scripts.cec_control.adapter_lock', side_effect=nullcontext)
    def test_off_unknown_status_fails(self, lock, adapter, run):
        run.return_value = subprocess.CompletedProcess([], 0, 'power status: unknown\n', '')
        with self.assertRaisesRegex(cec.CECControlError, 'not confirmed'):
            cec.power_off()

    @patch('scripts.cec_control.subprocess.run', side_effect=subprocess.TimeoutExpired('cec-client', 20))
    def test_command_timeout_propagates(self, run):
        with self.assertRaises(subprocess.TimeoutExpired):
            cec._run_cec_commands(['on 0'], adapter='RPI')

    def test_single_command_and_numeric_validation(self):
        with self.assertRaises(cec.CECControlError):
            cec._run_cec_commands(['on 0', 'as'], adapter='RPI')
        with patch.dict(os.environ, {'CEC_RETRIES': '0'}):
            with self.assertRaises(cec.CECControlError):
                cec._retry('test', lambda: None)
        with patch.dict(os.environ, {'CEC_RETRY_DELAY_SECONDS': 'nan'}):
            with self.assertRaises(cec.CECControlError):
                cec._env_float('CEC_RETRY_DELAY_SECONDS', 2)


class ScreenScheduleTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = override_settings(LOG_DIR=Path(self.directory.name))
        override.enable()
        self.addCleanup(override.disable)
        self.schedule = ScreenPowerSchedule.load()
        self.now = datetime(2026, 10, 1, 10, 7, tzinfo=ZoneInfo('America/New_York'))

    @patch('posts.tasks.turn_tv_on')
    @patch('posts.tasks.timezone.localtime')
    def test_late_start_catches_up_once(self, clock, power):
        clock.return_value = self.now
        self.assertEqual(apply_screen_power_schedule(), 'on')
        self.assertEqual(apply_screen_power_schedule(), 'already applied')
        power.assert_called_once()
        self.schedule.refresh_from_db()
        self.assertIsNotNone(self.schedule.last_scheduler_check)
        self.assertIsNotNone(self.schedule.last_screen_on_run)
        self.assertEqual(self.schedule.last_applied_slot, '2026-10-01:08:00:on')

    def test_overnight_window(self):
        self.schedule.screen_on_time = time(20)
        self.schedule.screen_off_time = time(6)
        state, slot = schedule_target(self.schedule, self.now.replace(hour=2))
        self.assertEqual((state, slot), ('on', '2026-09-30:20:00:on'))
        self.assertEqual(schedule_target(self.schedule, self.now)[0], 'off')

    def test_dst_boundaries(self):
        self.schedule.screen_on_time = time(1, 30)
        self.schedule.screen_off_time = time(1, 45)
        repeated = datetime(2026, 11, 1, 1, 35, fold=1, tzinfo=self.now.tzinfo)
        self.assertEqual(schedule_target(self.schedule, repeated)[0], 'off')
        self.schedule.screen_on_time = time(2, 30)
        self.schedule.screen_off_time = time(17)
        skipped = datetime(2026, 3, 8, 3, 0, tzinfo=self.now.tzinfo)
        self.assertEqual(schedule_target(self.schedule, skipped)[0], 'on')

    @patch('posts.tasks.turn_tv_on', side_effect=cec.CECControlError('No ACK from TV'))
    @patch('posts.tasks.timezone.localtime')
    def test_failure_is_visible_and_throttled_then_retried(self, clock, power):
        clock.return_value = self.now
        self.assertEqual(apply_screen_power_schedule(), 'failed')
        self.schedule.refresh_from_db()
        self.assertIsNone(self.schedule.last_screen_on_run)
        self.assertEqual(self.schedule.last_applied_slot, '')
        self.assertIn('No ACK', self.schedule.last_error)
        self.assertEqual(apply_screen_power_schedule(), 'retry pending')
        self.assertEqual(power.call_count, 1)
        clock.return_value = self.now + timedelta(minutes=5)
        power.side_effect = None
        self.assertEqual(apply_screen_power_schedule(), 'on')
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.last_error, '')

    @patch('posts.tasks.turn_tv_on')
    def test_disabled_schedule_does_not_touch_tv(self, power):
        self.schedule.is_enabled = False
        self.schedule.save()
        self.assertEqual(apply_screen_power_schedule(), 'disabled')
        power.assert_not_called()

    def test_duplicate_worker_is_locked_out(self):
        with (Path(self.directory.name) / 'screen-schedule.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(apply_screen_power_schedule(), 'busy')

    def test_equal_times_are_rejected(self):
        form = ScreenPowerScheduleForm(data={'is_enabled': 'on', 'screen_on_time': '08:00', 'screen_off_time': '08:00'})
        self.assertFalse(form.is_valid())

    def test_settings_warn_when_scheduler_missing(self):
        user = get_user_model().objects.create_superuser(username='operator', password='test')
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse('settings')), 'Not detected. Redis, Celery worker and Beat must be running.')

    @patch('scripts.cec_control.list_adapters', return_value=(['RPI'], 'com port: RPI'))
    @patch('scripts.cec_control.select_adapter', return_value='RPI')
    @patch('scripts.cec_control.power_status', return_value='standby')
    @patch('scripts.cec_control.adapter_lock', side_effect=nullcontext)
    @patch('scripts.cec_control.power_on')
    @patch('scripts.cec_control.power_off')
    def test_diagnostics_never_switch_power(self, off, on, lock, status, adapter, listing):
        output = io.StringIO()
        call_command('screen_power_status', query_tv=True, stdout=output)
        self.assertIn('TV reports: standby', output.getvalue())
        on.assert_not_called()
        off.assert_not_called()
