# Generated by Django 5.0.12 on 2025-07-02 16:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quiz_app', '0012_retrysession'),
    ]

    operations = [
        migrations.AlterField(
            model_name='quiz',
            name='sheet_url',
            field=models.URLField(unique=True),
        ),
    ]
