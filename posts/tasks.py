import fcntl
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from scripts import cec_control
from .models import ScreenPowerSchedule


screen_power_logger = logging.getLogger('screen_power')


@shared_task(name='posts.tasks.turn_tv_on', ignore_result=True)
def turn_tv_on():
    cec_control.power_on()
    screen_power_logger.info('TV reported power ON.')


@shared_task(name='posts.tasks.turn_tv_off', ignore_result=True)
def turn_tv_off():
    cec_control.power_off()
    screen_power_logger.info('TV reported STANDBY.')


def schedule_target(schedule, now):
    """Latest daily boundary; ambiguous hours use the first occurrence."""
    on = schedule.screen_on_time.replace(second=0, microsecond=0)
    off = schedule.screen_off_time.replace(second=0, microsecond=0)
    if on == off:
        raise ValueError('Screen on and off times must be different.')
    events = []
    for day in (now.date() - timedelta(days=1), now.date()):
        for at, state in ((on, 'on'), (off, 'off')):
            boundary = datetime.combine(day, at, tzinfo=now.tzinfo)
            # Move a nonexistent spring-forward time to the first valid minute.
            for _ in range(180):
                round_trip = boundary.astimezone(dt_timezone.utc).astimezone(now.tzinfo)
                if round_trip.replace(tzinfo=None) == boundary.replace(tzinfo=None):
                    break
                boundary += timedelta(minutes=1)
            instant = boundary.astimezone(dt_timezone.utc)
            if instant <= now.astimezone(dt_timezone.utc):
                events.append((instant, state == 'off', state, f'{day.isoformat()}:{at:%H:%M}:{state}'))
    _, _, state, slot = max(events)
    return state, slot


@shared_task(name='posts.tasks.apply_screen_power_schedule', ignore_result=True)
def apply_screen_power_schedule():
    # Never keep an SQLite write transaction open while talking to the TV.
    path = settings.LOG_DIR / 'screen-schedule.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 'busy'
        schedule = ScreenPowerSchedule.load()
        now = timezone.localtime()
        ScreenPowerSchedule.objects.filter(pk=schedule.pk).update(last_scheduler_check=now)
        if not schedule.is_enabled:
            return 'disabled'
        try:
            state, slot = schedule_target(schedule, now)
            if schedule.last_applied_slot == slot:
                return 'already applied'
            if (schedule.last_error and schedule.last_attempt_at
                    and now - schedule.last_attempt_at < timedelta(minutes=5)
                    and schedule_target(schedule, timezone.localtime(schedule.last_attempt_at))[1] == slot):
                return 'retry pending'
            ScreenPowerSchedule.objects.filter(pk=schedule.pk).update(last_attempt_at=now)
            screen_power_logger.info('Applying screen schedule: state=%s slot=%s timezone=%s', state, slot, settings.TIME_ZONE)
            (turn_tv_on if state == 'on' else turn_tv_off)()
        except Exception as error:
            ScreenPowerSchedule.objects.filter(pk=schedule.pk).update(
                last_error=str(error)[-2000:], last_attempt_at=now)
            screen_power_logger.exception('Screen power schedule failed; will retry in five minutes')
            return 'failed'
        # Do not acknowledge an obsolete slot if settings changed during CEC I/O.
        ScreenPowerSchedule.objects.filter(
            pk=schedule.pk, screen_on_time=schedule.screen_on_time,
            screen_off_time=schedule.screen_off_time, is_enabled=True,
        ).update(last_applied_slot=slot, last_error='',
                 **{f'last_screen_{state}_run': timezone.now()})
        return state
