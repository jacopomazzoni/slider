def is_site_admin(user):
    """Site administration is reserved for active, authenticated superusers."""
    return all(getattr(user, field, False) for field in ('is_authenticated', 'is_active', 'is_superuser'))
