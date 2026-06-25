from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def root_view(request):
    return JsonResponse({
        'service': 'FinFlow API',
        'version': '1.0',
        'endpoints': [
            'POST /api/transaction',
            'GET  /api/summary/<userId>',
            'GET  /api/ranking',
        ]
    })


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('transactions.urls')),
    path('', root_view),
]
