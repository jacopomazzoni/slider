from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ActivityLog, Post


class ActivityLogTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('admin-log', password='test')
        self.operator = get_user_model().objects.create_user('operator-log', password='test')
        self.slide = Post.objects.create(title='Announcement', content_type=Post.CONTENT_RICH_TEXT, description='<p>Hello</p>')

    def post(self, name, data=None, args=None):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse(name, args=args), data or {})

    def test_all_operators_changes_and_validation_failures_are_recorded(self):
        self.client.force_login(self.operator)
        self.post('update_slide_title', {'title': 'Renamed'}, [self.slide.pk])
        entry = ActivityLog.objects.get()
        self.assertEqual(entry.username, 'operator-log')
        self.assertEqual(entry.outcome, 'success')
        self.assertIn('Renamed', entry.target)
        self.assertIsNotNone(entry.occurred_at)
        self.post('update_slide_duration', {'duration_seconds': '-1'}, [self.slide.pk])
        self.assertEqual(ActivityLog.objects.first().outcome, 'failed')
        self.client.force_login(self.admin)
        self.post('delete_image', args=[self.slide.pk])
        entry = ActivityLog.objects.first()
        self.assertEqual(entry.username, 'admin-log')
        self.assertEqual(entry.action, 'Delete slide')
        self.assertIn('Renamed', entry.target)

    def test_passwords_tokens_and_qr_contents_are_not_logged(self):
        self.client.force_login(self.admin)
        secret = 'private-password'
        self.post('reset_user_password', {'user': self.operator.pk, 'new_password1': secret, 'new_password2': secret})
        self.post('rich_text_qr', {'text': 'private-qr-content', 'size': '192'})
        entries = str(list(ActivityLog.objects.values()))
        self.assertNotIn(secret, entries)
        self.assertNotIn('private-qr-content', entries)
        self.assertEqual(ActivityLog.objects.count(), 2)
        self.assertTrue(all(entry.outcome == 'success' for entry in ActivityLog.objects.all()))

    def test_real_login_logout_and_failed_login(self):
        self.post('login', {'username': self.operator.username, 'password': 'wrong-secret'})
        entry = ActivityLog.objects.get()
        self.assertEqual(entry.outcome, 'failed')
        self.assertNotIn('wrong-secret', entry.target)
        self.post('login', {'username': self.operator.username, 'password': 'test'})
        self.assertEqual(ActivityLog.objects.first().user_id, self.operator.pk)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('logout'))
        entry = ActivityLog.objects.first()
        self.assertEqual(entry.action, 'Log out')
        self.assertEqual(entry.user_id, self.operator.pk)

    def test_signup_and_role_changes_record_target(self):
        self.client.force_login(self.admin)
        self.post('signup', {'username': 'new-operator', 'email': 'new@example.com', 'password1': 'test', 'password2': 'test'})
        entry = ActivityLog.objects.get()
        self.assertEqual(entry.username, self.admin.username)
        self.assertIn('new-operator', entry.target)
        self.post('toggle_superuser', args=[self.operator.pk])
        self.assertEqual(ActivityLog.objects.first().outcome, 'success')
        self.assertIn('superuser', ActivityLog.objects.first().target)

    def test_settings_log_is_superuser_only_paginated_and_escaped(self):
        ActivityLog.objects.bulk_create([
            ActivityLog(username='<script>actor</script>', action='Edit slide', target='<script>unsafe</script>', outcome='success')
            for _ in range(30)
        ])
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('settings')).status_code, 302)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('settings'))
        self.assertContains(response, 'Activity Log')
        self.assertContains(response, '&lt;script&gt;unsafe&lt;/script&gt;')
        self.assertNotContains(response, '<script>unsafe</script>')
        self.assertEqual(len(response.context['activity_page']), 25)
        response = self.client.get(reverse('settings'), {'activity_page': 2})
        self.assertEqual(len(response.context['activity_page']), 5)
        self.assertContains(response, '<time datetime=')

    def test_logs_survive_actor_deletion(self):
        self.client.force_login(self.operator)
        self.post('update_slide_title', {'title': 'Renamed'}, [self.slide.pk])
        self.operator.delete()
        entry = ActivityLog.objects.get()
        self.assertIsNone(entry.user_id)
        self.assertEqual(entry.username, 'operator-log')

    def test_dashboard_polls_and_read_only_requests_do_not_write_logs(self):
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.get(reverse('settings'))
            self.client.get(reverse('transit_mobile'))
            self.client.get(reverse('transit_mobile_qr'))
            with patch('posts.views._transit_api', return_value=({}, False)):
                self.client.get(reverse('transit_mobile_live_data'))
        self.assertFalse(ActivityLog.objects.exists())

    def test_unauthorized_action_is_not_marked_success(self):
        self.post('toggle_superuser', args=[self.operator.pk])
        entry = ActivityLog.objects.get()
        self.assertEqual(entry.outcome, 'failed')
        self.assertEqual(entry.username, 'Anonymous')

    def test_rolled_back_transaction_does_not_keep_success_entry(self):
        from django.db import transaction
        from .activity import record_activity
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    record_activity(user_id=self.admin.pk, username=self.admin.username, action='Change settings')
                    raise ValueError('Rollback')
            except ValueError:
                pass
        self.assertFalse(ActivityLog.objects.exists())

    def test_unavailable_log_does_not_break_completed_action(self):
        self.client.force_login(self.operator)
        with patch('posts.activity.ActivityLog.objects.create', side_effect=RuntimeError('Unavailable')):
            with patch('posts.activity.logger.exception') as error_log:
                response = self.post('update_slide_title', {'title': 'Completed'}, [self.slide.pk])
        self.assertEqual(response.status_code, 302)
        self.slide.refresh_from_db()
        self.assertEqual(self.slide.title, 'Completed')
        error_log.assert_called_once()
