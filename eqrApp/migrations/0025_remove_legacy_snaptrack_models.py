from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('eqrApp', '0024_employeeprofile_role')]

    operations = [
        migrations.DeleteModel(name='Attendance'),
        migrations.DeleteModel(name='QRCode'),
        migrations.DeleteModel(name='Event'),
        migrations.DeleteModel(name='Member'),
    ]
