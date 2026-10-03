import fcntl
import os

from django.core.management import BaseCommand, CommandError
from posts.updates import run_update, status_write, update_dir


class Command(BaseCommand):
    help = 'Install an approved GitHub commit (normally launched from the admin dashboard).'

    def add_arguments(self, parser):
        parser.add_argument('sha')
        parser.add_argument('--lock-fd', type=int)

    def handle(self, *args, **options):
        fd = options['lock_fd']
        lock = os.fdopen(fd, 'a') if fd is not None else (update_dir() / 'update.lock').open('a')
        acquired = False
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            run_update(options['sha'])
        except Exception as error:
            if acquired:
                status_write('failed', f'Update stopped: {error}. See update.log and the backup directory before restarting.')
            raise CommandError(str(error)) from error
        finally:
            lock.close()
