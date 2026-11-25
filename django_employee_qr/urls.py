from django.urls import path, include
from django.views.generic.base import RedirectView

urlpatterns = [
    path('accounts/', include('eqrApp.urls')),
    path('', RedirectView.as_view(pattern_name='eqrApp:login', permanent=False)),
]
