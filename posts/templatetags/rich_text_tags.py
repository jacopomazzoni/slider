from django import template
from django.utils.safestring import mark_safe

from posts.rich_text import render_rich_text

register = template.Library()


@register.filter
def rich_text(value):
    # Only sanitized markup and locally generated images are trusted.
    return mark_safe(render_rich_text(value))
