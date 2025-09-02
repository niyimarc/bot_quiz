from django.apps import AppConfig


class AuthCoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'auth_core'

    def ready(self):
        import auth_core.signals
