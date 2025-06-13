from utils import _
def setup_api_controls(self, parent):
    # Основные настройки
    common_config = [
        {'label': _('Ссылка', 'URL'), 'key': 'NM_API_URL', 'type': 'entry'},
        {'label': _('Модель', 'Model'), 'key': 'NM_API_MODEL', 'type': 'entry'},
        {'label': _('Ключ', 'Key'), 'key': 'NM_API_KEY', 'type': 'entry', 'default': ""},
        {'label': _('Резервные ключи', 'Reserve keys'), 'key': 'NM_API_KEY_RES', 'type': 'text',
         'hide': bool(self.settings.get("HIDE_PRIVATE")), 'default': ""},
        {'label': _('Через Request', 'Using Request'), 'key': 'NM_API_REQ', 'type': 'checkbutton'},
        {'label': _('Гемини для ProxiAPI', 'Gemini for ProxiAPI'), 'key': 'GEMINI_CASE', 'type': 'checkbutton',
         'default_checkbutton': False}
    ]
    self.create_settings_section(parent,
                                 _("Настройки API", "API settings"),
                                 common_config)