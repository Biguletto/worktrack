from .roles import get_user_role, role_label


def worktrack_access(request):
    role = get_user_role(request.user) if request.user.is_authenticated else None
    return {
        'current_role': role,
        'current_role_label': role_label(role),
    }
