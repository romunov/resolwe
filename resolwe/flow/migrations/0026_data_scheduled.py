# -*- coding: utf-8 -*-
# Generated by Django 1.11.14 on 2019-02-07 02:58
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("flow", "0025_entity_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="data",
            name="scheduled",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
