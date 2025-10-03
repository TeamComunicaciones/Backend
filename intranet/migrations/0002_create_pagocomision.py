from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('intranet', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PagoComision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('idpos', models.CharField(max_length=100, db_index=True)),
                ('punto_de_venta', models.CharField(max_length=200, null=True, blank=True)),
                ('fecha_pago', models.DateTimeField(auto_now_add=True)),
                ('monto_total_pagado', models.DecimalField(max_digits=12, decimal_places=2)),
                ('monto_comisiones', models.DecimalField(max_digits=12, decimal_places=2)),
                ('metodos_pago', models.JSONField()),
                ('creado_por', models.ForeignKey(
                    on_delete=django.db.models.deletion.SET_NULL,
                    null=True,
                    related_name='pagos_realizados',
                    to=settings.AUTH_USER_MODEL
                )),
            ],
        ),
    ]
