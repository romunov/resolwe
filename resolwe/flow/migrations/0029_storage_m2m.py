# -*- coding: utf-8 -*-
# Generated by Django 1.11.16 on 2019-02-26 04:08
from __future__ import unicode_literals

from django.db import migrations, models


def set_data_relation(apps, schema_editor):
    Storage = apps.get_model("flow", "Storage")

    for storage in Storage.objects.iterator():
        storage.data.add(storage.data_migration_temporary)


class Migration(migrations.Migration):

    dependencies = [
        ("flow", "0028_add_data_location"),
    ]

    operations = [
        migrations.RenameField(
            model_name="storage", old_name="data", new_name="data_migration_temporary",
        ),
        migrations.AddField(
            model_name="storage",
            name="data",
            field=models.ManyToManyField(related_name="storages", to="flow.Data"),
        ),
        migrations.RunPython(set_data_relation),
        migrations.RemoveField(model_name="storage", name="data_migration_temporary",),
    ]
