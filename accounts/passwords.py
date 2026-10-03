from django.core.exceptions import ValidationError


PASSWORD_MAX_LENGTH = 20


def password_widget_attrs(*, autocomplete='new-password'):
    return {
        'autocomplete': autocomplete,
        'maxlength': PASSWORD_MAX_LENGTH,
    }


def validate_basic_password(value):
    if value is None:
        return value

    if len(value) > PASSWORD_MAX_LENGTH:
        raise ValidationError(f'Password must be {PASSWORD_MAX_LENGTH} characters or fewer.')

    for character in value:
        codepoint = ord(character)
        if codepoint < 32 or codepoint == 127:
            raise ValidationError('Password cannot contain control characters.')

    return value
