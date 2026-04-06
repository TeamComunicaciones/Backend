from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('intranet', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    # PagoComision ya fue creada en 0001_initial.
    # Esta migración queda vacía para no romper el historial de dependencias.
    operations = []
