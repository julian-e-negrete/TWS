# dashboard/urls.py
from django.urls import path
from .views import candlestick_chart

urlpatterns = [
    path('charts', candlestick_chart, name='candle'),
]
