import requests
import subprocess
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from accounts.permissions import is_site_admin
from .activity import activity_success
from .updates import UpdateError, check_update, launch_update, status_read


@require_GET
def update_check(request):
    if not is_site_admin(request.user):
        return JsonResponse({'error': 'Superuser access required.'}, status=403)
    try:
        result = check_update()
        result['job'] = status_read()
        response = JsonResponse(result)
    except (UpdateError, requests.RequestException, OSError, ValueError, subprocess.SubprocessError) as error:
        response = JsonResponse({'error': str(error), 'job': status_read()}, status=400)
    response['Cache-Control'] = 'no-store'
    return response


@require_POST
def update_install(request):
    if not is_site_admin(request.user):
        return JsonResponse({'error': 'Superuser access required.'}, status=403)
    try:
        launch_update(request.POST.get('sha', ''))
    except (UpdateError, requests.RequestException, OSError, ValueError, subprocess.SubprocessError) as error:
        return JsonResponse({'error': str(error)}, status=400)
    activity_success(request, 'Started GitHub software update.')
    return JsonResponse({'message': 'Update started. The server will briefly go offline.'}, status=202)
