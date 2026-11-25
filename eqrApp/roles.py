from .models import EmployeeProfile


def get_user_role(user):
    """Return the WorkTrack role for an authenticated Django user.

    Superusers are always administrators. Existing staff users without an
    EmployeeProfile are treated as HR personnel for backward compatibility.
    """
    if not getattr(user, 'is_authenticated', False):
        return None
    if user.is_superuser:
        return 'admin'
    try:
        return user.employee_profile.role
    except EmployeeProfile.DoesNotExist:
        return 'hr' if user.is_staff else 'employee'


def role_label(role):
    return {
        'employee': 'Employee',
        'supervisor': 'Supervisor',
        'hr': 'HR Personnel',
        'admin': 'Administrator',
    }.get(role, 'User')
