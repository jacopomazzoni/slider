from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.utils import timezone

from posts.models import ScreenPowerSchedule
from posts.tasks import schedule_target
from scripts import cec_control


class Command(BaseCommand):
    help = 'Read scheduler health and CEC adapter status without switching TV power.'

    def add_arguments(self, parser):
        parser.add_argument('--query-tv', action='store_true', help='Also ask the configured TV for its power status.')

    def handle(self, *args, **options):
        self.stdout.write(f'Application time: {timezone.localtime():%Y-%m-%d %H:%M:%S %Z} ({settings.TIME_ZONE})')
        schedule = ScreenPowerSchedule.objects.first()
        if schedule:
            self.stdout.write(f'Schedule enabled: {schedule.is_enabled}; on {schedule.screen_on_time}, off {schedule.screen_off_time}')
            self.stdout.write(f'Scheduler recently seen: {schedule.scheduler_healthy}; last check: {schedule.last_scheduler_check}')
            try:
                state, slot = schedule_target(schedule, timezone.localtime())
                self.stdout.write(f'Current scheduled state: {state}; slot: {slot}')
            except ValueError as error:
                self.stdout.write(str(error))
            self.stdout.write(f'Last confirmed on: {schedule.last_screen_on_run}; standby: {schedule.last_screen_off_run}')
            self.stdout.write(f'Last error: {schedule.last_error or "none"}')
        else:
            self.stdout.write('No schedule saved yet; the scheduler has not initialized it.')
        self.stdout.write(f'Logs: {settings.LOG_DIR / "screen_power.log"} and {settings.LOG_DIR / "celery.log"}')
        try:
            _, output = cec_control.list_adapters()
            self.stdout.write(output)
            adapter = cec_control.select_adapter()
            self.stdout.write(f'Selected CEC adapter: {adapter}')
            if options['query_tv']:
                with cec_control.adapter_lock():
                    self.stdout.write(f'TV reports: {cec_control.power_status(adapter)}')
        except Exception as error:
            raise CommandError(str(error)) from error
