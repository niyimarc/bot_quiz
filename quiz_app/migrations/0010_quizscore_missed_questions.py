# Generated by Django 5.0.12 on 2025-07-01 11:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quiz_app', '0009_quizaccess'),
    ]

    operations = [
        migrations.AddField(
            model_name='quizscore',
            name='missed_questions',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
