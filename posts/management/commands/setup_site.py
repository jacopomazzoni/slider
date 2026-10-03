from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError, call_command


class Command(BaseCommand):
    help = 'Create the database and interactively set up the first administrator.'

    def add_arguments(self, parser):
        parser.add_argument('--no-input', action='store_true')

    def handle(self, *args, **options):
        call_command('migrate', interactive=False)
        if get_user_model().objects.filter(is_superuser=True, is_active=True).exists():
            self.stdout.write('An administrator already exists; credentials were not changed.')
            return
        if options['no_input']:
            raise CommandError('No administrator exists. Run manage.py setup_site interactively to set a password.')
        self.stdout.write('Create your first administrator. The password is prompted securely, not stored in .env.')
        call_command('createsuperuser', interactive=True)
