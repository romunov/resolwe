# -*- coding: utf-8 -*-
# Generated by Django 1.11.7 on 2017-12-04 16:07
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("flow", "0010_add_secret"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datadependency",
            name="parent",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="children_dependency",
                to="flow.Data",
            ),
        ),
    ]
