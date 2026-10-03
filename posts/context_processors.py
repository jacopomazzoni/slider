from .models import SiteAppearanceSettings


def site_appearance(request):
    return {
        "site_appearance": SiteAppearanceSettings.load(),
    }
