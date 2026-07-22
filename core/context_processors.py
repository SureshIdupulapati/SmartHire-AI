from core.models import SystemSetting

def settings_context(request):
    api_key_setting = SystemSetting.objects.filter(key_name='gemini_api_key').first()
    passkey_setting, created = SystemSetting.objects.get_or_create(
        key_name='recruiter_passkey',
        defaults={'key_value': 'admin123'}
    )
    return {
        'api_key': api_key_setting.key_value if api_key_setting else '',
        'recruiter_passkey': passkey_setting.key_value,
        'is_recruiter': request.session.get('is_recruiter', False)
    }
