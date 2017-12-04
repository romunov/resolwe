# -*- coding: utf-8 -*-
# Generated by Django 1.11.7 on 2017-12-11 07:20
from __future__ import unicode_literals

from django.db import migrations

from resolwe.flow.utils import iterate_fields


def recreate_parent_dependencies(apps, schema_editor):
    """Create empty dependency relation if parent has been deleted."""
    Data = apps.get_model('flow', 'Data')
    DataDependency = apps.get_model('flow', 'DataDependency')

    def process_dependency(data, parent):
        if not Data.objects.filter(pk=parent).exists():
            DataDependency.objects.create(
                child=data, parent=None, kind='io'
            )

    for data in Data.objects.all():
        for field_schema, fields in iterate_fields(data.input, data.process.input_schema):
            name = field_schema['name']
            value = fields[name]

            if field_schema.get('type', '').startswith('data:'):
                process_dependency(data, value)

            elif field_schema.get('type', '').startswith('list:data:'):
                for parent in value:
                    process_dependency(data, parent)


class Migration(migrations.Migration):

    dependencies = [
        ('flow', '0011_preserve_parents'),
    ]

    operations = [
        migrations.RunPython(recreate_parent_dependencies)
    ]
