from django.contrib import admin
from .models import Cafe, MenuItem, Order, StudentProfile, CafeOwner # CafeOwner ተጨምሯል


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone_number', 'telegram_id', 'created_at')
    search_fields = ('full_name', 'phone_number', 'telegram_id')
    list_filter = ('created_at',)
    ordering = ('-created_at',)


@admin.register(CafeOwner)
class CafeOwnerAdmin(admin.ModelAdmin):
    list_display = ('user', 'cafe', 'telegram_id', 'is_authorized', 'is_locked', 'failed_attempts')
    list_filter = ('is_authorized', 'is_locked', 'cafe')
    search_fields = ('user__username', 'telegram_id')
    
  
    def has_module_permission(self, request):
        return request.user.is_superuser


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'cafe', 'is_available')
    list_filter = ('cafe', 'is_available')
    search_fields = ('name',)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(cafe__owner=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "cafe" and not request.user.is_superuser:
            kwargs["queryset"] = Cafe.objects.filter(owner=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Cafe)
class CafeAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'is_active', 'balance')
    list_filter = ('is_active',)
    search_fields = ('name',)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(owner=request.user)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'get_student_name', 'pickup_code', 'total_price', 'status', 'is_paid', 'created_at')
    list_filter = ('status', 'is_paid', 'created_at')
    search_fields = ('student__full_name', 'id', 'pickup_code')
    
    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else "ያልታወቀ ተማሪ"
    get_student_name.short_description = 'የተማሪ ስም'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(items__cafe__owner=request.user).distinct()