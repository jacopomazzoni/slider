"""Request-level operator history. Never capture request bodies or credentials."""
import logging

from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db import transaction

from .models import ActivityLog

logger = logging.getLogger(__name__)

ACTIONS = {
    'update_install': 'Install software update',
    'add_slide': 'Add slide', 'edit_slide_image': 'Edit image',
    'edit_rich_text_slide': 'Edit rich text', 'edit_html_slide': 'Edit HTML',
    'edit_google_slides_slide': 'Edit Google Slides', 'delete_image': 'Delete slide',
    'update_slide_duration': 'Change slide playback', 'update_slide_title': 'Rename slide',
    'update_slide_visibility': 'Change slide visibility', 'reorder_slides': 'Reorder slides',
    'reorder_sections': 'Reorder display sections',
    'update_generated_slide_config': 'Change Dateline settings',
    'update_weather_slide_config': 'Change weather settings',
    'update_calendar_slide_config': 'Change calendar settings',
    'update_transit_dashboard_config': 'Change transit settings',
    'update_empty_display_config': 'Change empty-display settings',
    'update_breaking_news_ticker_config': 'Change ticker settings',
    'update_site_appearance': 'Change site settings',
    'update_screen_power_schedule': 'Change screen power schedule',
    'reset_user_password': 'Reset user password', 'toggle_superuser': 'Change user role',
    'import_site_migration': 'Import site archive', 'export_site_migration': 'Export site archive',
    'rich_text_qr': 'Generate QR code', 'signup': 'Create user',
    'login': 'Log in', 'logout': 'Log out',
    'password_change': 'Change password', 'password_reset': 'Request password reset',
    'password_reset_confirm': 'Complete password reset',
}


def activity_success(request, text):
    request.activity_succeeded = True
    request.activity_detail = str(text)[:300]
    messages.success(request, text)


def record_activity(*, user_id, username, action, target='', outcome='success'):
    def write():
        try:
            actor_id = user_id if user_id and get_user_model().objects.filter(pk=user_id).exists() else None
            ActivityLog.objects.create(user_id=actor_id, username=username[:150],
                                       action=action[:160], target=target[:300], outcome=outcome)
        except Exception:
            # Logging must not turn an already completed operation into an error.
            logger.exception('Unable to persist activity log entry')
    transaction.on_commit(write)
