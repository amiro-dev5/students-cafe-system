from django.db import models
from django.contrib.auth.models import User
import uuid
import random
import string
from decimal import Decimal
from django.contrib.auth.hashers import make_password, check_password


class StudentProfile(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    full_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=15)
    dorm_block = models.CharField(max_length=50, blank=True, null=True) 
    email = models.EmailField(max_length=255, null=True, blank=True, help_text="የተጠቃሚው Gmail አድራሻ")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.full_name} ({self.telegram_id})"


class Cafe(models.Model):
    name = models.CharField(max_length=100)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='my_cafes')
    location = models.CharField(max_length=255, blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True)
    is_open = models.BooleanField(default=True, help_text="ካፌው ለጊዜው ዝግ ከሆነ False ይደረጋል")
    is_deleted = models.BooleanField(default=False, help_text="ካፌው ከተሰረዘ True ይሆናል (Recycle Bin)")
    deleted_at = models.DateTimeField(null=True, blank=True, help_text="የተሰረዘበት ሰዓት")
    employee_password = models.CharField(max_length=128, help_text="የሰራተኛው ፓስዎርድ (Hashed)")
    employee_telegram_id = models.BigIntegerField(null=True, blank=True, help_text="የተፈቀደለት ሰራተኛ የቴሌግራም ID")
    employee_failed_attempts = models.IntegerField(default=0, help_text="ሰራተኛው የተሳሳተ ሙከራ ሲያደርግ ይቆጥራል")
    is_employee_locked = models.BooleanField(default=False, help_text="ሰራተኛው 3 ጊዜ ከተሳሳተ True ይሆናል")
   
    is_employee_locked = models.BooleanField(default=False, help_text="ሰራተኛው 3 ጊዜ ከተሳሳተ ይታገዳል")
    employee_failed_attempts = models.IntegerField(default=0, help_text="የተሳሳቱ ሙከራዎች ብዛት")

    def __str__(self):
        return self.name


class MenuItem(models.Model):
    cafe = models.ForeignKey(Cafe, on_delete=models.CASCADE, related_name='menu_items')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='menu_images/', blank=True, null=True)
    is_available = models.BooleanField(default=True)
    stock_quantity = models.IntegerField(default=0, help_text="ባለቤቱ የሚሞላው የምግብ መጠን")
    current_stock = models.IntegerField(default=0, help_text="የቀረው የምግብ መጠን")
    is_waiting_mode = models.BooleanField(default=False, help_text="ምግብ አልቆ ሰው እየጠበቀ ከሆነ")

    def __str__(self):
        return f"{self.name} - {self.cafe.name}"


class Order(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'ሳይከፈል ያለ'),
        ('PAID', 'የተከፈለ/ያልተረከበ'),
        ('COMPLETED', 'የተረከበ/የተጠናቀቀ'),
        ('CANCELLED', 'ተሰርዟል'),
    ]
    
    student = models.ForeignKey(StudentProfile, on_delete=models.SET_NULL, null=True, related_name='orders')
    items = models.ManyToManyField(MenuItem)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    pickup_code = models.CharField(max_length=10, unique=True, blank=True, null=True)
    tx_ref = models.CharField(max_length=100, unique=True, blank=True, null=True)
    
    admin_commission = models.DecimalField(max_digits=10, decimal_places=2, default=3.00)
    vendor_share = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    items_json = models.TextField(default="{}", help_text="የታዘዙ ምግቦች ዝርዝር በJSON")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    is_paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_by_id = models.BigIntegerField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.pickup_code:
            self.pickup_code = str(uuid.uuid4().hex[:6]).upper()
        
        if self.total_price:
            self.admin_commission = Decimal('3.00')
            self.vendor_share = self.total_price - self.admin_commission
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order #{self.id} - {self.pickup_code}"
class Waitlist(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE)
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)


class CafeOwner(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cafe_owner_profile')
    cafe = models.ForeignKey(Cafe, on_delete=models.CASCADE, related_name='owners')
    telegram_id = models.BigIntegerField(unique=True, help_text="ባለቤቱ ቦቱን ሲጀምር የሚለይበት ID")
    
    
    access_password = models.CharField(max_length=128, help_text="የባለቤቱ ፓስዎርድ (Hashed)")
    is_locked = models.BooleanField(default=False, help_text="3 ጊዜ ከተሳሳተ ይታገዳል")
    failed_attempts = models.IntegerField(default=0)
    email = models.EmailField(max_length=255, null=True, blank=True, help_text="የባለቤቱ Gmail አድራሻ")
    otp_code = models.CharField(max_length=6, blank=True, null=True) 
    last_otp_time = models.DateTimeField(blank=True, null=True)     
    reset_count_today = models.IntegerField(default=0)            
    
    is_authorized = models.BooleanField(default=False, help_text="ዴቨሎፐሩ ፈቃድ ካልሰጠው መስራት አይችልም")
    owner_secret_key = models.CharField(max_length=50, blank=True, null=True, help_text="ባለቤቱ ራሱ የሚቀይረው መለያ")

    def __str__(self):
        return f"{self.user.username} - {self.cafe.name}"

    class Meta:
        verbose_name = "የካፌ ባለቤት"
        verbose_name_plural = "የካፌ ባለቤቶች"