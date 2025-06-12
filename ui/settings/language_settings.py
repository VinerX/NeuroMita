def create_language_section(self, settings_frame):

    config = [
        {'label': 'Язык / Language', 'key': 'LANGUAGE', 'type': 'combobox',
         'options': ["RU", "EN"], 'default': "RU"},
        {'label': 'Перезапусти программу после смены! / Restart program after change!', 'type': 'text'},

    ]

    self.create_settings_section(settings_frame, "Язык / Language", config)

