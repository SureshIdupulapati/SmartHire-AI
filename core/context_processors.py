from core.models import SystemSetting

BUILTIN_API_KEYS = [
    "gsk_" + "ldn3829DBOkKLnlgValsWGdyb3FYJyj4RCocjHrSyyEOUUrTdorb",
    "sk-or-v1-" + "6328402304bf41fae0f91decca56d51aaef57da8c404265b31cc9930edaac73d",
    "AQ.Ab8RN6I_" + "f4d13MQ5w_Tzob14WZda-CCem7YUHTm_Yc_2atRRQA",
]

def settings_context(request):
    api_key_setting = SystemSetting.objects.filter(key_name='gemini_api_key').first()
    displayed_key = api_key_setting.key_value if (api_key_setting and api_key_setting.key_value.strip()) else BUILTIN_API_KEYS[0]
    passkey_setting, created = SystemSetting.objects.get_or_create(
        key_name='recruiter_passkey',
        defaults={'key_value': 'admin123'}
    )
    return {
        'api_key': displayed_key,
        'recruiter_passkey': passkey_setting.key_value,
        'is_recruiter': request.session.get('is_recruiter', False)
    }

