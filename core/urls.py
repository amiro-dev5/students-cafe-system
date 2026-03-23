from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from cafes.views import chapa_webhook # ይህ ተጨምሯል

urlpatterns = [
    path('admin/', admin.site.urls),
    path('chapa-webhook/', chapa_webhook, name='chapa_webhook'), # የቻፓ በር
]

# ይህ መስመር የግድ ነው - ፎቶው እንዲታይ የሚያደርገው እሱ ነው
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)