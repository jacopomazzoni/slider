from django import template
from django.urls import reverse


register = template.Library()


@register.simple_tag
def nav_items(user):
    is_authenticated = getattr(user, 'is_authenticated', False)
    is_superuser = getattr(user, 'is_superuser', False)

    items = [
        {
            'key': 'home',
            'label': 'Home',
            'url': reverse('home'),
            'icon': 'home',
            'description': 'Open the main dashboard and quick controls.',
        },
    ]

    if is_authenticated:
        items.extend([
            {
                'key': 'add_slide',
                'label': 'Add Slide',
                'url': reverse('add_slide'),
                'icon': 'upload',
                'description': 'Add new media, announcements, and custom content slides.',
            },
            {
                'key': 'manage_slides',
                'label': 'Slide Library',
                'url': reverse('manage_slides'),
                'icon': 'slides',
                'description': 'Tune playback, transitions, generated slides, and slide order.',
            },
        ])
        if is_superuser:
            items.append(
                {
                    'key': 'settings',
                    'label': 'Settings',
                    'url': reverse('settings'),
                    'icon': 'gear',
                    'description': 'Manage branding, accounts, screen schedules, and passwords.',
                }
            )
        items.extend([
            {
                'key': 'start_display',
                'label': 'Start Display',
                'url': reverse('slidedisplay'),
                'icon': 'play',
                'description': 'Launch the live signage slideshow presentation.',
            },
            {
                'key': 'logout',
                'label': 'Log Out',
                'url': reverse('logout'),
                'icon': 'logout',
                'description': 'Sign out of the control panel on this device.',
            },
        ])
    else:
        items.extend([
            {
                'key': 'login',
                'label': 'Log In',
                'url': reverse('login'),
                'icon': 'login',
                'description': 'Sign in to the control panel and editing tools.',
            },
            {
                'key': 'start_display',
                'label': 'Start Display',
                'url': reverse('slidedisplay'),
                'icon': 'play',
                'description': 'Open the live signage slideshow presentation.',
            },
        ])

    return items
