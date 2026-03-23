import json
import os
import hmac
import hashlib
import requests 
import telebot
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Order, Cafe, CafeOwner


bot = telebot.TeleBot(os.getenv('TELEGRAM_BOT_TOKEN'))
CHAPA_SECRET_KEY = os.getenv('CHAPA_SECRET_KEY')

@csrf_exempt
def chapa_webhook(request):
    if request.method == 'GET':
        return HttpResponse("""
            <html>
                <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>
                        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; text-align: center; padding: 50px; background-color: #f4f7f6; }
                        .card { background: white; padding: 40px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); display: inline-block; max-width: 90%; }
                        h1 { color: #28a745; margin-bottom: 10px; }
                        p { color: #666; font-size: 18px; }
                        .btn { background: #0088cc; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 20px; font-weight: bold; }
                    </style>
                </head>
                <body>
                    <div class="card">
                        <h1>✅ ክፍያዎ ተሳክቷል!</h1>
                        <p>ትዕዛዝዎ በስርዓታችን ተመዝግቧል። የምግብ መቀበያ ኮድዎን በቴሌግራም ቦቱ ልከንልዎታል።</p>
                        <p style="font-size: 14px; color: #999;">አሁን ይህንን ገጽ ዘግተው ወደ ቦቱ መመለስ ይችላሉ።</p>
                        <a href="https://t.me/order6_bot" class="btn">ወደ ቴሌግራም ተመለስ</a>
                    </div>
                </body>
            </html>
        """)

    if request.method == 'POST':
       
        chapa_signature = request.headers.get('x-chapa-signature')
        secret_hash = os.getenv('CHAPA_WEBHOOK_HASH')

        if chapa_signature and secret_hash:
            computed_signature = hmac.new(
                secret_hash.encode('utf-8'),
                request.body,
                hashlib.sha256
            ).hexdigest()

            if chapa_signature != computed_signature:
                print("❌ የዌብሁክ ፊርማ አልገጠመም!")
                return HttpResponse(status=401)
        
        try:
            data = json.loads(request.body)
            tx_ref = data.get('tx_ref') 
        except json.JSONDecodeError:
            return HttpResponse(status=400)

        print(f"🔍 ትራንዛክሽን {tx_ref} እየተጣራ ነው...")
        
        headers = {"Authorization": f"Bearer {CHAPA_SECRET_KEY}"}
        verify_url = f"https://api.chapa.co/v1/transaction/verify/{tx_ref}"
        
        try:
            verify_res = requests.get(verify_url, headers=headers)
            res_data = verify_res.json()

            if res_data.get('status') == 'success':
                
                order = Order.objects.get(id=tx_ref)
                
                if not order.is_paid:
                    order.is_paid = True
                    order.status = 'PAID'
                    order.save()

                    
                    order_items_detail = ""
                    if order.items_json:
                        items_dict = json.loads(order.items_json)
                        for name, qty in items_dict.items():
                            order_items_detail += f"• {name} ({qty} ፍሬ)\n"
                    else:
                        order_items_detail = "ዝርዝር አልተገኘም"

                    
                    item = order.items.first() 
                    if item:
                        cafe = item.cafe
                        cafe.balance += order.vendor_share
                        cafe.save()

                        
                        success_text = (
                            f"✅ **ክፍያዎ ተረጋግጧል!**\n\n"
                            f"📦 **የታዘዙ ምግቦች፦**\n{order_items_detail}\n"
                            f"💰 **ጠቅላላ የተከፈለ፦** {order.total_price} ብር\n"
                            f"🔑 **የመቀበያ ኮድ፦ `{order.pickup_code}`**\n\n"
                            f"ይህንን ኮድ ካፌው ውስጥ በማሳየት ምግብዎን ይረከቡ።"
                        )
                        bot.send_message(order.student.telegram_id, success_text, parse_mode="Markdown")
                        
                        
                        owners = CafeOwner.objects.filter(cafe=cafe)
                        owner_msg = (
                            f"🔔 **አዲስ ሽያጭ ተፈጽሟል!** 🔔\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"👤 **ተማሪ፦** {order.student.full_name}\n"
                            f"📦 **ዝርዝር፦**\n{order_items_detail}\n"
                            f"💰 **ገቢ፦** {order.vendor_share} ብር\n"
                            f"🔑 **ኮድ፦** `{order.pickup_code}`\n"
                            f"━━━━━━━━━━━━━━━━━━━━"
                        )
                        for owner in owners:
                            try:
                                bot.send_message(owner.telegram_id, owner_msg, parse_mode="Markdown")
                            except Exception as e:
                                print(f"ለባለቤቱ መላክ አልተቻለም: {e}")

                return HttpResponse(status=200)

        except Order.DoesNotExist:
            print(f"❌ ስህተት: ትዕዛዝ ቁጥር {tx_ref} አልተገኘም!")
            return HttpResponse(status=404)
        except Exception as e:
            print(f"❌ ስህተት: {str(e)}")
            return HttpResponse(status=500)

    return HttpResponse(status=405)