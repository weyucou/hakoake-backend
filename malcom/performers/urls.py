from django.urls import path

from . import views

app_name = "performers"

urlpatterns = [
    path("performers/verify/", views.verify_social_link_view, name="verify_social_link"),
    path("performers/verify/action/", views.verify_social_link_action, name="verify_social_link_action"),
]
