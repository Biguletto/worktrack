from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('eqrApp', '0028_add_integrity_constraints'),
    ]

    operations = [
        migrations.AlterField(
            model_name='employeeprofile',
            name='department',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
