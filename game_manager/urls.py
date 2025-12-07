from django.urls import path
from .views import MapDataView, TaskResultView, DashboardView, CommandView

urlpatterns = [
    path('map/<int:map_id>/', MapDataView.as_view(), name='map_data'),
    path('result/', TaskResultView.as_view(), name='task_result'),
    path('command/', CommandView.as_view(), name='command'),
]
