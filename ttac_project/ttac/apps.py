from django.apps import AppConfig

class TtacConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ttac"

    def ready(self):
        import ttac.signals
