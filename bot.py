import os
import django
import telebot
import uuid
import json
import random
import requests
import pytz
import re 
import smtplib
from decimal import Decimal
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from django.db.models import Sum, Count
from telebot import types
from dotenv import load_dotenv
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone

load_dotenv()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from cafes.models import MenuItem, Cafe, StudentProfile, Order, CafeOwner, Waitlist

API_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAPA_SECRET_KEY = os.getenv('CHAPA_SECRET_KEY')
CHAPA_URL = "https://api.chapa.co/v1/transaction/initialize"
DEVELOPER_CHAT_ID = int(os.getenv('DEVELOPER_CHAT_ID'))

bot = telebot.TeleBot(API_TOKEN)
user_carts = {}
ethiopia_tz = pytz.timezone('Africa/Addis_Ababa')
image_cache = {}

# ኢሜል ለመላክ የሚያገለግል ፈንክሽን
def send_otp_email(receiver_email, otp_code, user_name):
    sender_email = os.getenv('EMAIL_ADDRESS')
    sender_password = os.getenv('EMAIL_PASSWORD')
    
    try:
        # 1. የተሻሻለ ርዕስ (Subject)
        subject = f"ሰላም {user_name}፣ የማረጋገጫ ኮድዎ - {otp_code}"
        
        # 2. HTML ይዘት (ይሄ Inbox የመግባት እድሉን ይጨምራል)
        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                <h2 style="color: #2c3e50;">የካፌ ባለቤት ማረጋገጫ</h2>
                <p>ሰላም <b>{user_name}</b>፣</p>
                <p>የካፌ ማስተዳደሪያ ቦት ፓስዎርድዎን ለመቀየር የጠየቁት የማረጋገጫ ኮድ ከታች ያለው ነው፦</p>
                <div style="background-color: #f1f1f1; padding: 20px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 5px;">
                    {otp_code}
                </div>
                <p>ይህ ኮድ ለ 5 ደቂቃ ብቻ ያገለግላል። እባክዎ ለማንም አያጋሩ።</p>
                <hr>
                <small>ይህ መልእክት በራስ-ሰር የተላከ ስለሆነ መልስ አይስጡ።</small>
            </body>
        </html>
        """
        
        msg = MIMEMultipart()
        msg['From'] = f"Cafe Management System <{sender_email}>" # ስም ጨምረናል
        msg['To'] = receiver_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html')) # HTML መሆኑን ገልጸናል
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"ኢሜል ስህተት፦ {e}")
        return False

def is_registered(user_id):
    return StudentProfile.objects.filter(telegram_id=user_id).exists()

def is_cafe_owner(user_id):
    if user_id == DEVELOPER_CHAT_ID:
        return True
    return CafeOwner.objects.filter(telegram_id=user_id).exists()
def is_authorized_employee(user_id):
    return Cafe.objects.filter(employee_telegram_id=user_id).exists()

def initialize_chapa_payment(order, student, total_amount, cart_summary):
    headers = {'Authorization': f'Bearer {CHAPA_SECRET_KEY}', 'Content-Type': 'application/json'}
    
    
    tx_ref = str(order.id) 
    
    payload = {
        "amount": str(total_amount), 
        "currency": "ETB", 
        "email": student.email if student.email else "student@smartcampus.com",
        "first_name": "Student", 
        "tx_ref": tx_ref,
        "callback_url": "https://linelike-ling-proemployee.ngrok-free.dev/chapa-webhook/", 
        "return_url": "https://t.me/order6_bot", 
        "customization": {
           
            "title": "SmartCampus", 
            "description": f"Order No {order.id}" 
        }
    }
    
    try:
        response = requests.post(CHAPA_URL, json=payload, headers=headers)
        res_data = response.json()
        if res_data.get('status') == 'success':
            return res_data['data']['checkout_url']
        
        print(f"❌ Chapa API Error: {res_data}")
        return None
    except Exception as e:
        print(f"❌ Chapa Connection Error: {e}")
        return None

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    if is_registered(user_id):
        buttons = ['🍴 ሜኑ እይ', '🛍 ትዕዛዞቼ', '🔄 Refresh']
        if user_id == DEVELOPER_CHAT_ID:
            buttons.append('🚀 የ Dev Amiro መግቢያ')
        if is_authorized_employee(user_id):
            buttons.append('👨‍🍳 የሰራተኛ መግቢያ')
        try:
            
            owner = CafeOwner.objects.get(telegram_id=user_id)
            
            
            if user_id != DEVELOPER_CHAT_ID and owner.is_authorized and not owner.cafe.is_deleted:
                buttons.append('🔐 የካፌ ባለቤት መግቢያ')
        except CafeOwner.DoesNotExist:
            
            pass
        markup.add(*buttons)
        bot.send_message(message.chat.id, "🌟 **እንኳን በደህና ተመለሱ!**", reply_markup=markup, parse_mode="Markdown")
    else:
        msg = bot.send_message(message.chat.id, "ሰላም! መጀመሪያ ይመዝገቡ።\n**ሙሉ ስምዎን ያስገቡ፦**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_name_step)


@bot.message_handler(func=lambda message: message.text == '🔄 Refresh')
def refresh_button_handler(message):
    send_welcome(message)        

def process_name_step(message):
    full_name = message.text
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(types.KeyboardButton(text="📲 ስልክ ቁጥሬን ላክ", request_contact=True))
    markup.add("🔄 Refresh")
    msg = bot.send_message(message.chat.id, f"አመሰግናለሁ {full_name}! ስልክዎን ይላኩ።", reply_markup=markup)
    bot.register_next_step_handler(msg, process_phone_step, full_name)

def process_phone_step(message, full_name):
    user_id = message.from_user.id
    phone = message.contact.phone_number if message.contact else message.text
    phone = phone.replace("+251", "0").replace(" ", "").strip()
    
    
    if re.match(r"^(09|07)\d{8}$", phone):
        
        msg = bot.send_message(
            message.chat.id, 
            "✅ ስልክዎ ተረጋግጧል!\n\n📧 አሁን ደግሞ የ **Gmail** አድራሻዎን ያስገቡ (ለምሳሌ: user@gmail.com)፦",
            reply_markup=types.ReplyKeyboardRemove() 
        )
        
        bot.register_next_step_handler(msg, process_email_step, full_name, phone)
    else:
        error_msg = "⚠️ **የተሳሳተ ስልክ ቁጥር!**\n\nእባክዎ በ 09 ወይም 07 የሚጀምር 10 አሃዝ ቁጥር ያስገቡ (ለምሳሌ፦ 0912345678)"
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add(types.KeyboardButton(text="📲 ስልክ ቁጥሬን ላክ", request_contact=True))
        
        msg = bot.send_message(message.chat.id, error_msg, reply_markup=markup, parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_phone_step, full_name)
  
def process_email_step(message, full_name, phone):
    email = message.text.strip().lower()
    user_id = message.from_user.id
    
    
    gmail_pattern = r"^[a-z0-9.]{3,}@gmail\.com$"
    
    if not re.match(gmail_pattern, email):
        msg = bot.send_message(message.chat.id, "❌ ስህተት! እባክዎ ትክክለኛ የ **Gmail** አድራሻ ያስገቡ (ለምሳሌ: example@gmail.com)፦")
        bot.register_next_step_handler(msg, process_email_step, full_name, phone)
        return

    
    StudentProfile.objects.create(
        telegram_id=user_id,
        full_name=full_name,
        phone_number=phone,
        email=email
    )
    
    bot.send_message(message.chat.id, f"🎊 እንኳን ደስ አለዎት {full_name}! ምዝገባው በሚገባ ተጠናቋል።")
    send_welcome(message)

@bot.message_handler(func=lambda message: message.text == '🔐 የካፌ ባለቤት መግቢያ')
def owner_login_start(message):
    user_id = message.from_user.id
    if not is_cafe_owner(user_id): return
    
    
    if user_id == DEVELOPER_CHAT_ID:
        owner = CafeOwner.objects.first()
        if owner:
            show_owner_dashboard(message, owner)
        else:
            bot.send_message(message.chat.id, "🛠 ሰላም አድሚን! በመጀመሪያ ዳታቤዝ ውስጥ ካፌ መመዝገብ አለበት።")
        return

    
    try:
        owner = CafeOwner.objects.get(telegram_id=user_id)
        if owner.is_locked:
            bot.send_message(message.chat.id, "🔒 **አካውንትዎ ታግዷል።**")
            return
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🤷‍♂️ ፓስዎርድ ረሳሁ", callback_data="owner_forgot_pw"))

        msg = bot.send_message(message.chat.id, "🔑 **ሚስጥራዊ ቃልዎን ያስገቡ፦**", reply_markup=markup)
        bot.register_next_step_handler(msg, check_owner_password, owner)
    except CafeOwner.DoesNotExist:
        bot.send_message(message.chat.id, "❌ እርስዎ የካፌ ባለቤት አይደሉም።")


@bot.message_handler(func=lambda message: message.text == '👨‍🍳 የሰራተኛ መግቢያ')
def employee_login_start(message):
    user_id = message.from_user.id
    try:
        cafe = Cafe.objects.get(employee_telegram_id=user_id)
        
        
        if cafe.is_employee_locked:
            bot.send_message(message.chat.id, "🔒 **የሰራተኛ አካውንትዎ ታግዷል!**\nእባክዎ የካፌውን ባለቤት ያነጋግሩ።")
            return

        msg = bot.send_message(message.chat.id, "🔑 **የሰራተኛ መግቢያ ፓስዎርድ ያስገቡ፦**")
        
        bot.register_next_step_handler(msg, lambda m: process_employee_auth(m, cafe))
    except Cafe.DoesNotExist:
        bot.send_message(message.chat.id, "❌ እርስዎ የተመዘገቡ ሰራተኛ አይደሉም።")


def process_employee_auth(message, cafe):
    
    if not message.text or message.text.startswith('/'):
        msg = bot.send_message(message.chat.id, "⚠️ እባክዎ መጀመሪያ ፓስዎርድ ያስገቡ፦")
        bot.register_next_step_handler(msg, lambda m: process_employee_auth(m, cafe))
        return

    entered_pw = message.text.strip()
    
    
    if entered_pw == cafe.employee_password:
        cafe.employee_failed_attempts = 0
        cafe.is_employee_locked = False
        cafe.save()
        
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🔍 ኮድ አረጋግጥ", "🔙 ወደ ዋና ሜኑ")
        
        bot.send_message(message.chat.id, f"✅ እንኳን ደህና መጡ! የ{cafe.name} ሰራተኛ መሆንዎ ተረጋግጧል።", reply_markup=markup)
    else:
       
        cafe.employee_failed_attempts += 1
        remaining = 3 - cafe.employee_failed_attempts
        
        if cafe.employee_failed_attempts >= 3:
            cafe.is_employee_locked = True
            cafe.save()
            bot.send_message(message.chat.id, "🔒 **ፓስዎርድ 3 ጊዜ ተሳስተዋል። አካውንትዎ ተቆልፏል!**\nባለቤቱን ያነጋግሩ።")
        else:
            cafe.save()
            msg = bot.send_message(message.chat.id, f"❌ የተሳሳተ ኮድ! {remaining} ሙከራ ቀርቶታል።\nእንደገና ይሞክሩ፦")
            bot.register_next_step_handler(msg, lambda m: process_employee_auth(m, cafe))


@bot.callback_query_handler(func=lambda call: call.data == "owner_forgot_pw")
def handle_owner_forgot_password(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    try:
        owner = CafeOwner.objects.get(telegram_id=user_id)
        
       
        if owner.is_locked:
            bot.answer_callback_query(call.id, "🚫 አካውንትዎ ታግዷል።", show_alert=True)
            return

        bot.clear_step_handler_by_chat_id(chat_id=chat_id)    

    
        bot.answer_callback_query(call.id, "📨 ኮድ እየተላከ ነው...")
        start_password_reset(call.message, owner)
        
    except CafeOwner.DoesNotExist:
        bot.answer_callback_query(call.id, "❌ አካውንት አልተገኘም።", show_alert=True)        
@bot.message_handler(func=lambda message: message.text == '🚀 የ Dev Amiro መግቢያ')
def dev_amiro_dashboard(message):
    if message.from_user.id != DEVELOPER_CHAT_ID:
        return

    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    
    btn_cafes = "🏘 ካፌዎችን አስተዳድር"
    btn_unlock = "🔓 የታገዱ ባለቤቶች"
    btn_users = "👥 ተጠቃሚዎችን እይ"
    btn_stats = "📈 አጠቃላይ ሪፖርት"
    btn_back = "🔙 ወደ ዋና ሜኑ"
    
    markup.add(btn_cafes, btn_unlock)
    markup.add(btn_users, btn_stats)
    markup.add(btn_back)
    
    bot.send_message(message.chat.id, "🛠 **የ Dev Amiro መቆጣጠሪያ ማዕከል**\n\nጌታዬ፣ የትኛውን ክፍል ማስተካከል ይፈልጋሉ?", reply_markup=markup, parse_mode="Markdown")
    
@bot.message_handler(func=lambda message: message.text == '🏘 ካፌዎችን አስተዳድር')
def dev_manage_cafes(message):
    if message.from_user.id != DEVELOPER_CHAT_ID: return
    
    cafes = Cafe.objects.filter(is_deleted=False)
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for cafe in cafes:
       
        markup.add(types.InlineKeyboardButton(text=f"🏢 {cafe.name.upper()}", callback_data=f"dev_view_cafe_{cafe.id}"))
    
    
    markup.add(types.InlineKeyboardButton(text="➕ አዲስ ካፌ ጨምር", callback_data="dev_add_new_cafe"))
    markup.add(types.InlineKeyboardButton("♻️ ሪሳይክል ቢን (Recycle Bin)", callback_data="dev_recycle_bin"))
    
    bot.send_message(message.chat.id, "🏘 **የካፌዎች ዝርዝር**\n\nለማስተዳደር አንዱን ይጫኑ ወይም አዲስ ይጨምሩ፦", reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data == "dev_add_new_cafe")
def dev_start_add_cafe(call):
    msg = bot.send_message(call.message.chat.id, "📝 **የካፌውን ስም ያስገቡ፦**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, dev_process_cafe_name)

def dev_process_cafe_name(message):
    cafe_name = message.text
    msg = bot.send_message(message.chat.id, f"👤 **ለ{cafe_name} የባለቤት ስም ያስገቡ፦**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, dev_process_owner_name, cafe_name)

def dev_process_owner_name(message, cafe_name):
    owner_name = message.text
    msg = bot.send_message(message.chat.id, f"🆔 **ለ{owner_name} የቴሌግራም ID ያስገቡ፦**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, dev_process_telegram_id, cafe_name, owner_name)

def dev_process_telegram_id(message, cafe_name, owner_name):
    try:
        tg_id = int(message.text.strip())
        msg = bot.send_message(message.chat.id, f"🔑 **ለ{owner_name} መግቢያ ፓስዎርድ ይፍጠሩ፦**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, dev_finalize_cafe, cafe_name, owner_name, tg_id)
    except ValueError:
        msg = bot.send_message(message.chat.id, "❌ ስህተት! ID ቁጥር መሆን አለበት። እንደገና ያስገቡ፦")
        bot.register_next_step_handler(msg, dev_process_telegram_id, cafe_name, owner_name)

def dev_finalize_cafe(message, cafe_name, owner_name, tg_id):
    password = message.text
    try:
        from django.db import transaction
        from django.contrib.auth.models import User
        import random
        
        with transaction.atomic():
           
            owner_email = None
            try:
               
                student_data = StudentProfile.objects.get(telegram_id=tg_id)
                owner_email = student_data.email
            except StudentProfile.DoesNotExist:
                owner_email = None 
          
            username = owner_name.replace(" ", "_").lower() + str(random.randint(10, 99))
            new_user = User.objects.create_user(username=username, password=password)

            new_cafe = Cafe.objects.create(
                name=cafe_name, 
                owner=new_user, 
                employee_password="1234",
                is_open=True
            )
          
            CafeOwner.objects.create(
                user=new_user,
                cafe=new_cafe,
                telegram_id=tg_id,
                access_password=make_password(password),
                email=owner_email,
                is_authorized=True 
            )
        
        email_status = f"📧 ኢሜል፦ {owner_email}" if owner_email else "⚠️ ኢሜል፦ አልተገኘም (በኋላ በእጅ መሞላት አለበት)"
        
        bot.send_message(message.chat.id, 
            f"✅ **ካፌው በተሳካ ሁኔታ ተመዝግቧል!**\n\n"
            f"🏘 ካፌ፦ {cafe_name}\n"
            f"👤 ባለቤት፦ {owner_name}\n"
            f"🆔 Telegram ID፦ `{tg_id}`\n"
            f"🔑 Password፦ `{password}`\n"
            f"{email_status}\n\n"
            f"አሁን ባለቤቱ በቴሌግራም IDው ገብቶ ማስተዳደር ይችላል።", 
            parse_mode="Markdown")
            
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ ስህተት፦ {str(e)}")
       
@bot.message_handler(func=lambda message: message.text == '🔓 የታገዱ ባለቤቶች')
def dev_list_locked_owners(message):
    if message.from_user.id != DEVELOPER_CHAT_ID: return
    
    
    locked_owners = CafeOwner.objects.filter(is_locked=True)
    
    if not locked_owners.exists():
        bot.send_message(message.chat.id, "✅ በአሁኑ ሰዓት የታገደ የካፌ ባለቤት የለም።")
        return
    
    markup = types.InlineKeyboardMarkup()
    for owner in locked_owners:
        
        markup.add(types.InlineKeyboardButton(
            text=f"🔓 {owner.cafe.name} ({owner.user.username}) - ፍታ", 
            callback_data=f"dev_unlock_{owner.id}"
        ))
    
    bot.send_message(message.chat.id, "🔐 **የታገዱ ባለቤቶች ዝርዝር**\n\nለመፍታት ስሙን ይጫኑ፦", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('dev_unlock_'))
def dev_unlock_owner_action(call):
    owner_id = call.data.split('_')[-1]
    try:
        owner = CafeOwner.objects.get(id=owner_id)
        owner.is_locked = False
        owner.failed_attempts = 0 
        owner.save()
        
        bot.answer_callback_query(call.id, f"✅ የ{owner.cafe.name} ባለቤት ተፈትቷል!")
        bot.edit_message_text(f"✅ የ{owner.cafe.name} ባለቤት ({owner.user.username}) አሁን መግባት ይችላል።", 
                              call.message.chat.id, call.message.message_id)
    except Exception as e:
        bot.answer_callback_query(call.id, f"ስህተት፦ {str(e)}")
        
@bot.message_handler(func=lambda message: message.text == '📈 አጠቃላይ ሪፖርት')
def dev_master_report(message):
    if message.from_user.id != DEVELOPER_CHAT_ID: return
    
    loading_msg = bot.send_message(message.chat.id, "📊 **ዳታውን በማሰባሰብ ላይ... ጥቂት ይጠብቁ**")
    
    try:
        from django.db.models import Sum
        from datetime import timedelta
        
        today = timezone.now().astimezone(ethiopia_tz).date()
        last_week = today - timedelta(days=7)
        
        daily_orders = Order.objects.filter(status='COMPLETED', created_at__date=today)
        total_daily_revenue = daily_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
        total_daily_commission = daily_orders.aggregate(Sum('admin_commission'))['admin_commission__sum'] or 0
        
        weekly_orders = Order.objects.filter(status='COMPLETED', created_at__date__gte=last_week)
        total_weekly_revenue = weekly_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
        total_weekly_commission = weekly_orders.aggregate(Sum('admin_commission'))['admin_commission__sum'] or 0
        
        new_users_today = StudentProfile.objects.filter(created_at__date=today).count()
        total_users = StudentProfile.objects.count()

        cafe_breakdown = ""
        cafes = Cafe.objects.filter(is_active=True)
        for cafe in cafes:
            c_orders = daily_orders.filter(items__cafe=cafe).distinct()
            c_rev = c_orders.aggregate(Sum('vendor_share'))['vendor_share__sum'] or 0
            c_comm = c_orders.aggregate(Sum('admin_commission'))['admin_commission__sum'] or 0
            if c_rev > 0 or c_comm > 0:
                cafe_breakdown += f"📍 **{cafe.name}**\n   └ 💰 ገቢ: `{c_rev} ETB` | 🎫 ኮሚሽን: `{c_comm} ETB`\n"

        report = (
            f"🚀 **ሲስተም ዳሽቦርድ (Dev Amiro)**\n"
            f"📅 ቀን፦ {today.strftime('%b %d, %Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 **ተጠቃሚዎች**\n"
            f"   ├ 🆕 ዛሬ የመጡ፦ `{new_users_today}`\n"
            f"   └ 📈 አጠቃላይ ተማሪ፦ `{total_users}`\n\n"
            f"💰 **የዛሬ የገንዘብ እንቅስቃሴ**\n"
            f"{cafe_breakdown if cafe_breakdown else '   ⚠️ ዛሬ ገና ሽያጭ አልተጀመረም።'}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 **ጠቅላላ የዛሬ ድምር**\n"
            f"   ├ 🏢 የካፌዎች ገቢ፦ `{total_daily_revenue - total_daily_commission} ETB`\n"
            f"   └ 👑 ያንተ ኮሚሽን፦ `{total_daily_commission} ETB`\n\n"
            f"📅 **የሳምንቱ አጠቃላይ (Last 7 Days)**\n"
            f"   ├ 🛍 ጠቅላላ ሽያጭ፦ `{total_weekly_revenue} ETB`\n"
            f"   └ 💎 ጠቅላላ ኮሚሽን፦ `{total_weekly_commission} ETB`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ *ሪፖርቱ በሰዓቱ የተመዘገቡ ዳታዎችን ብቻ ያሳያል።*"
        )

        bot.edit_message_text(report, message.chat.id, loading_msg.message_id, parse_mode="Markdown")
        
    except Exception as e:
        bot.edit_message_text(f"❌ ስህተት፦ {str(e)}", message.chat.id, loading_msg.message_id)
      
@bot.message_handler(func=lambda message: message.text == '👥 ተጠቃሚዎችን እይ')
def dev_manage_users(message):
    if message.from_user.id != DEVELOPER_CHAT_ID: return
    
    users = StudentProfile.objects.all().order_by('-created_at')[:15]
    total_count = StudentProfile.objects.count()
    
    msg = f"👥 **የተመዘገቡ ተማሪዎች (ጠቅላላ፦ {total_count})**\n\n"
    msg += "የመጨረሻዎቹ 15 ተማሪዎች ዝርዝር፦\n"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for user in users:
       
        user_info = f"👤 {user.full_name} | 📞 {user.phone_number}"
      
        markup.add(types.InlineKeyboardButton(text=user_info, callback_data=f"dev_user_ops_{user.id}"))
    
    markup.add(types.InlineKeyboardButton(text="🔍 ተማሪ በስም ፈልግ", callback_data="dev_search_user"))
    
    bot.send_message(message.chat.id, msg, reply_markup=markup, parse_mode="Markdown")
    
@bot.callback_query_handler(func=lambda call: call.data == "dev_search_user")
def dev_start_search_user(call):
    msg = bot.send_message(call.message.chat.id, "🔍 **ሊፈልጉት የፈለጉትን የተማሪ ስም ያስገቡ፦**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, dev_process_user_search)

def dev_process_user_search(message):
    search_query = message.text
    if not search_query:
        bot.send_message(message.chat.id, "❌ እባክዎ ትክክለኛ ስም ያስገቡ።")
        return

    results = StudentProfile.objects.filter(full_name__icontains=search_query)
    
    if not results.exists():
        bot.send_message(message.chat.id, f"😔 '{search_query}' በሚል ስም የተመዘገበ ተማሪ አልተገኘም።")
        return

    msg = f"✅ **የፍለጋ ውጤት ለ፦ '{search_query}'**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for user in results:
        user_info = f"👤 {user.full_name} | 📞 {user.phone_number}"
        markup.add(types.InlineKeyboardButton(text=user_info, callback_data=f"dev_user_ops_{user.id}"))
    
    markup.add(types.InlineKeyboardButton(text="🔙 ወደ ዝርዝር ተመለስ", callback_data="dev_back_to_users"))
    
    bot.send_message(message.chat.id, msg, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('dev_user_ops_'))
def dev_user_operations(call):
    user_id = call.data.split('_')[-1]
    try:
        user = StudentProfile.objects.get(id=user_id)
        order_count = Order.objects.filter(student=user).count()
        
        detail = (f"👤 **የተማሪ መረጃ**\n\n"
                  f"📝 **ስም፦** {user.full_name}\n"
                  f"📞 **ስልክ፦** `{user.phone_number}`\n"
                  f"🆔 **TG ID፦** `{user.telegram_id}`\n"
                  f"🛍 **የታዘዙ ትዕዛዞች፦** {order_count}\n"
                  f"📅 **የተመዘገበበት፦** {user.created_at.strftime('%Y-%m-%d')}")
        
        markup = types.InlineKeyboardMarkup()
       
        btn_del = types.InlineKeyboardButton("🗑 ተማሪውን ሰርዝ (Ban)", callback_data=f"dev_del_user_{user.id}")
        btn_back = types.InlineKeyboardButton("🔙 ተመለስ", callback_data="dev_back_to_users")
        markup.add(btn_del, btn_back)
        
        bot.edit_message_text(detail, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.answer_callback_query(call.id, f"ስህተት፦ {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('dev_del_user_'))
def dev_delete_user_action(call):
    user_id = call.data.split('_')[-1]
    try:
        user = StudentProfile.objects.get(id=user_id)
        name = user.full_name
        user.delete() 
        bot.answer_callback_query(call.id, f"✅ {name} በተሳካ ሁኔታ ተሰርዟል!")
        dev_manage_users(call.message)
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception as e:
        bot.answer_callback_query(call.id, f"ስህተት፦ {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "dev_back_to_users")
def dev_back_to_users_callback(call):
    dev_manage_users(call.message)
    bot.delete_message(call.message.chat.id, call.message.message_id)
def show_owner_dashboard(message, owner):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    btn_verify = "🔍 ኮድ አረጋግጥ"
    btn_manage = "🍔 ሜኑ አስተዳድር"
    btn_sales = "📊 የዛሬ ሽያጭ"
    btn_settings = "🔐 ሴቲንግ"
    btn_back = "🔙 ወደ ዋና ሜኑ"
    
    if message.from_user.id == DEVELOPER_CHAT_ID:
        markup.add(btn_verify, btn_manage)
        markup.add(btn_sales, "🌐 ሁሉንም ካፌዎች እይ")
        markup.add(btn_settings, btn_back)
    else:
        markup.add(btn_verify, btn_manage)
        markup.add(btn_sales, btn_settings)
        markup.add(btn_back)
        
    bot.send_message(message.chat.id, f"✅ እንኳን ደህና መጡ የ{owner.cafe.name} ባለቤት!\nምን ማድረግ ይፈልጋሉ?", reply_markup=markup)
def check_owner_password(message, owner):
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass
      
    
    if check_password(message.text, owner.access_password):
        owner.failed_attempts = 0
        owner.save()
      
        show_owner_dashboard(message, owner)
    else:
        owner.failed_attempts += 1
        remaining = 3 - owner.failed_attempts
        if owner.failed_attempts >= 3:
            owner.is_locked = True
            owner.save()
            bot.send_message(message.chat.id, "🔒 **ከመጠን በላይ ተሳስተዋል። አካውንትዎ ተቆልፏል!**")
        else:
            owner.save()
            msg = bot.send_message(message.chat.id, f"❌ የተሳሳተ ፓስዎርድ! {remaining} ሙከራ ቀርቶታል።")
            bot.register_next_step_handler(msg, check_owner_password, owner)

@bot.message_handler(func=lambda message: message.text == '🍴 ሜኑ እይ')
def list_cafes(message):
    cafes = Cafe.objects.filter(is_active=True)
    markup = types.InlineKeyboardMarkup(row_width=1)
    for cafe in cafes:
        status = "" if cafe.is_open else " (🚫 ዝግ ነው)"
        markup.add(types.InlineKeyboardButton(
            text=f"🏘 {cafe.name.upper()}{status}", 
            callback_data=f"cafe_{cafe.id}"
        ))
    
    bot.send_message(message.chat.id, "📍 **ካፌ ይምረጡ፦**", reply_markup=markup, parse_mode="Markdown")
    
@bot.callback_query_handler(func=lambda call: call.data.startswith('cafe_'))
def show_cafe_menu(call):
    try:
        cafe_id = call.data.split('_')[1]
        items = MenuItem.objects.filter(cafe_id=cafe_id, is_available=True).select_related('cafe')
        
        if not items.exists():
            bot.answer_callback_query(call.id, "ለጊዜው ምንም አይነት የምግብ ዝርዝር የለም።")
            return

        bot.answer_callback_query(call.id, "ሜኑ በመጫን ላይ...")

        for item in items:
            markup = types.InlineKeyboardMarkup()
            
            markup.add(types.InlineKeyboardButton(f"🍱 {item.name}ን ምረጥ", callback_data=f"select_{item.id}"))
            
            caption = f"🍴 **{item.name}**\n💰 **ዋጋ: {item.price} ብር**\n📝 {item.description or ''}"
            
           
            if item.image:
                if item.id in image_cache:
                    bot.send_photo(call.message.chat.id, image_cache[item.id], caption=caption, reply_markup=markup, parse_mode="Markdown")
                else:
                    try:
                        with open(item.image.path, 'rb') as photo:
                            sent_msg = bot.send_photo(call.message.chat.id, photo, caption=caption, reply_markup=markup, parse_mode="Markdown")
                            image_cache[item.id] = sent_msg.photo[-1].file_id
                    except:
                        bot.send_message(call.message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")
            else:
                bot.send_message(call.message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in show_cafe_menu: {e}")
        bot.answer_callback_query(call.id, "ሜኑውን በማሳየት ላይ ስህተት ተፈጥሯል።")

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def handle_selection(call):
    item_id = call.data.split('_')[1]
    user_id = call.from_user.id
    
   
    if user_id not in user_carts:
        user_carts[user_id] = {}
    
    user_carts[user_id][item_id] = 1
    
   
    item = MenuItem.objects.get(id=item_id)
    
    send_quantity_picker(call.message, item, 1)

def send_quantity_picker(message, item, qty):
    
    total_price = float(item.price) * qty
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    
   
    minus_btn = types.InlineKeyboardButton("-", callback_data=f"qty_minus_{item.id}")
    qty_btn = types.InlineKeyboardButton(f"{qty}", callback_data="ignore")
    plus_btn = types.InlineKeyboardButton("+", callback_data=f"qty_plus_{item.id}")
    
    
    add_to_cart = types.InlineKeyboardButton(f"🛒 ወደ ቅርጫት ጨምር ({total_price} ብር)", callback_data=f"add_cart_{item.id}")
    back_btn = types.InlineKeyboardButton("🔙 ተመለስ", callback_data="show_menu")
    
    markup.add(minus_btn, qty_btn, plus_btn)
    markup.add(add_to_cart)
    markup.add(back_btn)
    
    text = (f"🍴 **የምግብ ስም:** {item.name}\n"
            f"💰 **የአንዱ ዋጋ:** {item.price} ብር\n"
            f"🔢 **ብዛት:** {qty}\n"
            f"------------------\n"
            f"💵 **ጠቅላላ ዋጋ:** {total_price} ብር")

    try:
       
        if message.content_type == 'photo' or message.photo:
            bot.edit_message_caption(
                caption=text,
                chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )
        else:
            
            bot.edit_message_text(
                text=text,
                chat_id=message.chat.id,
                message_id=message.message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )
    except Exception as e:
        print(f"Error updating message: {e}")
       
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('qty_'))
def update_qty(call):
    action, item_id = call.data.split('_')[1], call.data.split('_')[2]
    user_id = call.from_user.id
    item = MenuItem.objects.get(id=item_id)
    
    current_qty = user_carts.get(user_id, {}).get(item_id, 1)
    
    if action == "plus":
        current_qty += 1
    elif action == "minus":
        if current_qty > 1: 
            current_qty -= 1
        else:
            bot.answer_callback_query(call.id, "ዝቅተኛው የትዕዛዝ ብዛት 1 ነው!")
            return

    
    user_carts[user_id][item_id] = current_qty
    
    
    send_quantity_picker(call.message, item, current_qty)

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_cart_'))
def handle_add_to_cart(call):
    item_id = call.data.split('_')[2]
    user_id = call.from_user.id
    
    
    qty = user_carts.get(user_id, {}).get(item_id, 1)
    
    
    if 'final_cart' not in user_carts[user_id]:
        user_carts[user_id]['final_cart'] = {}
    
   
    user_carts[user_id]['final_cart'][item_id] = qty
    
    bot.answer_callback_query(call.id, "✅ ምግቡ ወደ ቅርጫት ተጨምሯል!")
    show_post_add_options(call.message)

def show_post_add_options(message):
    markup = types.InlineKeyboardMarkup()
  
    btn_continue = types.InlineKeyboardButton("➕ ሌላ ምግብ ጨምር", callback_data="dev_back_to_cafes")
    btn_view_cart = types.InlineKeyboardButton("🛒 ቅርጫቴን አሳይ", callback_data="view_my_cart")
    
    markup.add(btn_continue)
    markup.add(btn_view_cart)
    
    bot.send_message(message.chat.id, "ምርጫዎ ተመዝግቧል! ምን ማድረግ ይፈልጋሉ?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'view_my_cart')
def view_cart(call):
    user_id = call.from_user.id
  
    user_data = user_carts.get(user_id, {})
    cart = user_data.get('final_cart', {})
    
    if not cart:
        bot.answer_callback_query(call.id, "ቅርጫትዎ ባዶ ነው!")
        bot.send_message(call.message.chat.id, "🛒 ቅርጫትዎ ባዶ ነው። እባክዎ መጀመሪያ ምግብ ይምረጡ።")
        return

    total_sum = 0
    cart_summary = "🛒 **የመረጧቸው ምግቦች ዝርዝር**\n\n"
    
    for item_id, qty in cart.items():
        item = MenuItem.objects.get(id=item_id)
        line_total = float(item.price) * qty
        total_sum += line_total
        cart_summary += f"• {item.name} | {qty} ፍሬ x {item.price} = **{line_total} ብር**\n"
    
    cart_summary += f"\n------------------\n💰 **ጠቅላላ ድምር፦ {total_sum} ብር**"
    
    markup = types.InlineKeyboardMarkup()
    pay_btn = types.InlineKeyboardButton(f"💳 አሁን ክፈል ({total_sum} ብር)", callback_data="checkout_cart")
    clear_btn = types.InlineKeyboardButton("🗑 ቅርጫቱን አጽዳ", callback_data="clear_cart")
    
    markup.add(pay_btn)
    markup.add(clear_btn)
    
    bot.send_message(call.message.chat.id, cart_summary, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == 'clear_cart')
def clear_cart(call):
    user_id = call.from_user.id
    if user_id in user_carts and 'final_cart' in user_carts[user_id]:
        user_carts[user_id]['final_cart'] = {}
    bot.answer_callback_query(call.id, "ቅርጫቱ ጸድቷል!")
    bot.edit_message_text("🛒 ቅርጫትዎ ባዶ ተደርጓል።", call.message.chat.id, call.message.message_id)
@bot.callback_query_handler(func=lambda call: call.data == 'checkout_cart')
def checkout_cart(call):
    user_id = call.from_user.id
    cart = user_carts.get(user_id, {}).get('final_cart', {})
    
    if not cart:
        bot.answer_callback_query(call.id, "ቅርጫትዎ ባዶ ነው!")
        return

    total_sum = Decimal('0.00')
    items_to_order = []
    cart_summary_text = ""
    cart_json_data = {}

    try:
        for item_id, qty in cart.items():
            item = MenuItem.objects.get(id=item_id)
            if item.current_stock < qty:
                bot.send_message(call.message.chat.id, f"😔 ይቅርታ፣ **{item.name}** የቀረው {item.current_stock} ፍሬ ብቻ ነው።")
                return
            
            price = Decimal(str(item.price))
            total_sum += price * qty
            items_to_order.append((item, qty))
            cart_summary_text += f"• {item.name} ({qty} ፍሬ) "
            cart_json_data[item.name] = qty

        student = StudentProfile.objects.get(telegram_id=user_id)
        
       
        order = Order.objects.create(
            student=student, 
            total_price=total_sum, 
            status='PENDING',
            items_json=json.dumps(cart_json_data) 
        )

        
        if items_to_order:
            order.items.add(items_to_order[0][0])

        
        for item, qty in items_to_order:
            item.current_stock -= qty
            item.save()

        
        url = initialize_chapa_payment(order, student, total_sum, cart_summary_text)
        
        if url:
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("💳 አጠቃላይ ክፈል", url=url))
            bot.send_message(call.message.chat.id, 
                             f"🚀 **የክፍያ ትዕዛዝ ተፈጥሯል!**\n\n"
                             f"💰 **ጠቅላላ ክፍያ፦ {total_sum} ብር**\n\n"
                             f"ክፍያውን ለመፈጸም ከታች ያለውን ቁልፍ ይጫኑ።", 
                             reply_markup=markup, parse_mode="Markdown")
            
            
            user_carts[user_id]['final_cart'] = {}
        else:
            bot.send_message(call.message.chat.id, "❌ የክፍያ ሊንክ መፍጠር አልተቻለም። እባክዎ ደግመው ይሞክሩ።")

    except Exception as e:
        print(f"Checkout Error: {e}")
        bot.send_message(call.message.chat.id, f"❌ ስህተት ተከስቷል፦ {str(e)}")
@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def confirm_order(call):
    item_id = call.data.split('_')[1]
    item = MenuItem.objects.get(id=item_id)
    markup = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("✅ አዎ", callback_data=f"pay_now_{item.id}"),
        types.InlineKeyboardButton("❌ አይደለም", callback_data="cancel_order")
    )
    try:
        
        bot.edit_message_caption(caption=f"📝 **{item.name}** ማዘዝ ይፈልጋሉ?", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    except:
       
        bot.edit_message_text(text=f"📝 **{item.name}** ማዘዝ ይፈልጋሉ?", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_now_'))
def process_pay(call):
    item_id = call.data.split('_')[2]
    item = MenuItem.objects.get(id=item_id)
    if item.current_stock <= 0:
       
        if item.is_available: 
             markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⏳ ሲመጣ 'ቲንግ' በሉኝ", callback_data=f"wait_{item.id}"))
             bot.send_message(call.message.chat.id, f"😔 ይቅርታ፣ **{item.name}** ለጊዜው አልቋል። ሲዘጋጅ መልእክት እንዲደርስዎ ይፈልጋሉ?", reply_markup=markup)
     
        else:
             bot.send_message(call.message.chat.id, f"🚫 ይቅርታ፣ **{item.name}** ለዛሬ አልቋል። እባክዎ ሌላ ምግብ ይምረጡ።")
        return
    
    item.current_stock -= 1
    item.save()
  
    owner = CafeOwner.objects.filter(cafe=item.cafe).first()
    if owner:
      
        if item.current_stock == 5:
            bot.send_message(owner.telegram_id, f"⚠️ **ማስጠንቀቂያ!**\n\nየ**{item.name}** ክምችት **5 ፍሬ** ብቻ ቀርቷል። ማዘጋጀት ቢጀምሩ ይመከራል!")
       
        elif item.current_stock <= 0:
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("⏳ ተማሪው ይጠባበቅ", callback_data=f"mode_wait_{item.id}"),
                types.InlineKeyboardButton("🚫 ለዛሬ ይብቃ", callback_data=f"mode_stop_{item.id}")
            )
            bot.send_message(owner.telegram_id, 
                f"❌ **{item.name}** አልቋል!\n\nተማሪዎች በ 'ቲንግ' ተመዝግበው ይጠብቁ ወይንስ ለዛሬ ይብቃ?", 
                reply_markup=markup, parse_mode="Markdown")
    student = StudentProfile.objects.get(telegram_id=call.from_user.id)
    order = Order.objects.create(student=student, total_price=item.price, status='PENDING')
    order.items.add(item)
    url = initialize_chapa_payment(order, student, item)
    if url:
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("💳 ክፈል", url=url))
        bot.edit_message_caption(f"🚀 **ክፍያውን ይፈጽሙ!**\n💰 {item.price} ብር", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text == '🔍 ኮድ አረጋግጥ')
def ask_code(message):
    user_id = message.from_user.id
    
    if is_cafe_owner(user_id) or is_authorized_employee(user_id):
        msg = bot.send_message(message.chat.id, "🔢 የመቀበያ ኮድ ያስገቡ፦")
        bot.register_next_step_handler(msg, verify_pickup_code)
    else:
        bot.send_message(message.chat.id, "🚫 ይህን ለማድረግ ፈቃድ የለዎትም።")

def verify_pickup_code(message):
    code = message.text.upper().strip()
    user_id = message.from_user.id
    
    try:
       
        is_emp = is_authorized_employee(user_id)
        is_own = is_cafe_owner(user_id)
        
        if not (is_emp or is_own): return

        if is_own and user_id != DEVELOPER_CHAT_ID:
            cafe = CafeOwner.objects.get(telegram_id=user_id).cafe
        elif is_emp:
            cafe = Cafe.objects.get(employee_telegram_id=user_id)
        else: 
            cafe = Cafe.objects.first()

        order = Order.objects.filter(pickup_code=code).first()
        
        if not order:
            bot.send_message(message.chat.id, "⚠️ ይህ ኮድ በጭራሽ አልተፈጠረም!")
            return

        order_item = order.items.first()
        if order_item.cafe != cafe:
            bot.send_message(message.chat.id, f"🚫 ይህ የሌላ ካፌ ኮድ ነው!\n(የ{order_item.cafe.name} ኮድ ነው)")
            return

        
        items_detail = ""
        if order.items_json:
            try:
                items_dict = json.loads(order.items_json)
                for name, qty in items_dict.items():
                    items_detail += f"• {name} ({qty} ፍሬ)\n"
            except:
                items_detail = f"• {order_item.name if order_item else 'ያልታወቀ ምግብ'}"
        else:
            items_detail = f"• {order_item.name if order_item else 'ያልታወቀ ምግብ'}"

        buyer_name = order.student.full_name if (order.student and order.student.full_name) else "ያልታወቀ ተማሪ"
        
        if order.status == 'COMPLETED':
           
            order_time = getattr(order, 'updated_at', order.created_at) 
            used_at_et = order_time.astimezone(ethiopia_tz).strftime('%b-%d %I:%M %p')
            
            msg = (f"🚨 ይህ ኮድ ቀድሞውኑ አገልግሏል!\n\n"
                   f"👤 **ለተጠቃሚ፦** {buyer_name}\n"
                   f"🍴 **ምግቦች፦**\n{items_detail}"
                   f"⏰ **የተጠቀመበት ሰዓት፦** {used_at_et} (EAT)\n\n"
                   f"❌ ደግመው ማገልገል አይችሉም።")
            bot.send_message(message.chat.id, msg)
            return

        if order.is_paid:
            order.status = 'COMPLETED'
            order.verified_by_id = user_id 
            order.save()
            
            bot.send_message(message.chat.id, f"✅ ተረጋግጧል!\n👤 ተመጋቢ: {buyer_name}\n🍔 የታዘዙ ምግቦች፦: {items_detail}\n👉 አሁን መስጠት ይችላሉ።")
        else:
            bot.send_message(message.chat.id, "💳 **ይህ ትዕዛዝ ክፍያው አልተጠናቀቀም!")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ ስህተት: {str(e)}")
@bot.message_handler(func=lambda message: message.text == '🛍 ትዕዛዞቼ')
@bot.message_handler(func=lambda message: message.text == '🛍 ትዕዛዞቼ')
def my_orders(message):
    try:
        student = StudentProfile.objects.get(telegram_id=message.from_user.id)
        orders = Order.objects.filter(student=student).order_by('-created_at')[:10]
        
        if not orders.exists():
            bot.send_message(message.chat.id, "🛍 **እስካሁን ምንም ትዕዛዝ አልፈጠሩም።**\nበ '🍴 ሜኑ እይ' በኩል ማዘዝ ይችላሉ።", parse_mode="Markdown")
            return

        msg = "📋 **የመጨረሻዎቹ 10 ትዕዛዞችዎ፦**\n\n"
        for o in orders:
            
            item = o.items.first()
            item_name = item.name if item else "ያልታወቀ ምግብ"
            
            status_icon = "✅" if o.status == 'COMPLETED' else "⏳" if o.is_paid else "❌"
            msg += f"{status_icon} {item_name} | {o.total_price} ብር\n🔑 ኮድ: `{o.pickup_code}`\n\n"
            
        bot.send_message(message.chat.id, msg, parse_mode="Markdown")
    except StudentProfile.DoesNotExist:
        bot.send_message(message.chat.id, "⚠️ መጀመሪያ መመዝገብ አለብዎት።")
    except Exception as e:
        print(f"Error in my_orders: {e}") 
        bot.send_message(message.chat.id, "😔 ትዕዛዞችን ማግኘት አልተቻለም። እባክዎ ጥቂት ቆይተው ይሞክሩ።")

@bot.message_handler(func=lambda message: message.text == '🔙 ወደ ዋና ሜኑ')
def back_to_main_fix(message):
    send_welcome(message)
@bot.message_handler(func=lambda message: message.text in ['🔍 ኮድ አረጋግጥ', '🔙 ወደ ዋና ሜኑ'])
def employee_buttons_priority(message):
    user_id = message.from_user.id
    if message.text == '🔍 ኮድ አረጋግጥ':
        if is_authorized_employee(user_id) or is_cafe_owner(user_id):
            ask_code(message)
    elif message.text == '🔙 ወደ ዋና ሜኑ':
        send_welcome(message)

@bot.message_handler(func=lambda message: message.text in ['🍔 ሜኑ አስተዳድር', '📊 የዛሬ ሽያጭ', '🔐 ሴቲንግ', '🌐 ሁሉንም ካፌዎች እይ'])
def owner_dashboard_router(message):
    user_id = message.from_user.id
    if not is_cafe_owner(user_id): return

    if message.text == '🍔 ሜኑ አስተዳድር':
        markup = types.InlineKeyboardMarkup(row_width=1)
        btn_add = types.InlineKeyboardButton("➕ አዲስ ምግብ ጨምር", callback_data="admin_add_item")
        btn_list = types.InlineKeyboardButton("📜 ያሉ ምግቦችን ዝርዝር/አስተካክል", callback_data="admin_list_items")
        markup.add(btn_add, btn_list)
        
        bot.send_message(message.chat.id, "🍴 **የምግብ ማውጫ ማስተዳደሪያ**\nምን ማድረግ ይፈልጋሉ?", reply_markup=markup, parse_mode="Markdown")
        
    elif message.text == '📊 የዛሬ ሽያጭ':
        show_daily_sales(message)
        
    elif message.text == '🔐 ሴቲንግ':
        user_id = message.from_user.id
        owner = CafeOwner.objects.get(telegram_id=user_id) if user_id != DEVELOPER_CHAT_ID else CafeOwner.objects.first()
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        btn_toggle = types.InlineKeyboardButton(f"🕒 ካፌውን {'ዝጋ 🚫' if owner.cafe.is_open else 'ክፈት ✅'}", callback_data=f"admin_toggle_status_{owner.cafe.id}")
        btn_emp_pw = types.InlineKeyboardButton("🔑 የሰራተኛ ኮድ ቀይር", callback_data="admin_change_emp_pw")
        btn_emp_id = types.InlineKeyboardButton("🆔 የሰራተኛ Telegram ID መዝግብ", callback_data="admin_change_emp_id")
        btn_owner_pw = types.InlineKeyboardButton("🔐 የባለቤት (የእርሶ) ኮድ ቀይር", callback_data="admin_change_owner_pw")
        btn_staff_info = types.InlineKeyboardButton("👥 የሰራተኛ መረጃ/ታሪክ", callback_data="admin_staff_info")
        
        markup.add(btn_toggle, btn_emp_pw, btn_emp_id, btn_owner_pw, btn_staff_info)

        emp_id_display = owner.cafe.employee_telegram_id if owner.cafe.employee_telegram_id else "ያልተመዘገበ"
        status_text = "✅ ክፍት" if owner.cafe.is_open else "🚫 ዝግ"
        
        msg = (f"⚙️ **የካፌ አስተዳዳሪ ሴቲንግ**\n\n"
               f"🏪 **ካፌ፦** {owner.cafe.name}\n"
               f"💰 **ባላንስ፦** `{owner.cafe.balance} ETB`\n"
               f"📊 **ሁኔታ፦** {status_text}\n"
               f"🔑 **የሰራተኛ ኮድ፦** `{owner.cafe.employee_password}`\n"
               f"👤 **የሰራተኛ ID፦** `{emp_id_display}`")
        bot.send_message(message.chat.id, msg, reply_markup=markup, parse_mode="Markdown")
        
    elif message.text == '🌐 ሁሉንም ካፌዎች እይ':
        if user_id == DEVELOPER_CHAT_ID:
            bot.send_message(message.chat.id, "👨‍💻 **ክቡር ዴቨሎፐር ሆይ፣ የሁሉንም ካፌዎች መረጃ እዚህ ያገኛሉ።**")
def back_to_main(message): send_welcome(message)

print("ስማርት ካምፓስ (Turbo & Secure 🚀🛡️) በሙሉ አቅሙ ስራ ጀምሯል...")
@bot.callback_query_handler(func=lambda call: call.data.startswith('dev_view_cafe_'))
def dev_view_cafe_details(call):
    cafe_id = call.data.split('_')[-1]
    try:
        cafe = Cafe.objects.get(id=cafe_id)
        owner = CafeOwner.objects.get(cafe=cafe)
        
        msg = (f"🏢 **የካፌ መረጃ፦ {cafe.name}**\n\n"
               f"👤 **ባለቤት (User)፦** {owner.user.username}\n"
               f"🆔 **Telegram ID፦** `{owner.telegram_id}`\n"
               f"💰 **Balance፦** {cafe.balance} ETB\n"
               f"📊 **ሁኔታ፦** {'ክፍት ✅' if cafe.is_open else 'ዝግ 🚫'}")
        
        markup = types.InlineKeyboardMarkup()
        btn_del = types.InlineKeyboardButton("🗑 ካፌውን ሰርዝ", callback_data=f"dev_del_cafe_{cafe.id}")
        btn_back = types.InlineKeyboardButton("🔙 ወደ ዝርዝር ተመለስ", callback_data="dev_back_to_cafes")
        markup.add(btn_del)
        markup.add(types.InlineKeyboardButton("🆔 ባለቤት ID ቀይር", callback_data=f"dev_chg_owner_id_{cafe.id}"))
        markup.add(btn_back)
        
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.answer_callback_query(call.id, f"ስህተት፦ {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('dev_chg_owner_id_'))
def dev_ask_new_owner_id(call):
    cafe_id = call.data.split('_')[-1]
    msg = bot.send_message(call.message.chat.id, "🔢 እባክዎ አዲሱን የባለቤቱን **Telegram ID** በቁጥር ብቻ ያስገቡ፦")
    bot.register_next_step_handler(msg, dev_save_new_owner_id, cafe_id)

def dev_save_new_owner_id(message, cafe_id):
    try:
        new_id = int(message.text.strip())
        owner = CafeOwner.objects.get(cafe_id=cafe_id)
        owner.telegram_id = new_id
        owner.save()
        bot.send_message(message.chat.id, f"✅ የባለቤቱ ID ወደ `{new_id}` ተቀይሯል!")
    except ValueError:
        bot.send_message(message.chat.id, "❌ ስህተት! እባክዎ ቁጥር ብቻ ያስገቡ።")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ ስህተት፦ {str(e)}")        

@bot.callback_query_handler(func=lambda call: call.data == "dev_back_to_cafes")
def dev_back_to_cafes(call):
    dev_manage_cafes(call.message)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    

@bot.callback_query_handler(func=lambda call: call.data.startswith('dev_del_cafe_'))
def dev_confirm_delete_cafe(call):
    cafe_id = call.data.split('_')[-1]
    try:
        cafe = Cafe.objects.get(id=cafe_id)
        
        markup = types.InlineKeyboardMarkup()
       
        btn_yes = types.InlineKeyboardButton("🗑 አዎ፣ ወደ ሪሳይክል ቢን ላከው", callback_data=f"dev_softdelete_yes_{cafe_id}")
        btn_no = types.InlineKeyboardButton("❌ አይ፣ ተመለስ", callback_data="dev_back_to_cafes")
        markup.add(btn_yes, btn_no)
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"⚠️ **ካፌውን ማጥፋት ይፈልጋሉ?**\n\n"
                 f"ስም፦ **{cafe.name}**\n\n"
                 f"ይህ ካፌ ለጊዜው እንዲደበቅ እና ወደ ሪሳይክል ቢን እንዲዛወር እርግጠኛ ነዎት?",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Cafe.DoesNotExist:
        bot.answer_callback_query(call.id, "❌ ካፌው አልተገኘም።")


@bot.callback_query_handler(func=lambda call: call.data.startswith("dev_softdelete_yes_"))
def dev_execute_soft_delete(call):
    cafe_id = call.data.split('_')[-1]
    try:
        from django.utils import timezone
        cafe = Cafe.objects.get(id=cafe_id)
        
        # 1. Soft Delete
        cafe.is_deleted = True
        cafe.deleted_at = timezone.now()
        cafe.is_active = False 
        cafe.save()

        
        owners = CafeOwner.objects.filter(cafe=cafe)
        for owner in owners:
            try:
                
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                markup.add('🍴 ሜኑ እይ', '🛍 ትዕዛዞቼ') 
                bot.send_message(
                    owner.telegram_id, 
                    f"⚠️ **ማሳሰቢያ**\n\nየእርስዎ ካፌ (**{cafe.name}**) በአድሚኑ ታግዷል።", 
                    reply_markup=markup, 
                    parse_mode="Markdown"
                )
            except: pass
        
        owners.update(is_authorized=False)
        
        bot.edit_message_text(
            chat_id=call.message.chat.id, 
            message_id=call.message.message_id,
            text=f"✅ **'{cafe.name}'** ወደ ሪሳይክል ቢን ተዛውሯል።\n\nባለቤቱም ዳሽቦርዱን መጠቀም አይችልም።",
            reply_markup=None
        )
        
        bot.answer_callback_query(call.id, "ተጠናቅቋል")
        
        
        import time
        time.sleep(1.5)
        
        dev_manage_cafes(call.message)
        
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ ስህተት ተፈጥሯል፦ {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_item")
def start_add_item(call):
    msg = bot.send_message(call.message.chat.id, "📝 **የምግቡን ስም ያስገቡ፦**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_item_name)

def process_item_name(message):
    item_name = message.text
    msg = bot.send_message(message.chat.id, f"💰 **የ{item_name} ዋጋ ስንት ነው?** (በቁጥር ብቻ ያስገቡ)፦", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_item_price, item_name)

def process_item_price(message, item_name):
    try:
        price = float(message.text)
        msg = bot.send_message(message.chat.id, f"📸 **ለ{item_name} ፎቶ ይላኩ፦**\n(ፎቶ ከሌለ 'አልፈልግም' ብለው ይፃፉ)", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_item_photo, item_name, price)
    except ValueError:
        msg = bot.send_message(message.chat.id, "⚠️ እባክዎ ዋጋውን በቁጥር ብቻ ያስገቡ (ለምሳሌ፦ 120)፦")
        bot.register_next_step_handler(msg, process_item_price, item_name)

def process_item_photo(message, item_name, price):
    user_id = message.from_user.id
    owner = CafeOwner.objects.get(telegram_id=user_id)
    
    new_item = MenuItem(
        cafe=owner.cafe,
        name=item_name,
        price=price,
        is_available=True
    )

    if message.content_type == 'photo':
       
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        file_name = f"{uuid.uuid4().hex}.jpg"
        file_path = os.path.join('media/menu_images', file_name)
        
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        new_item.image = f"menu_images/{file_name}"
        msg = bot.send_message(message.chat.id, f"🔢 የ**{item_name}** ክምችት (Stock) ስንት ይሁን? (ለምሳሌ 50)፦", parse_mode="Markdown")
        bot.register_next_step_handler(msg, finalize_item_creation, new_item)
def finalize_item_creation(message, new_item):
    try:
       
        amount = int(message.text)
        new_item.current_stock = amount
        new_item.stock_quantity = amount
        new_item.save()
       
        if new_item.image:
            msg_text = f"✅ **{new_item.name}** በ {new_item.price} ብር ከፎቶ ጋር በተሳካ ሁኔታ ተመዝግቧል!\n📦 ክምችት፦ {amount}"
        else:
            msg_text = f"✅ **{new_item.name}** በ {new_item.price} ብር ያለ ፎቶ ተመዝግቧል!\n📦 ክምችት፦ {amount}"
            
        bot.send_message(message.chat.id, msg_text, parse_mode="Markdown")
        
    except ValueError:

        msg = bot.send_message(message.chat.id, "⚠️ እባክዎ መጠኑን በቁጥር ብቻ ያስገቡ (ለምሳሌ፦ 50)፦")
        bot.register_next_step_handler(msg, finalize_item_creation, new_item)
    except Exception as e:
        
        bot.send_message(message.chat.id, f"❌ ስህተት ተፈጥሯል፦ {str(e)}")
       
@bot.callback_query_handler(func=lambda call: call.data == "admin_list_items")
def admin_list_items(call):
    user_id = call.from_user.id
    try:
        if user_id == DEVELOPER_CHAT_ID:
            owner = CafeOwner.objects.first()
        else:
            owner = CafeOwner.objects.get(telegram_id=user_id)
            
        items = MenuItem.objects.filter(cafe=owner.cafe)
        
        if not items:
            bot.send_message(call.message.chat.id, "🚫 እስካሁን የተመዘገበ ምግብ የለም።")
            return

        bot.send_message(call.message.chat.id, f"📋 **የ{owner.cafe.name} የምግብ ዝርዝር፦**", parse_mode="Markdown")
        
        for item in items:
            status = "✅ በክምችት ላይ" if item.is_available else "🚫 ያለቀ"
            markup = types.InlineKeyboardMarkup()
           
            btn_toggle = types.InlineKeyboardButton(f"🔄 ሁኔታውን ቀይር ({'አቁም' if item.is_available else 'አስጀምር'})", callback_data=f"toggle_{item.id}")
            btn_delete = types.InlineKeyboardButton("🗑️ አጥፋ", callback_data=f"del_item_{item.id}")
            btn_stock = types.InlineKeyboardButton(f"📦 ክምችት ሙላ ({item.current_stock} ቀርቷል)", callback_data=f"set_stock_{item.id}")
            markup.add(btn_toggle)
            markup.add(btn_stock)
            markup.add(btn_delete)
            
            caption = f"🍴 **{item.name}**\n💰 ዋጋ፦ {item.price} ብር\n📊 ሁኔታ፦ {status}"
            
            if item.image:
                try:
                    bot.send_photo(call.message.chat.id, item.image.url if hasattr(item.image, 'url') else item.image.path, caption=caption, reply_markup=markup, parse_mode="Markdown")
                except:
                    bot.send_message(call.message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")
            else:
                bot.send_message(call.message.chat.id, caption, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ ስህተት፦ {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('mode_'))
def handle_owner_decision(call):
   
    decision = call.data.split('_')[1] 
    item_id = call.data.split('_')[2]
    item = MenuItem.objects.get(id=item_id)
    
    if decision == "wait":
        item.is_available = True 
        item.save()
        bot.edit_message_text(f"⏳ ለ{item.name} 'ተጠባባቂ' ሁነታ በርቷል። ተማሪዎች መመዝገብ ይችላሉ።", call.message.chat.id, call.message.message_id)
    else:
        item.is_available = False 
        item.save()
        bot.edit_message_text(f"🚫 {item.name} ለዛሬ እንዲቆም ተደርጓል። ተማሪዎች ማዘዝ አይችሉም።", call.message.chat.id, call.message.message_id)
        
@bot.callback_query_handler(func=lambda call: call.data.startswith(('toggle_', 'del_item_')))
def handle_item_edit(call):
    data = call.data
    item_id = data.split('_')[-1]
    item = MenuItem.objects.get(id=item_id)
    
    if data.startswith('toggle_'):
       
        item.is_available = not item.is_available
        item.save()
        status_text = "አሁን በክምችት ላይ ይገኛል" if item.is_available else "አሁን አልቋል ተብሎ ተመዝግቧል"
        bot.answer_callback_query(call.id, f"✅ {item.name} {status_text}።")

        admin_list_items(call) 

    elif data.startswith('del_item_'):

        name = item.name
        item.delete()
        bot.answer_callback_query(call.id, f"🗑️ {name} ተሰርዟል።")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        from django.db.models import Sum, Count

@bot.message_handler(func=lambda message: message.text == '📊 የዛሬ ሽያጭ')
def show_daily_sales(message):
    user_id = message.from_user.id
    if not is_cafe_owner(user_id):
        bot.send_message(message.chat.id, "🚫 **ይህ መረጃ ለእርስዎ አልተፈቀደም!**")
        return

    loading_msg = bot.send_message(message.chat.id, "🔄 **ሪፖርቱን በማመንጨት ላይ...**")

    try:

        if user_id == DEVELOPER_CHAT_ID:
            owner = CafeOwner.objects.first()
        else:
            owner = CafeOwner.objects.get(telegram_id=user_id)

        today = timezone.now().astimezone(ethiopia_tz).date()

        daily_orders = Order.objects.filter(
            items__cafe=owner.cafe,
            status='COMPLETED',
            created_at__date=today
        ).distinct()

        total_revenue = daily_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
        total_customers = daily_orders.count()

        best_seller = daily_orders.values('items__name').annotate(count=Count('items')).order_by('-count').first()
        best_seller_name = best_seller['items__name'] if best_seller else "የለም"
        best_seller_count = best_seller['count'] if best_seller else 0

        report = (
            f"📊 **የዛሬ የንግድ ዳሽቦርድ**\n"
            f"🏘 **ካፌ፦** {owner.cafe.name}\n"
            f"📅 **ቀን፦** {today.strftime('%b %d, %Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 **ጠቅላላ ገቢ፦** `{total_revenue} ETB`\n"
            f"👥 **የተስተናገዱ ተማሪዎች፦** `{total_customers}`\n"
            f"🔥 **ተወዳጅ ምግብ፦** `{best_seller_name}` ({best_seller_count} ጊዜ ተሽጧል)\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ *ሪፖርቱ በራስ-ሰር በየቀኑ ይታደሳል።*"
        )

        bot.edit_message_text(report, chat_id=message.chat.id, message_id=loading_msg.message_id, parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ **ስህተት ተፈጥሯል፦** {str(e)}", chat_id=message.chat.id, message_id=loading_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_toggle_status_'))
def toggle_cafe_status(call):
    cafe_id = call.data.split('_')[-1]
    cafe = Cafe.objects.get(id=cafe_id)
    cafe.is_open = not cafe.is_open
    cafe.save()
    bot.answer_callback_query(call.id, f"✅ ካፌው ተሳክቶለታል!")
    bot.delete_message(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_change_emp_pw")
def ask_new_emp_pw(call):
    msg = bot.send_message(call.message.chat.id, "🔢 **አዲሱን የሰራተኛ መለያ ኮድ ያስገቡ፦**")
    bot.register_next_step_handler(msg, update_employee_password)

def update_employee_password(message):
    new_pw = message.text.strip()
    owner = CafeOwner.objects.get(telegram_id=message.from_user.id)
    owner.cafe.employee_password = new_pw
    owner.cafe.save()
    bot.send_message(message.chat.id, f"✅ የሰራተኛ ኮድ ወደ `{new_pw}` ተቀይሯል!")


@bot.message_handler(func=lambda message: message.text == '👨‍🍳 የሰራተኛ መግቢያ')
def employee_login_start(message):
    user_id = message.from_user.id
    try:
        cafe = Cafe.objects.get(employee_telegram_id=user_id)
        
      
        if cafe.is_employee_locked:
            bot.send_message(message.chat.id, "🔒 **የሰራተኛ አካውንትዎ ታግዷል!**\nእባክዎ የካፌውን ባለቤት ያነጋግሩ።")
            return

        msg = bot.send_message(message.chat.id, "🔑 **የሰራተኛ መግቢያ ፓስዎርድ ያስገቡ፦**")
        
        bot.register_next_step_handler(msg, lambda m: process_employee_auth(m, cafe))
    except Cafe.DoesNotExist:
        bot.send_message(message.chat.id, "❌ እርስዎ የተመዘገቡ ሰራተኛ አይደሉም።")


def process_employee_auth(message, cafe):
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
   
    if not message.text or message.text.startswith('/'):
        msg = bot.send_message(message.chat.id, "⚠️ እባክዎ መጀመሪያ ፓስዎርድ ያስገቡ፦")
        bot.register_next_step_handler(msg, lambda m: process_employee_auth(m, cafe))
        return

    entered_pw = message.text.strip()
    
    
    if entered_pw == cafe.employee_password:
        cafe.employee_failed_attempts = 0
        cafe.is_employee_locked = False
        cafe.save()
        
       
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🔍 ኮድ አረጋግጥ", "🔙 ወደ ዋና ሜኑ")
        
        bot.send_message(message.chat.id, f"✅ እንኳን ደህና መጡ! የ{cafe.name} ሰራተኛ መሆንዎ ተረጋግጧል።", reply_markup=markup)
    else:
      
        cafe.employee_failed_attempts += 1
        remaining = 3 - cafe.employee_failed_attempts
        
        if cafe.employee_failed_attempts >= 3:
            cafe.is_employee_locked = True
            cafe.save()
            bot.send_message(message.chat.id, "🔒 **ፓስዎርድ 3 ጊዜ ተሳስተዋል። አካውንትዎ ተቆልፏል!**\nባለቤቱን ያነጋግሩ።")
        else:
            cafe.save()
            msg = bot.send_message(message.chat.id, f"❌ የተሳሳተ ኮድ! {remaining} ሙከራ ቀርቶታል።\nእንደገና ይሞክሩ፦")
            bot.register_next_step_handler(msg, lambda m: process_employee_auth(m, cafe))
@bot.callback_query_handler(func=lambda call: call.data == "admin_change_emp_id")      
def ask_emp_id(call):
        msg = bot.send_message(call.message.chat.id, "👤 **እባክዎ የሰራተኛውን የቴሌግራም ID ያስገቡ፦**\n(ID ለማግኘት ሰራተኛው @userinfobot ላይ ሄዶ ማየት ይችላል)")
        bot.register_next_step_handler(msg, update_employee_id)

def update_employee_id(message):
    try:
        new_id = int(message.text.strip())
        user_id = message.from_user.id
        owner = CafeOwner.objects.get(telegram_id=user_id) if user_id != DEVELOPER_CHAT_ID else CafeOwner.objects.first()
        
        owner.cafe.employee_telegram_id = new_id
        owner.cafe.save()
        bot.send_message(message.chat.id, f"✅ የሰራተኛ ID `{new_id}` በተሳካ ሁኔታ ተመዝግቧል! አሁን ሰራተኛው ቦቱን ሲያስጀምር መግቢያው ይታይለታል።")
    except ValueError:
        bot.send_message(message.chat.id, "❌ ስህተት! እባክዎ ID በቁጥር ብቻ ያስገቡ።")

@bot.callback_query_handler(func=lambda call: call.data == "admin_change_owner_pw")
def ask_old_owner_pw(call):
    msg = bot.send_message(call.message.chat.id, "🔒 **መጀመሪያ አሁን ያለውን ሚስጥራዊ ቃልዎን ያስገቡ፦**")
    bot.register_next_step_handler(msg, verify_old_owner_pw)

def verify_old_owner_pw(message):
    user_id = message.from_user.id
    owner = CafeOwner.objects.get(telegram_id=user_id) if user_id != DEVELOPER_CHAT_ID else CafeOwner.objects.first()
    
    if check_password(message.text, owner.access_password):
        msg = bot.send_message(message.chat.id, "✅ ተረጋግጧል! አሁን **አዲሱን ሚስጥራዊ ቃል** ያስገቡ፦")
        bot.register_next_step_handler(msg, save_new_owner_pw)
    else:
        bot.send_message(message.chat.id, "❌ የድሮው ፓስዎርድ ስህተት ነው። እንደገና ይሞክሩ።")

def save_new_owner_pw(message):
    new_pw = message.text.strip()
   
    if len(new_pw) < 6 or new_pw.isdigit() or new_pw.isalpha():
        bot.send_message(message.chat.id, "⚠️ **ደህንነቱ ያልተጠበቀ ፓስዎርድ!**\n\n* ቢያንስ 6 ቁምፊ መሆን አለበት\n* የፊደል እና የቁጥር ድብልቅ ይጠቀሙ (ቁጥር ብቻ ወይም ፊደል ብቻ አይቻልም)")
        bot.register_next_step_handler(message, save_new_owner_pw) 
        return

    user_id = message.from_user.id
    owner = CafeOwner.objects.get(telegram_id=user_id) if user_id != DEVELOPER_CHAT_ID else CafeOwner.objects.first()
    
    owner.access_password = make_password(new_pw)
    owner.save()
   
    bot.send_message(message.chat.id, "🎊 እንኳን ደስ አለዎት! የባለቤት መግቢያ ሚስጥራዊ ቃልዎ በተሳካ ሁኔታ ተቀይሯል።")

    
    send_welcome(message)
@bot.callback_query_handler(func=lambda call: call.data == "admin_staff_info")
def handle_staff_info(call):
    user_id = call.from_user.id
    try:
        
        owner = CafeOwner.objects.get(telegram_id=user_id) if user_id != DEVELOPER_CHAT_ID else CafeOwner.objects.first()
        cafe = owner.cafe
        emp_id = cafe.employee_telegram_id
        
       
        status_text = "🟢 ንቁ (Active)"
        if cafe.is_employee_locked:
            status_text = "🔴 የታገደ (Locked)"

        msg = f"👥 **የሰራተኛ መረጃ ማዕከል**\n"
        msg += f"🆔 **ID:** `{emp_id if emp_id else 'ያልተመዘገበ'}`\n"
        msg += f"📊 **ሁኔታ፦** {status_text}\n"
        if cafe.is_employee_locked:
            msg += f"⚠️ **የተሳሳቱ ሙከራዎች፦** {cafe.employee_failed_attempts}/3\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━\n"

        if not emp_id:
            msg += "⚠️ ሰራተኛ አልተመዘገበም።"
        else:
            staff_sales = Order.objects.filter(
                items__cafe=cafe, 
                status='COMPLETED',
                verified_by_id=emp_id 
            ).order_by('-created_at')[:10]

            msg += f"📜 **በዚህ ሰራተኛ የተረጋገጡ (የቅርብ ጊዜ)፦**\n\n"
            if not staff_sales.exists():
                msg += "ምንም ታሪክ የለም።"
            else:
                for order in staff_sales:
                    time = order.created_at.astimezone(ethiopia_tz).strftime('%I:%M %p')
                    
                    item_obj = order.items.first()
                    item_name = item_obj.name if item_obj else "ምግብ"
                    msg += f"⏰ {time} | 🍔 {item_name} | 💰 {order.total_price} ETB\n"

        markup = types.InlineKeyboardMarkup()
        
       
        if cafe.is_employee_locked:
            markup.add(types.InlineKeyboardButton("🔓 እገዳ ፍታ (Unlock)", callback_data=f"unlock_emp_{cafe.id}"))
        
       
        if emp_id:
            markup.add(types.InlineKeyboardButton("🗑️ የሰራተኛ ID ሰርዝ", callback_data="admin_clear_staff_id"))
        
       
        markup.add(types.InlineKeyboardButton("⬅️ ተመለስ", callback_data=f"manage_cafe_{cafe.id}"))
        
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        
    except Exception as e:
        bot.answer_callback_query(call.id, f"ስህተት፦ {str(e)}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("unlock_emp_"))
def unlock_employee_action(call):
    cafe_id = call.data.split("_")[-1]
    try:
        from cafes.models import Cafe
        cafe = Cafe.objects.get(id=cafe_id)
        cafe.is_employee_locked = False
        cafe.employee_failed_attempts = 0
        cafe.save()
        
        bot.answer_callback_query(call.id, "✅ የሰራተኛው እገዳ ተነስቷል!", show_alert=True)
      
        handle_staff_info(call)
    except Exception as e:
        bot.answer_callback_query(call.id, f"ስህተት፦ {str(e)}")
    
@bot.callback_query_handler(func=lambda call: call.data == "admin_clear_staff_id")
def clear_staff_id_action(call):
    owner = CafeOwner.objects.get(telegram_id=call.from_user.id) if call.from_user.id != DEVELOPER_CHAT_ID else CafeOwner.objects.first()
    owner.cafe.employee_telegram_id = None
    owner.cafe.save()
    bot.answer_callback_query(call.id, "✅ የሰራተኛው ID ተሰርዟል!")
    bot.edit_message_text("✅ የሰራተኛው Telegram ID ተሰርዟል። አሁን ሰራተኛው ዳሽቦርዱን ማየት አይችልም።", call.message.chat.id, call.message.message_id)
@bot.callback_query_handler(func=lambda call: call.data.startswith('wait_'))
def add_to_waitlist(call):
    item_id = call.data.split('_')[1]
    item = MenuItem.objects.get(id=item_id)
    student = StudentProfile.objects.get(telegram_id=call.from_user.id)
    
    Waitlist.objects.get_or_create(student=student, menu_item=item)
    
    bot.answer_callback_query(call.id, "✅ ተመዝግበዋል! ምግቡ እንደደረሰ 'ቲንግ' የሚል መልእክት ይደርስዎታል።")
    bot.edit_message_text(f"⏳ ለ **{item.name}** በተጠባባቂ ዝርዝር ውስጥ ገብተዋል።", call.message.chat.id, call.message.message_id)
@bot.callback_query_handler(func=lambda call: call.data.startswith('set_stock_'))
def ask_stock_amount(call):
    item_id = call.data.split('_')[2]
    msg = bot.send_message(call.message.chat.id, "🔢 እባክዎ አሁን የገባውን የምግብ መጠን (ቁጥር) ብቻ ይጻፉ፦")

    bot.register_next_step_handler(msg, process_stock_update, item_id)
def process_stock_update(message, item_id):
    try:
        new_amount = int(message.text)
        item = MenuItem.objects.get(id=item_id)

        item.stock_quantity = new_amount
        item.current_stock = new_amount
        item.is_available = True
        item.save()
        
        bot.send_message(message.chat.id, f"✅ ተሳክቷል! የ**{item.name}** ክምችት ወደ {new_amount} ታድሷል።")

        waiters = Waitlist.objects.filter(menu_item=item)
        for entry in waiters:
            try:
                bot.send_message(
                    entry.student.telegram_id, 
                    f"🔔 ሠላም! የፈለጉት **{item.name}** አሁን ደርሷል። ማዘዝ ይችላሉ! 😊"
                )
                entry.delete() 
            except:
                continue 
                
    except ValueError:
        bot.send_message(message.chat.id, "❌ ስህተት፦ እባክዎ ቁጥር ብቻ ያስገቡ።")

def start_password_reset(message, owner):
    
    otp = str(random.randint(100000, 999999))
    
    if owner.email:
        bot.send_message(message.chat.id, "📨 የማረጋገጫ ኮድ ወደ ኢሜልዎ እየተላከ ነው...")
        
        if send_otp_email(owner.email, otp, owner.user.first_name):
            owner.otp_code = otp 
            owner.save()
            
            msg = bot.send_message(message.chat.id, f"📩 ኮድ ወደ {owner.email} ተልኳል።\nእባክዎ ኮዱን እዚህ ያስገቡ፦")
            
            bot.register_next_step_handler(msg, verify_otp_step, owner)
        else:
            bot.send_message(message.chat.id, "❌ ኢሜል መላክ አልተቻለም። እባክዎ ቆይተው ይሞክሩ።")
    else:
        bot.send_message(message.chat.id, "⚠️ በሲስተሙ ላይ ኢሜልዎ አልተመዘገበም። እባክዎ አድሚኑን ያነጋግሩ።") 
def verify_otp_step(message, owner):
    input_code = message.text.strip()
    
    if input_code == owner.otp_code:
        owner.otp_code = None
        owner.save()
        
        msg = bot.send_message(message.chat.id, "✅ ኮዱ ተረጋግጧል! አሁን **አዲሱን ፓስዎርድ** ያስገቡ፦")
        bot.register_next_step_handler(msg, finalize_password_reset, owner)
    else:
        bot.send_message(message.chat.id, "❌ የተሳሳተ ኮድ! እባክዎ እንደገና 'ፓስዎርድ ረሳሁ' የሚለውን ተጭነው ይሞክሩ።")

def finalize_password_reset(message, owner):
    new_password = message.text.strip()
    chat_id = message.chat.id
    message_id = message.message_id

    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass 

    if len(new_password) < 4:
        msg = bot.send_message(message.chat.id, "⚠️ ፓስዎርዱ በጣም አጭር ነው። እባክዎ ቢያንስ 4 ፊደል/ቁጥር ይጠቀሙ፦")
        bot.register_next_step_handler(msg, finalize_password_reset, owner)
        return

    owner.access_password = make_password(new_password)
    owner.failed_attempts = 0
    owner.is_locked = False
    owner.save()
    
    bot.send_message(message.chat.id, "🎊 ፓስዎርድዎ በተሳካ ሁኔታ ተቀይሯል! አሁን በአዲሱ ፓስዎርድ መግባት ይችላሉ።")  

@bot.callback_query_handler(func=lambda call: call.data == "dev_recycle_bin")
def dev_show_recycle_bin(call):
    deleted_cafes = Cafe.objects.filter(is_deleted=True)
    markup = types.InlineKeyboardMarkup()
    
    if not deleted_cafes:
        text = "♻️ **ሪሳይክል ቢን ባዶ ነው**"
    else:
        text = "♻️ **ሪሳይክል ቢን**\n\nለመመለስ ስሙን ይንኩ፦"
        for cafe in deleted_cafes:
            markup.add(types.InlineKeyboardButton(f"🗑 {cafe.name}", callback_data=f"dev_bin_opt_{cafe.id}"))
    
    
    markup.add(types.InlineKeyboardButton("🔙 ተመለስ", callback_data="dev_back_to_cafes"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("dev_bin_opt_"))
def dev_bin_item_options(call):
    cafe_id = call.data.split('_')[-1]
    cafe = Cafe.objects.get(id=cafe_id)
    markup = types.InlineKeyboardMarkup()
    
    markup.add(types.InlineKeyboardButton("🔄 ወደ ነበረበት መልስ (Restore)", callback_data=f"dev_restore_{cafe_id}"))
    markup.add(types.InlineKeyboardButton("🔥 ለዘላለም ሰርዝ", callback_data=f"dev_hard_del_confirm_{cafe_id}"))
    markup.add(types.InlineKeyboardButton("🔙 ተመለስ", callback_data="dev_recycle_bin"))
    
    bot.edit_message_text(f"🏘 ካፌ፦ **{cafe.name}**\n\nምን ለማድረግ ይፈልጋሉ?", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("dev_restore_"))
def dev_restore_cafe(call):
    cafe_id = call.data.split('_')[-1]
    try:
        cafe = Cafe.objects.get(id=cafe_id)
        cafe.is_deleted = False
        cafe.is_active = True
        cafe.save()
        
        
        CafeOwner.objects.filter(cafe=cafe).update(is_authorized=True)
        
        bot.answer_callback_query(call.id, f"✅ {cafe.name} ተመልሷል!", show_alert=True)
        dev_show_recycle_bin(call)
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ ስህተት፦ {str(e)}")   

@bot.callback_query_handler(func=lambda call: call.data.startswith("dev_hard_del_confirm_"))
def dev_hard_delete_warning(call):
    cafe_id = call.data.split('_')[-1]
    try:
        cafe = Cafe.objects.get(id=cafe_id)
        
        markup = types.InlineKeyboardMarkup()
        
        btn_danger = types.InlineKeyboardButton("⚠️ አዎ፣ እርግጠኛ ነኝ! ለዘላለም ይጥፋ", callback_data=f"dev_PERMANENT_DEL_{cafe_id}")
        btn_cancel = types.InlineKeyboardButton("🔙 አይ፣ ይቆይ (ተመለስ)", callback_data=f"dev_bin_opt_{cafe_id}")
        markup.add(btn_danger)
        markup.add(btn_cancel)
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"🚨 **እጅግ አደገኛ ማስጠንቀቂያ!** 🚨\n\n"
                 f"ካፌ፦ **{cafe.name}**\n\n"
                 f"ይህንን ካፌ ካጠፋኸው፦\n"
                 f"❌ የካፌው ሽያጭ ታሪክ በሙሉ ይጠፋል።\n"
                 f"❌ የካፌው ምግቦችና ዝርዝሮች በሙሉ ይደመሰሳሉ።\n"
                 f"❌ ባለቤቱ ዳግመኛ መግባት አይችልም።\n\n"
                 f"**ይህ ድርጊት በፍጹም ወደ ኋላ ሊመለስ አይችልም!**\n"
                 f"በእርግጥ ለዘላለም እንዲጠፋ ትፈልጋለህ?",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.answer_callback_query(call.id, f"ስህተት፦ {str(e)}")  

@bot.callback_query_handler(func=lambda call: call.data.startswith("dev_PERMANENT_DEL_"))
def dev_execute_permanent_delete(call):
    cafe_id = call.data.split('_')[-1]
    try:
        cafe = Cafe.objects.get(id=cafe_id)
        cafe_name = cafe.name
        
        cafe.delete() 
        
        bot.answer_callback_query(call.id, "💥 ካፌው ለዘላለም ጠፍቷል!", show_alert=True)
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"💥 **'{cafe_name}'** ከነታሪኩ ለዘላለም ከሲስተሙ ተወግዷል።\n\nአሁን በሪሳይክል ቢን ውስጥም አይገኝም።",
            reply_markup=None
        )
        
        import time
        time.sleep(2)
        dev_show_recycle_bin(call)
        
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ ስህተት ተፈጥሯል፦ {str(e)}")                        
bot.infinity_polling()