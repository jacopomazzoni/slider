import logging
from uuid import uuid4

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .activity import activity_success
from .design import MAX_DOCUMENT_BYTES, raster, read_document
from .models import Post

logger = logging.getLogger('upload_errors')


class DesignSlideForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ['title', 'duration_seconds', 'transition_type']


@login_required
@require_http_methods(['GET', 'POST'])
def design_editor(request, pk=None):
    post = get_object_or_404(Post, pk=pk, content_type=Post.CONTENT_DESIGN) if pk is not None else None
    if request.method == 'GET':
        return render(request, 'design_edit.html', {'design_post': post,
                      'slide_transition_choices': Post.TRANSITION_CHOICES})
    form = DesignSlideForm(request.POST, instance=post)
    if not form.is_valid():
        return JsonResponse({'error': ' '.join(error for errors in form.errors.values() for error in errors)}, status=400)
    try:
        document_upload = request.FILES.get('document')
        preview = request.FILES.get('preview')
        if not document_upload or not preview:
            raise ValidationError('Save both the layout and its rendered preview.')
        document = read_document(document_upload)
        if preview.size > MAX_DOCUMENT_BYTES:
            raise ValidationError('The rendered slide is too large (12 MB maximum).')
        image_data = preview.read(MAX_DOCUMENT_BYTES + 1)
        raster(image_data, expected_size=(document['width'] * 2, document['height'] * 2))
    except ValidationError as error:
        return JsonResponse({'error': ' '.join(error.messages)}, status=400)
    old_cover = post.cover.name if post and post.cover else None
    content = form.save(commit=False)
    content.content_type = Post.CONTENT_DESIGN
    content.design_document = document
    new_cover = None
    try:
        with transaction.atomic():
            content.cover.save(f'design-{uuid4().hex}.png', ContentFile(image_data), save=False)
            new_cover = content.cover.name
            content.save()
            if old_cover:
                transaction.on_commit(lambda: default_storage.delete(old_cover))
    except Exception:
        if new_cover:
            default_storage.delete(new_cover)
        logger.exception('Slide design save failed user=%s', request.user.pk)
        return JsonResponse({'error': 'The slide could not be saved. Your design is still open; please retry.'}, status=500)
    activity_success(request, f'Slide design saved: {content.title} (ID {content.pk}).')
    return JsonResponse({'redirect': reverse('manage_slides'), 'id': content.pk})
