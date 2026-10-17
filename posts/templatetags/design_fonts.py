from django import template

from posts.design import GOOGLE_MONO_FONTS, GOOGLE_SANS_FONTS, GOOGLE_SERIF_FONTS, SYSTEM_FONTS

register = template.Library()


@register.simple_tag
def design_font_groups():
    return (
        ('System fonts', SYSTEM_FONTS),
        ('Google Fonts - Serif', GOOGLE_SERIF_FONTS),
        ('Google Fonts - Sans-serif', GOOGLE_SANS_FONTS),
        ('Google Fonts - Monospace', GOOGLE_MONO_FONTS),
    )
