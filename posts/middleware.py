from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class ActivityLogMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        from .activity import ACTIONS
        match = request.resolver_match
        name = match.url_name
        is_admin = match.app_name == 'admin' and request.method == 'POST'
        if not is_admin and (name not in ACTIONS or (
            request.method != 'POST' and name not in ('logout', 'export_site_migration')
        )):
            return
        user = request.user
        request.activity_event = {
            'user_id': user.pk if user.is_authenticated else None,
            'username': user.get_username() if user.is_authenticated else 'Anonymous',
            'action': ACTIONS.get(name, f'Django admin: {name}'),
            'target': '',
        }
        object_id = view_kwargs.get('pk') or view_kwargs.get('object_id')
        if object_id:
            request.activity_event['target'] = f'ID {object_id}'
        request.activity_route = name
        request.activity_admin = is_admin
        request.activity_admin_authorized = user.is_authenticated and user.is_active and user.is_staff

    def process_response(self, request, response):
        from .activity import record_activity
        event = getattr(request, 'activity_event', None)
        if event is None:
            return response
        name = request.activity_route
        success = getattr(request, 'activity_succeeded', False)
        if name in ('login', 'password_change', 'password_reset'):
            success = response.status_code == 302
        if name == 'password_change':
            success = success and request.user.is_authenticated
        if name == 'logout':
            success = event['user_id'] is not None and response.status_code == 302
        if name in ('rich_text_qr', 'export_site_migration'):
            success = response.status_code == 200 and request.user.is_authenticated
        if name == 'login' and success:
            event.update(user_id=request.user.pk, username=request.user.get_username())
        if name == 'login' and not success:
            event['target'] = str(request.POST.get('username', ''))[:150]
        detail = getattr(request, 'activity_detail', '')
        if detail:
            event['target'] = f"{event['target']}: {detail}" if event['target'] else detail
        event['outcome'] = 'success' if success and response.status_code < 400 else 'failed'
        if request.activity_admin and request.activity_admin_authorized and name not in ('login', 'logout', 'password_change') and response.status_code < 400:
            event['outcome'] = 'success' if response.status_code == 302 else 'submitted'
        record_activity(**event)
        return response


class MediaCacheControlMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(settings.MEDIA_URL) and response.status_code == 200:
            response.setdefault("Cache-Control", "public, max-age=31536000, immutable, stale-while-revalidate=86400")
            response.setdefault("X-Content-Type-Options", "nosniff")
        return response
