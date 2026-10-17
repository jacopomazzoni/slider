import base64
import copy
import json
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .design import MAX_DOCUMENT_BYTES, read_document, validate_document
from .models import Post
from .site_migration import build_site_manifest, replace_database_records


def design():
    return {'schema': 1, 'width': 1920, 'height': 1080, 'background': '#FFFFFF',
            'objects': [{'type': 'Textbox', 'text': 'Welcome', 'fontFamily': 'Georgia',
                         'fontSize': 72, 'left': 140, 'top': 230, 'width': 800, 'height': 90,
                         'fill': '#112233', 'locked': False}]}


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SlideDesignTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('designer', password='test')

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.client.force_login(self.user)

    def upload(self, document=None, size=(3840, 2160)):
        png = BytesIO()
        Image.new('RGB', size, '#ABCDEF').save(png, 'PNG')
        return {'title': 'Designed slide', 'duration_seconds': '12', 'transition_type': 'crossfade',
                'document': SimpleUploadedFile('design.json', json.dumps(document or design()).encode(), content_type='application/json'),
                'preview': SimpleUploadedFile('preview.png', png.getvalue(), content_type='image/png')}

    def create_slide(self):
        response = self.client.post(reverse('add_design_slide'), self.upload())
        self.assertEqual(response.status_code, 200, response.content)
        return Post.objects.get(pk=response.json()['id'])

    def test_add_tab_and_editor_render(self):
        self.assertContains(self.client.get(reverse('add_slide')), 'data-tab-target="design"')
        response = self.client.get(reverse('add_design_slide'))
        self.assertContains(response, 'fabric-7.4.0.min.js')
        self.assertContains(response, 'Fade to Black')
        self.assertContains(response, 'step="any"', count=5)
        self.assertContains(response, '<optgroup label="Google Fonts - Serif">')
        self.assertContains(response, '<optgroup label="Google Fonts - Sans-serif">')
        self.assertContains(response, '<optgroup label="Google Fonts - Monospace">')
        self.assertContains(response, '<option value="EB Garamond" data-google-font="true">EB Garamond</option>')
        self.assertContains(response, '<option value="Roboto" data-google-font="true">Roboto</option>')
        self.assertContains(response, 'data-style="underline"')

    def test_google_font_styles_and_underline_survive_save(self):
        document = design()
        document['objects'][0].update(fontFamily='Roboto', fontWeight='bold',
                                      fontStyle='italic', underline=True)
        response = self.client.post(reverse('add_design_slide'), self.upload(document))
        self.assertEqual(response.status_code, 200, response.content)
        slide = Post.objects.get(pk=response.json()['id'])
        self.assertEqual(slide.design_document['objects'][0]['fontFamily'], 'Roboto')
        self.assertTrue(slide.design_document['objects'][0]['underline'])
        self.assertEqual(slide.design_document['objects'][0]['fontWeight'], 'bold')
        self.assertEqual(slide.design_document['objects'][0]['fontStyle'], 'italic')
        self.assertContains(self.client.get(reverse('edit_design_slide', args=[slide.pk])), '"underline": true')

    def test_layer_effects_survive_save_and_invalid_effects_are_rejected(self):
        document = design()
        document['objects'][0].update(stroke='#123456', strokeWidth=4, shadowSettings={
            'color':'#000000', 'opacity':.4, 'blur':15, 'offsetX':-5, 'offsetY':8})
        document['objects'].append({'type':'Rect', 'width':300, 'height':200, 'cornerRadius':24})
        response = self.client.post(reverse('add_design_slide'), self.upload(document))
        self.assertEqual(response.status_code, 200, response.content)
        saved = Post.objects.get(pk=response.json()['id']).design_document['objects']
        self.assertEqual(saved[0]['strokeWidth'], 4)
        self.assertEqual(saved[0]['shadowSettings']['offsetX'], -5)
        self.assertEqual(saved[1]['cornerRadius'], 24)
        self.assertContains(self.client.get(reverse('edit_design_slide', args=[response.json()['id']])), '"cornerRadius": 24')
        for changes in ({'strokeWidth':101}, {'stroke':'url(https://example.com)'},
                        {'shadowSettings':{'color':'#000000', 'opacity':2}},
                        {'cornerRadius':float('inf')}):
            invalid = copy.deepcopy(document)
            invalid['objects'][1].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_document(invalid)

    def test_create_save_reopen_and_lightweight_playback(self):
        slide = self.create_slide()
        self.assertEqual(slide.content_type, Post.CONTENT_DESIGN)
        self.assertEqual(slide.design_document['objects'][0]['text'], 'Welcome')
        self.assertEqual(slide.duration_seconds, 12)
        with Image.open(slide.preview_image.path) as image:
            self.assertEqual(image.width, 250)
        self.assertEqual(len(slide.media_variants['display']), 1)
        self.assertEqual(slide.initial_display_url, slide.cover_media_url)
        self.assertContains(self.client.get(reverse('edit_design_slide', args=[slide.pk])), 'design-document')
        library = self.client.get(reverse('manage_slides'))
        self.assertContains(library, reverse('edit_design_slide', args=[slide.pk]))
        self.assertContains(library, slide.preview_url)
        response = self.client.get(reverse('paused_post_view', args=[slide.pk]))
        self.assertContains(response, slide.cover_media_url)
        self.assertContains(response, 'fullscreen-image')
        self.assertNotContains(response, 'fabric-7.4.0')
        self.assertNotContains(response, 'design-document')

    def test_edit_keeps_identity_and_removes_previous_render(self):
        slide = self.create_slide()
        previous = Path(slide.cover.path)
        document = design()
        document['objects'][0]['text'] = 'Updated'
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('edit_design_slide', args=[slide.pk]), self.upload(document))
        self.assertEqual(response.status_code, 200)
        slide.refresh_from_db()
        self.assertEqual(slide.design_document['objects'][0]['text'], 'Updated')
        self.assertFalse(previous.exists())
        self.assertEqual(Post.objects.count(), 1)

    def test_failed_validation_leaves_previous_slide_unchanged(self):
        slide = self.create_slide()
        response = self.client.post(reverse('edit_design_slide', args=[slide.pk]), self.upload(size=(250, 140)))
        self.assertEqual(response.status_code, 400)
        slide.refresh_from_db()
        self.assertEqual(slide.design_document['objects'][0]['text'], 'Welcome')
        self.assertTrue(Path(slide.cover.path).exists())

    def test_rejects_urls_scripts_invalid_numbers_fonts_and_too_many_layers(self):
        for override in ({'type': 'Group'}, {'left': float('inf')}, {'fontFamily':'https://example.com/font'},
                         {'type': 'Image', 'src':'https://example.com/track.png'},
                         {'type': 'Image', 'src':'data:image/svg+xml;base64,PHN2Zz4='}, {'opacity':2}):
            document = design()
            document['objects'][0].update(override)
            with self.subTest(override=override), self.assertRaises(ValidationError):
                validate_document(document)
        document = design()
        document['objects'] *= 81
        with self.assertRaises(ValidationError):
            validate_document(document)
        document = design()
        document['objects'][0]['underline'] = 'yes'
        with self.assertRaises(ValidationError):
            validate_document(document)

    def test_embedded_image_is_portable_and_unknown_properties_are_removed(self):
        buffer = BytesIO()
        Image.new('RGB', (32, 32), 'red').save(buffer, 'PNG')
        document = design()
        document['objects'].append({'type':'Image', 'src':'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode(),
                                    'width':32, 'height':32, 'cornerRadius':8, 'stroke':'#112233', 'strokeWidth':3,
                                    'shadowSettings':{'color':'#000000', 'opacity':.5, 'blur':7, 'offsetX':2, 'offsetY':3}})
        document['objects'][0]['clipPath'] = {'type':'Image', 'src':'https://example.com'}
        clean = validate_document(document)
        self.assertEqual(clean['objects'][1]['src'], document['objects'][1]['src'])
        self.assertEqual(clean['objects'][1]['cornerRadius'], 8)
        self.assertEqual(clean['objects'][1]['shadowSettings']['blur'], 7)
        self.assertNotIn('clipPath', clean['objects'][0])

    def test_invalid_json_and_oversized_document_are_rejected(self):
        with self.assertRaises(ValidationError):
            read_document(SimpleUploadedFile('x.json', b'not json'))
        with self.assertRaises(ValidationError):
            read_document(SimpleUploadedFile('x.json', b' ' * (MAX_DOCUMENT_BYTES + 1)))

    def test_export_import_preserves_editable_layout_and_older_archives_work(self):
        slide = self.create_slide()
        manifest = build_site_manifest()
        document = copy.deepcopy(slide.design_document)
        replace_database_records(manifest)
        self.assertEqual(Post.objects.get(pk=slide.pk).design_document, document)
        manifest['posts'][0]['fields'].pop('design_document')
        manifest['posts'][0]['fields']['content_type'] = Post.CONTENT_IMAGE
        replace_database_records(manifest)
        self.assertEqual(Post.objects.get(pk=slide.pk).design_document, {})

    def test_delete_removes_render_and_thumbnail(self):
        slide = self.create_slide()
        paths = [Path(slide.cover.path), Path(slide.preview_image.path)]
        self.client.post(reverse('delete_image', args=[slide.pk]))
        self.assertTrue(all(not path.exists() for path in paths))

    def test_save_failure_cleans_uploaded_render(self):
        with patch('posts.models.Post._rebuild_media_assets', side_effect=OSError('disk full')):
            response = self.client.post(reverse('add_design_slide'), self.upload())
        self.assertEqual(response.status_code, 500)
        self.assertFalse(Post.objects.exists())
        self.assertFalse(list(Path(self.media.name).rglob('*.png')))
