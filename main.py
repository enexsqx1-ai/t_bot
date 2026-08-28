import os
import re
import json
import httpx
import requests
from dotenv import load_dotenv

import qrcode
from io import BytesIO
import yt_dlp
import asyncio
import os
from datetime import datetime, time
import pytz
from aiohttp import web
from threading import Thread
import zxcvbn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

load_dotenv()

# ── API Anahtarları ───────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
VIRUSTOTAL_API_KEY = os.getenv("VIRUSTOTAL_API_KEY")
RAPIDAPI_KEY      = os.getenv("RAPIDAPI_KEY")
SERPAPI_KEY       = os.getenv("SERPAPI_KEY")
SIGHTENGINE_USER  = os.getenv("SIGHTENGINE_USER", "")
SIGHTENGINE_SECRET = os.getenv("SIGHTENGINE_SECRET", "")
HF_TOKEN          = os.getenv("HF_TOKEN", "")

IG_HOST = "instagram-scraper-20251.p.rapidapi.com"
IG_BASE = f"https://{IG_HOST}"
IG_HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": IG_HOST,
    "Content-Type": "application/json",
}

URL_REGEX = r'(https?://[^\s]+)'

# ── Kullanıcı Durumu ──────────────────────────────────────────────────────────
# user_data["mode"]: None | "link" | "ig_lookup" | "ig_search"
# user_data["ig_search_query"]: son arama sorgusu
# user_data["ig_search_offset"]: sayfalama ofseti

# ═════════════════════════════════════════════════════════════════════════════
# MENÜ
# ═════════════════════════════════════════════════════════════════════════════

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Link Sorgu (Virüs Tarama)", callback_data="menu_link")],
        [InlineKeyboardButton("📸 Instagram Sorgu",            callback_data="menu_ig")],
        [InlineKeyboardButton("📹 Video İndirici (Fligransız)", callback_data="menu_video")],
        [InlineKeyboardButton("🔲 QR Kod Oluştur",             callback_data="menu_qr")],
        [InlineKeyboardButton("📧 E-posta Sızıntı Kontrolü",   callback_data="menu_email")],
        [InlineKeyboardButton("📞 Numara Sorgulama",           callback_data="menu_phone")],
        [InlineKeyboardButton("🤖 AI Görsel Analizi",          callback_data="menu_ai")],
        [InlineKeyboardButton("🚀 Bot Takipçi",                 callback_data="menu_bot_takipci")],
        [InlineKeyboardButton("🔐 Şifre Gücü Ölçer",           callback_data="menu_password")],
        [InlineKeyboardButton("⚙️ Nexus Panel",                callback_data="menu_nexus")],
        [InlineKeyboardButton("ℹ️ Bilgi (Komutlar)",           callback_data="menu_info")]
    ])

def ig_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Kullanıcı adını biliyorum",                callback_data="ig_known")],
        [InlineKeyboardButton("⬅️ Geri",                                    callback_data="back_main")],
    ])

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Global scheduler
scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Istanbul"))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    chat_id = update.message.chat_id

    # Sivilce alarmını kur
    job_id = f"sivilce_{chat_id}"
    if not scheduler.get_job(job_id):
        scheduler.add_job(
            send_sivilce_alarm,
            'cron',
            hour=17,
            minute=0,
            args=[context.bot, chat_id],
            id=job_id
        )

    # Nexus sunucusunu uyandır (her 14 dakikada bir ping)
    if not scheduler.get_job("nexus_keepalive"):
        scheduler.add_job(
            ping_nexus_server,
            'interval',
            minutes=14,
            id="nexus_keepalive"
        )
        
    # Sunucu durmuşsa bile /start yazıldığı anda hemen uyansın diye tek seferlik ping at
    asyncio.create_task(ping_nexus_server())

    hosgeldin = (
        "*Virexa'ya Hoş Geldiniz!* 🤖\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Siber güvenlik, medya indirme ve yapay zeka araçlarıyla dolu asistanınız hazır.\n\n"
        "Tüm özellikleri görmek ve modüllere erişmek için 👉 /menu yazabilirsiniz."
    )
    await update.message.reply_text(
        hosgeldin,
        parse_mode="Markdown"
    )

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👇 Lütfen kullanmak istediğiniz modülü seçin:",
        reply_markup=main_menu_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_link":
        context.user_data["mode"] = "link"
        await query.edit_message_text(
            "🔗 *Virüs Tarama Modülü*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Bu modül ile şüpheli linkleri 70+ güvenlik motorunda taratabilir, "
            "virüsün türünü ve ne anlama geldiğini Türkçe olarak öğrenebilirsiniz.\n\n"
            "📌 *Nasıl Kullanılır?*\n"
            "Sadece linki (URL) bana gönderin, gerisini ben hallederim.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*Örnek Kullanımlar:*\n"
            "`https://google.com` → Güvenli çıkar\n"
            "`https://secure.eicar.org/eicar.com.txt` → Test virüsü tespit edilir\n\n"
            "⬇️ Şimdi taramak istediğiniz linki gönderin:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Ana Menü", callback_data="back_main")]])
        )

    elif data == "menu_ig":
        context.user_data["mode"] = None
        await query.edit_message_text(
            "📸 *Instagram Sorgu Modülü*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Bu modül ile Instagram üzerinde detaylı profil analizi ve arama yapabilirsiniz.\n\n"
            "*Mevcut Komutlar:*\n\n"
            "👤 `/ig @kullaniciadi`\n"
            "_→ Profil fotoğrafı, takipçi, takip edilen, gönderi sayısı, bio_\n\n"
            "👥 `/takipci @kullaniciadi`\n"
            "_→ O hesabın takipçi listesini gösterir (herkese açık hesaplarda)_\n\n"
            "📸 `/gonderiler @kullaniciadi`\n"
            "_→ Son gönderileri, beğeni ve yorum sayılarıyla listeler (açık hesaplarda)_\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Nasıl devam etmek istiyorsunuz? 👇",
            parse_mode="Markdown",
            reply_markup=ig_menu_keyboard()
        )

    elif data == "ig_known":
        context.user_data["mode"] = "ig_lookup"
        await query.edit_message_text(
            "👤 *Kullanıcı Adıyla Profil Sorgulama*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Kullanıcı adını `@` işareti ile veya onsuz yazabilirsiniz.\n\n"
            "*Size göstereceğim bilgiler:*\n"
            "• 🖼️ Profil fotoğrafı\n"
            "• 👤 Tam isim ve kullanıcı adı\n"
            "• 📝 Bio (hakkında yazısı)\n"
            "• 👥 Takipçi sayısı\n"
            "• ➡️ Takip edilen sayısı\n"
            "• 📸 Gönderi sayısı\n"
            "• 🔒 Hesap türü (Gizli / Herkese Açık)\n\n"
            "_Örnek: `messi` veya `@leomessi`_\n\n"
            "⬇️ Kullanıcı adını yazın:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Geri", callback_data="menu_ig")]])
        )

    elif data == "menu_video":
        context.user_data["mode"] = "video"
        await query.edit_message_text(
            "📹 *Video İndirici Modülü*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "TikTok, Instagram Reels veya YouTube videolarını filigransız olarak indirebilirsiniz.\n\n"
            "⬇️ Lütfen indirmek istediğiniz videonun linkini gönderin:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Ana Menü", callback_data="back_main")]])
        )

    elif data == "menu_qr":
        context.user_data["mode"] = "qr"
        await query.edit_message_text(
            "🔲 *QR Kod Modülü*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Bana herhangi bir link veya metin gönderin, size hemen karekodunu (QR) oluşturup resim olarak atayım.\n\n"
            "⬇️ QR'a dönüştürülecek metni/linki yazın:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Ana Menü", callback_data="back_main")]])
        )
        
    elif data == "menu_nexus":
        user_id = update.effective_user.id
        if user_id not in AUTHORIZED_USERS:
            context.user_data["mode"] = "nexus_login"
            await query.edit_message_text(
                "🔒 *Nexus Paneli Kilitli*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Lütfen erişim şifresini mesaj olarak yazın:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ İptal", callback_data="back_main")]])
            )
            return

        context.user_data["mode"] = None
        await query.edit_message_text(
            "⚙️ *Nexus Yönetim Paneli*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Kullanılabilir Komutlar:\n"
            "🌐 `/nexus` - Sunucudaki anlık kişi sayısını gösterir.\n"
            "🔨 `/ban <İsim veya IP>` - Belirtilen kullanıcıyı sunucudan atar.\n",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Ana Menü", callback_data="back_main")]])
        )

    elif data == "menu_email":
        context.user_data["mode"] = "email"
        await query.edit_message_text(
            "📧 *E-posta Sızıntı Kontrolü*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Girdiğiniz e-posta adresinin geçmişteki veri sızıntılarında (data breach) yer alıp almadığını kontrol edeceğim.\n\n"
            "⬇️ Sorgulamak istediğiniz e-posta adresini gönderin:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Ana Menü", callback_data="back_main")]])
        )

    elif data == "menu_phone":
        context.user_data["mode"] = "phone"
        await query.edit_message_text(
            "📞 *Telegram Numara Sorgulama*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Bana uluslararası formatta (+90 ile başlayan) bir telefon numarası gönderin, "
            "bu numaranın kime ait olduğunu ve Telegram kullanıp kullanmadığını analiz edeyim.\n\n"
            "⬇️ Örnek: `+905551234567`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Ana Menü", callback_data="back_main")]])
        )

    elif data == "menu_ai":
        context.user_data["mode"] = "ai_detect"
        await query.edit_message_text(
            "🤖 *Yapay Zeka (AI) Görsel Analizi*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Bana bir fotoğraf gönderin, size bunun Yapay Zeka (AI) ile üretilip üretilmediğini analiz edeyim.\n\n"
            "⬇️ Analiz edilecek fotoğrafı gönderin (Dosya olarak değil, fotoğraf olarak):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Ana Menü", callback_data="back_main")]])
        )

    elif data == "menu_password":
        context.user_data["mode"] = "password"
        await query.edit_message_text(
            "🔐 *Şifre Gücü Ölçer*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Bana bir şifre gönderin, sizin için ne kadar sürede kırılabileceğini (çevrimdışı saldırı vb.) hesaplayıp puanlayayım.\n\n"
            "⬇️ Gücünü ölçmek istediğiniz şifreyi gönderin:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Ana Menü", callback_data="back_main")]])
        )

    elif data == "menu_bot_takipci":
        await query.edit_message_text(
            "🚀 *Bot Takipçi Gönderimi*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Lütfen işlem yapmak istediğiniz platformu seçin:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📸 Instagram", callback_data="bot_takipci_ig")],
                [InlineKeyboardButton("🎵 TikTok", callback_data="bot_takipci_tt")],
                [InlineKeyboardButton("⬅️ Ana Menü", callback_data="back_main")]
            ])
        )

    elif data == "bot_takipci_ig":
        context.user_data["mode"] = "fake_bot_ig"
        await query.edit_message_text(
            "📸 *Instagram Bot Takipçi*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Kullanıcı adınızı girmek için lütfen `/ig kullanıcıadı` komutunu kullanın.\n"
            "Örnek: `/ig messi`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Geri", callback_data="menu_bot_takipci")]])
        )

    elif data == "bot_takipci_tt":
        context.user_data["mode"] = "fake_bot_tt"
        await query.edit_message_text(
            "🎵 *TikTok Bot Takipçi*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Kullanıcı adınızı girmek için lütfen `/tt kullanıcıadı` komutunu kullanın.\n"
            "Örnek: `/tt charlidamelio`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Geri", callback_data="menu_bot_takipci")]])
        )

    elif data == "fake_hack_button":
        await query.answer("Hata: Hedef cihazın güvenlik duvarı (Firewall) bu işlemi engelledi.", show_alert=True)

    elif data == "menu_info":
        info_text = (
            "ℹ️ *Virexa Komut Bilgi Sistemi*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔹 `/start` - Botu başlatır ve karşılama mesajını gösterir.\n"
            "🔹 `/menu` - Ana menüyü açarak tüm araçlara (Virüs tarama, Video, Şifre vb.) erişmenizi sağlar.\n"
            "🔹 `/ig @kullaniciadi` - Instagram profil bilgilerini getirir.\n"
            "🔹 `/takipci @kullaniciadi` - Bir Instagram hesabının takipçi listesini (açıksa) gösterir.\n"
            "🔹 `/gonderiler @kullaniciadi` - Hesabın gönderilerini listeler.\n"
            "🔹 `/devam` - Uzun listelerde (takipçi gibi) sonraki sayfayı getirir.\n"
            "🔹 `/reset` - Sohbet ekranındaki eski mesajları temizler ve botu sıfırlar.\n"
            "🔹 `/ertele` - Günlük hatırlatmaları erteler.\n"
            "🔹 `/nexus` - Nexus sunucusunun anlık durumunu (online kişi vb.) gösterir.\n"
            "🔹 `/ban <ip>` - Nexus sunucusundan bir kişiyi engeller (Sadece Admin).\n"
            "🔹 `/unban <ip>` - Nexus sunucusundan engeli kaldırır (Sadece Admin)."
        )
        await query.edit_message_text(
            info_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Ana Menü", callback_data="back_main")]])
        )

    elif data == "back_main":
        context.user_data.clear()
        await query.edit_message_text(
            "👋 Ana menüye döndünüz. Ne yapmak istiyorsunuz?",
            reply_markup=main_menu_keyboard()
        )

# ═════════════════════════════════════════════════════════════════════════════
# MESAJ YÖNLENDİRİCİ
# ═════════════════════════════════════════════════════════════════════════════

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")

    if mode == "link":
        await handle_link_scan(update, context)
    elif mode == "ig_lookup":
        await handle_ig_lookup(update, context)
    elif mode == "video":
        await handle_video_download(update, context)
    elif mode == "qr":
        await handle_qr_generate(update, context)
    elif mode == "email":
        await handle_email_check(update, context)
    elif mode == "phone":
        await handle_phone_lookup(update, context)
    elif mode == "password":
        await handle_password_check(update, context)
    elif mode == "ai_detect":
        await handle_ai_detect(update, context)
    elif mode == "nexus_login":
        if update.message.text and update.message.text.strip() == NEXUS_PASSWORD:
            AUTHORIZED_USERS.add(update.effective_user.id)
            context.user_data["mode"] = None
            await update.message.reply_text("✅ *Şifre Doğru!*\nNexus Paneline erişim izni verildi. Menüyü görmek için /nexus yazabilir veya ana menüden butona tıklayabilirsiniz.", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Yanlış şifre. Tekrar deneyin veya /start ile iptal edin.")
    else:
        # Mod yoksa ana menüyü göster
        if update.message.text:
            await update.message.reply_text(
                "👋 Ne yapmak istiyorsunuz?",
                reply_markup=main_menu_keyboard()
            )

# ═════════════════════════════════════════════════════════════════════════════
# YENİ MODÜLLER (E-POSTA, ŞİFRE, AI)
# ═════════════════════════════════════════════════════════════════════════════

async def handle_email_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text: return
    email = update.message.text.strip()
    wait_msg = await update.message.reply_text("⏳ E-posta veri tabanlarında aranıyor...")
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"https://api.xposedornot.com/v1/check-email/{email}")
            if resp.status_code == 404:
                await wait_msg.edit_text("✅ *Harika!* Bu e-posta hiçbir veri sızıntısında bulunamadı. Tamamen güvenli.", parse_mode="Markdown")
            elif resp.status_code == 200:
                data = resp.json()
                breaches = data.get("breaches", [[]])[0]
                if breaches:
                    breach_list = "\n".join([f"🔴 {b}" for b in breaches])
                    await wait_msg.edit_text(
                        f"🚨 *TEHLİKE:* Bu e-posta {len(breaches)} farklı veri sızıntısında bulundu!\n\n"
                        f"*Sızdırılan Yerler:*\n{breach_list}\n\n"
                        "Lütfen bu e-posta ile kullandığınız şifreleri acilen değiştirin!",
                        parse_mode="Markdown"
                    )
                else:
                    await wait_msg.edit_text("✅ Bu e-posta adresinde sızıntı bulunamadı.", parse_mode="Markdown")
            else:
                await wait_msg.edit_text("❌ Sorgulama sırasında bir hata oluştu.")
    except Exception as e:
         await wait_msg.edit_text(f"❌ Bağlantı hatası: {str(e)[:50]}")
    context.user_data.clear()

async def handle_password_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text: return
    password = update.message.text.strip()
    wait_msg = await update.message.reply_text("⏳ Şifre gücü hesaplanıyor...")
    
    try:
        # zxcvbn şifre analizi
        result = zxcvbn.zxcvbn(password)
        score = result['score'] # 0-4
        raw_crack_time = result['crack_times_display']['offline_slow_hashing_1e4_per_second']
        raw_feedback = result['feedback']['warning']
        raw_suggestions = "\n".join(result['feedback']['suggestions'])
        
        # Zaman sözcüklerini Türkçeye çevir
        def translate_time(t):
            tr = t
            tr = tr.replace("less than a second", "1 saniyeden az")
            tr = tr.replace("seconds", "saniye").replace("second", "saniye")
            tr = tr.replace("minutes", "dakika").replace("minute", "dakika")
            tr = tr.replace("hours", "saat").replace("hour", "saat")
            tr = tr.replace("days", "gün").replace("day", "gün")
            tr = tr.replace("months", "ay").replace("month", "ay")
            tr = tr.replace("years", "yıl").replace("year", "yıl")
            tr = tr.replace("centuries", "yüzyıl").replace("century", "yüzyıl")
            tr = tr.replace("weeks", "hafta").replace("week", "hafta")
            return tr
        
        crack_time = translate_time(raw_crack_time)
        
        # Geri bildirim çevirisi
        feedback_tr = {
            "Straight rows of keys are easy to guess": "Düz tuş sıraları tahmin edilmesi kolay",
            "Short keyboard patterns are easy to guess": "Kısa klavye kalıpları kolay tahmin edilir",
            "Use a longer keyboard pattern with more turns": "Daha fazla dönüşlü uzun bir klavye deseni kullan",
            "Repeats like \"aaa\" are easy to guess": "'aaa' gibi tekrarlar kolay tahmin edilir",
            "Repeats like \"abcabc\" are only slightly harder to guess than \"abc\"": "'abcabc' gibi tekrarlar sadece biraz daha zor",
            "Sequences like abc or 6543 are easy to guess": "abc veya 6543 gibi diziler kolay tahmin edilir",
            "Recent years are easy to guess": "Son yıllar kolay tahmin edilir",
            "Dates are often easy to guess": "Tarihler kolay tahmin edilir",
            "This is a top-10 common password": "Bu, en yaygın 10 şifreden biri",
            "This is a top-100 common password": "Bu, en yaygın 100 şifreden biri",
            "This is a very common password": "Bu çok yaygın bir şifre",
            "This is similar to a commonly used password": "Bu yaygın bir şifreye benziyor",
            "A word by itself is easy to guess": "Tek bir kelime kolay tahmin edilir",
            "Names and surnames by themselves are easy to guess": "Tek başına isimler kolay tahmin edilir",
            "Common names and surnames are easy to guess": "Yaygın isimler kolay tahmin edilir",
        }
        suggestions_tr = {
            "Use a few words, avoid common phrases": "Birkaç kelime kullan, yaygın ifadelerden kaçın",
            "No need for symbols, digits, or uppercase letters": "Sembol, rakam veya büyük harf gerekmez",
            "Add another word or two. Uncommon words are better.": "Bir-iki kelime daha ekle. Nadir kelimeler daha iyidir.",
            "Capitalization doesn't help very much": "Büyük harfler pek yardımcı olmaz",
            "All-uppercase is almost as easy to guess as all-lowercase": "Tamamen büyük harfler, küçük harfler kadar kolay",
            "Reversed words aren't much harder to guess": "Ters çevrilmiş kelimeler pek zor değil",
            "Predictable substitutions like '@' instead of 'a' don't help very much": "'@' yerine 'a' gibi tahmin edilebilir değişimler pek yardımcı olmaz",
            "Use a longer keyboard pattern with more turns": "Daha fazla dönüşlü uzun bir klavye deseni kullan",
            "Avoid repeated words and characters": "Tekrar eden kelime ve karakterlerden kaçın",
            "Avoid sequences": "Dizilerden kaçın",
            "Avoid recent years": "Son yıllardan kaçın",
            "Avoid years that are associated with you": "Sizinle ilişkili yıllardan kaçın",
            "Avoid dates and years that are associated with you": "Sizinle ilişkili tarih ve yıllardan kaçın",
        }

        feedback = feedback_tr.get(raw_feedback, raw_feedback)
        suggestions_list = raw_suggestions.split("\n") if raw_suggestions else []
        suggestions = "\n".join(suggestions_tr.get(s, s) for s in suggestions_list if s)

        score_stars = "⭐" * score + "❌" * (4 - score)

        msg = (
            f"🔐 *Şifre Analiz Sonucu*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💪 *Güç Puanı:* {score}/4 {score_stars}\n"
            f"⏱️ *Tahmini Kırılma Süresi:* {crack_time}\n"
        )
        if feedback:
            msg += f"\n⚠️ *Uyarı:* {feedback}\n"
        if suggestions:
            msg += f"💡 *Öneriler:*\n{suggestions}\n"

        await wait_msg.edit_text(msg, parse_mode="Markdown")
    except Exception as e:
        await wait_msg.edit_text(f"❌ Hesaplama hatası: {str(e)[:50]}")

    context.user_data.clear()


async def handle_ai_detect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("❌ Lütfen analiz edilecek bir fotoğraf gönderin.")
        return

    wait_msg = await update.message.reply_text("🔬 Üçlü analiz motoru çalışıyor...\n_(Model + EXIF + Görsel Analizi)_", parse_mode="Markdown")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        # Telegram'dan fotoğrafı indir
        async with httpx.AsyncClient(timeout=20.0) as client:
            photo_resp = await client.get(file.file_path)
            photo_bytes = photo_resp.content

        from PIL import Image, ImageFilter
        import io, numpy as np

        img = Image.open(io.BytesIO(photo_bytes))

        # ─── ANALİZ 1: HuggingFace AI Tespit Modeli (Ağırlık: %50) ───────────
        hf_ai_score = 50.0  # varsayılan: belirsiz
        hf_status = "⚠️ Model yanıt vermedi"

        def call_hf():
            return requests.post(
                "https://router.huggingface.co/hf-inference/models/umm-maybe/AI-image-detector",
                headers={"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/octet-stream"},
                data=photo_bytes,
                timeout=30
            )

        try:
            resp = await asyncio.to_thread(call_hf)
            if resp.status_code == 200:
                for item in resp.json():
                    if item['label'] == 'artificial':
                        hf_ai_score = round(item['score'] * 100, 1)
                hf_status = f"✅ Model skoru: %{hf_ai_score}"
            elif resp.status_code == 503:
                hf_status = "⏳ Model uyku modunda (atlandı)"
            else:
                hf_status = f"⚠️ Model hatası (kod {resp.status_code})"
        except Exception:
            hf_status = "⚠️ Model bağlantı hatası (atlandı)"

        # ─── ANALİZ 2: EXIF Metadata (Ağırlık: %25) ──────────────────────────
        # Gerçek fotoğraflar kamera bilgisi (Make, Model) içerir. AI görseller içermez.
        exif_ai_score = 0.0
        exif_details = []
        exif_status = ""

        try:
            exif = img.getexif()
            exif_tags = {
                271: "Kamera Markası",   # Make
                272: "Kamera Modeli",    # Model
                306: "Çekim Tarihi",     # DateTime
                36867: "Orijinal Tarih", # DateTimeOriginal
                34853: "GPS Verisi",     # GPS
                33434: "Poz Süresi",     # ExposureTime
                37386: "Odak Uzunluğu", # FocalLength
            }
            found = {}
            for tag_id, tag_name in exif_tags.items():
                val = exif.get(tag_id)
                if val:
                    found[tag_name] = val

            if len(found) == 0:
                exif_ai_score = 80.0
                exif_status = "🔴 Hiç kamera verisi yok (AI işareti)"
                exif_details = ["Kamera bilgisi, tarih, GPS verisi bulunamadı"]
            elif len(found) <= 2:
                exif_ai_score = 50.0
                exif_status = "🟡 Çok az kamera verisi var"
                exif_details = [f"{k}: {str(v)[:30]}" for k,v in list(found.items())[:3]]
            else:
                exif_ai_score = 5.0
                exif_status = "🟢 Zengin kamera verisi var (Gerçek işareti)"
                exif_details = [f"{k}: {str(v)[:30]}" for k,v in list(found.items())[:3]]
        except Exception:
            exif_ai_score = 40.0
            exif_status = "⚠️ EXIF okunamadı"

        # ─── ANALİZ 3: Görsel Gürültü & Renk Analizi (Ağırlık: %25) ─────────
        # AI görseller genellikle: 1) Aşırı yumuşak/mükemmel 2) Renk gradyanları çok düzgün
        noise_ai_score = 0.0
        noise_status = ""

        try:
            # Görseli gri tona çevir ve gürültüyü ölç
            gray = img.convert("L").resize((256, 256))
            arr = np.array(gray, dtype=np.float32)

            # Laplacian filtre ile keskinlik/gürültü ölçümü
            sharp = gray.filter(ImageFilter.FIND_EDGES)
            sharp_arr = np.array(sharp, dtype=np.float32)
            noise_std = sharp_arr.std()

            # Renk kanalları arası korelasyon — AI'da çok mükemmel olur
            if img.mode in ('RGB', 'RGBA'):
                rgb = img.convert("RGB").resize((128, 128))
                r, g, b = rgb.split()
                r_arr = np.array(r, dtype=np.float32).flatten()
                g_arr = np.array(g, dtype=np.float32).flatten()
                b_arr = np.array(b, dtype=np.float32).flatten()
                rg_corr = np.corrcoef(r_arr, g_arr)[0,1]
                rb_corr = np.corrcoef(r_arr, b_arr)[0,1]
                avg_corr = (rg_corr + rb_corr) / 2
            else:
                avg_corr = 0.5

            # Düşük gürültü + yüksek kanal korelasyonu = AI ihtimali yüksek
            if noise_std < 10:
                noise_ai_score += 40
                noise_status = "🔴 Çok az gürültü (aşırı mükemmel görsel)"
            elif noise_std < 20:
                noise_ai_score += 20
                noise_status = "🟡 Az gürültü"
            else:
                noise_status = "🟢 Normal gürültü seviyesi"

            if avg_corr > 0.97:
                noise_ai_score += 40
                noise_status += " + 🔴 Renk kanalları çok mükemmel"
            elif avg_corr > 0.92:
                noise_ai_score += 15
                noise_status += " + 🟡 Renk hafif mükemmel"
            else:
                noise_status += " + 🟢 Doğal renk dağılımı"

            noise_ai_score = min(noise_ai_score, 100)

        except Exception as e:
            noise_ai_score = 30.0
            noise_status = f"⚠️ Analiz hatası: {str(e)[:30]}"

        # ─── SONUÇ: Ağırlıklı Ortalama ────────────────────────────────────────
        # HF modeli %50, EXIF %25, Gürültü analizi %25
        final_ai = round((hf_ai_score * 0.50) + (exif_ai_score * 0.25) + (noise_ai_score * 0.25), 1)
        final_human = round(100 - final_ai, 1)

        if final_ai >= 55:
            verdict_emoji = "🤖"
            verdict_tr = "YAPAY ZEKA (AI) ÜRETİM"
            verdict_en = "AI GENERATED"
            desc_tr = "Bu görsel büyük ihtimalle bir yapay zeka tarafından üretilmiştir."
            desc_en = "This image was most likely generated by an AI."
            bar = "🔴" * round(final_ai / 10) + "⬜" * (10 - round(final_ai / 10))
        elif final_ai >= 40:
            verdict_emoji = "🟡"
            verdict_tr = "BELİRSİZ / KARIŞIK SİNYALLER"
            verdict_en = "UNCERTAIN / MIXED SIGNALS"
            desc_tr = "Analiz kesin bir karar veremedi. Görsel gerçek de olabilir AI de."
            desc_en = "The analysis could not reach a definitive conclusion."
            bar = "🟡" * round(final_ai / 10) + "⬜" * (10 - round(final_ai / 10))
        else:
            verdict_emoji = "📸"
            verdict_tr = "GERÇEK / İNSAN YAPIMI"
            verdict_en = "REAL / HUMAN MADE"
            desc_tr = "Bu görsel büyük ihtimalle gerçek bir fotoğraftır."
            desc_en = "This image appears to be a real, human-taken photograph."
            bar = "🟢" * round(final_human / 10) + "⬜" * (10 - round(final_human / 10))

        msg = (
            f"{verdict_emoji} *{verdict_tr}*\n"
            f"_{verdict_en}_\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 AI: *%{final_ai}*  |  📸 Gerçek: *%{final_human}*\n"
            f"{bar}\n\n"
            f"📊 *Analiz Detayları:*\n"
            f"  🧠 AI Modeli: {hf_status}\n"
            f"  📷 EXIF: {exif_status}\n"
            f"  🔬 Görsel: {noise_status}\n\n"
            f"🇹🇷 _{desc_tr}_\n"
            f"🇬🇧 _{desc_en}_"
        )
        await wait_msg.edit_text(msg, parse_mode="Markdown")

    except Exception as e:
        await wait_msg.edit_text(f"❌ Beklenmedik hata: {str(e)[:80]}")
    context.user_data.clear()




# ═════════════════════════════════════════════════════════════════════════════
# VİRÜS TARAMA
# ═════════════════════════════════════════════════════════════════════════════

async def handle_link_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    urls = re.findall(URL_REGEX, text)
    if not urls:
        # Modu SIFIRLAMADAN sadece uyar, kullanıcı tekrar link gönderebilsin
        await update.message.reply_text(
            "❌ Geçerli bir link bulamadım.\n"
            "Lütfen `http://` veya `https://` ile başlayan bir link gönderin.\n\n"
            "💡 _Örnek: https://google.com_",
            parse_mode="Markdown"
        )
        return

    url = urls[0]
    wait_msg = await update.message.reply_text(
        "⏳ Linkiniz 70+ güvenlik sisteminde taranıyor... *(30-40 sn sürebilir)*",
        parse_mode="Markdown"
    )
    result = await check_url_with_virustotal(url)
    context.user_data["mode"] = None

    if "error" in result:
        await wait_msg.edit_text(f"❌ Hata: {result['error']}")
    else:
        report = generate_turkish_report(result["stats"], result["results"], url)
        await wait_msg.edit_text(report, parse_mode="Markdown")

    # Tekrar menü sun
    await update.message.reply_text(
        "🔄 Başka bir işlem yapmak ister misiniz?",
        reply_markup=main_menu_keyboard()
    )

async def check_url_with_virustotal(url: str) -> dict:
    headers = {
        "accept": "application/json",
        "x-apikey": VIRUSTOTAL_API_KEY,
        "content-type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post("https://www.virustotal.com/api/v3/urls", headers=headers, data={"url": url})
        if r.status_code != 200:
            return {"error": f"API Hatası (Kod: {r.status_code})"}
        analysis_id = r.json().get("data", {}).get("id")
        if not analysis_id:
            return {"error": "Analiz kimliği alınamadı."}

        analysis_url = f"https://www.virustotal.com/api/v3/analyses/{analysis_id}"
        for _ in range(10):
            await asyncio.sleep(3)
            r2 = await client.get(analysis_url, headers=headers)
            if r2.status_code != 200:
                continue
            data = r2.json()
            if data.get("data", {}).get("attributes", {}).get("status") == "completed":
                attrs = data["data"]["attributes"]
                return {"stats": attrs.get("stats", {}), "results": attrs.get("results", {})}
    return {"error": "Analiz çok uzun sürdü, lütfen tekrar deneyin."}

def categorize_threat(result_name: str) -> str:
    name = result_name.lower()
    if "phishing" in name:        return "Oltalama (Phishing)"
    if "trojan" in name:          return "Truva Atı (Trojan)"
    if "ransomware" in name:      return "Fidye Yazılımı (Ransomware)"
    if "malware" in name:         return "Zararlı Yazılım (Malware)"
    if "spyware" in name:         return "Casus Yazılım (Spyware)"
    if "adware" in name:          return "Reklam Yazılımı (Adware)"
    if "worm" in name:            return "Solucan (Worm)"
    if "botnet" in name:          return "Botnet"
    if "spam" in name:            return "Spam"
    if "eicar" in name:           return "Test Virüsü (EICAR)"
    if "exploit" in name:         return "Açık İstismarı (Exploit)"
    if "backdoor" in name:        return "Arka Kapı (Backdoor)"
    if "miner" in name:           return "Kripto Madencisi"
    if "scam" in name:            return "Dolandırıcılık (Scam)"
    if "riskware" in name:        return "Riskli Yazılım"
    short = result_name[:35]
    return f"Zararlı İçerik ({short})" if result_name else "Zararlı İçerik"

THREAT_DESC = {
    "Oltalama (Phishing)":       "Bu site banka/sosyal medya gibi güvenilir yerleri taklit ederek *şifrenizi veya kredi kartı bilgilerinizi çalmaya* çalışıyor. Hiçbir bilgi girmeyin!",
    "Truva Atı (Trojan)":        "Cihazınıza *Truva Atı* bulaştırabilir. Kendini gizleyerek bilgilerinizi çalar veya uzaktan erişim sağlar.",
    "Fidye Yazılımı (Ransomware)":"Dosyalarınızı *şifreleyerek para* isteyebilir. Son derece tehlikeli!",
    "Zararlı Yazılım (Malware)": "Cihazınıza *zararlı yazılım* bulaştırabilir, dosyalarınıza zarar verir.",
    "Casus Yazılım (Spyware)":   "*Tuş vuruşlarınızı ve parolalarınızı* gizlice kaydeder.",
    "Reklam Yazılımı (Adware)":  "Tarayıcınıza *sürekli açılan reklam* yazılımı yükler.",
    "Solucan (Worm)":            "Kendiliğinden çoğalarak *ağdaki diğer cihazlara yayılır.*",
    "Botnet":                    "Cihazınızı farkınızda olmadan *başkalarına saldırmak için kullanır.*",
    "Spam":                      "Dolandırıcılık veya *istenmeyen içerik* sitesi.",
    "Test Virüsü (EICAR)":       "Gerçek bir tehlike değil; güvenlik sistemlerini *test etmek için kullanılan* özel bir dosya.",
    "Açık İstismarı (Exploit)":  "Tarayıcı açıklarını kullanarak *izinsiz kod çalıştırabilir.*",
    "Arka Kapı (Backdoor)":      "Saldırganların cihazınıza *istedikleri zaman gizlice erişmesini* sağlar.",
    "Kripto Madencisi":          "Cihazınızı *gizli kripto para madenciliği* için kullanır, cihazınız yavaşlar.",
    "Dolandırıcılık (Scam)":     "Sahte ödül/para vaatleriyle *sizi kandırmaya çalışan* site.",
    "Riskli Yazılım":            "Yasal görünse de *gizlice istenmeyen işlemler* yapabilir.",
}

def generate_turkish_report(stats: dict, results: dict, url: str) -> str:
    malicious  = stats.get("malicious", 0)
    suspicious = stats.get("suspicious", 0)
    harmless   = stats.get("harmless", 0)
    undetected = stats.get("undetected", 0)
    total      = malicious + suspicious + harmless + undetected

    report = f"🔍 *Link Taraması Tamamlandı*\n`{url}`\n\n"

    if malicious == 0 and suspicious == 0:
        report += f"✅ *SONUÇ: GÜVENLİ*\n"
        report += f"Taranan {total} sistemin hiçbiri tehlike bulmadı. Gönül rahatlığıyla tıklayabilirsiniz."
        return report

    report += f"⚠️ *SONUÇ: TEHLİKELİ OLABİLİR!*\n"
    report += f"{total} sistemden *{malicious} zararlı*, *{suspicious} şüpheli* buldu!\n\n"

    threat_types = {}
    detected = []
    for engine, details in results.items():
        if details.get("category") in ["malicious", "suspicious"]:
            rname = str(details.get("result", "")).strip()
            if rname and rname.lower() not in ["clean", "unrated", "-", ""]:
                cat = categorize_threat(rname)
                threat_types[cat] = threat_types.get(cat, 0) + 1
                detected.append((engine, rname))

    if threat_types:
        report += "🦠 *Tespit Edilen Tehdit Türleri:*\n"
        sorted_t = sorted(threat_types.items(), key=lambda x: x[1], reverse=True)
        for t, c in sorted_t:
            report += f"  • {t} — {c} sistem\n"
        report += "\n"
        top = sorted_t[0][0]
        desc = THREAT_DESC.get(top)
        if desc:
            report += f"💡 *Ne Anlama Geliyor?*\n{desc}\n\n"
    else:
        report += "🦠 Bu link zararlı işaretlendi ancak tür belirlenemedi.\n\n"

    if detected:
        report += "🛡️ *Tespit Eden Sistemler (ilk 5):*\n"
        for eng, rn in detected[:5]:
            report += f"  • {eng}: `{rn}`\n"
        report += "\n"

    report += "⛔ *TAVSİYE:* Bu linke *TIKLAMAMANIZI* şiddetle öneririz."
    return report

# ═════════════════════════════════════════════════════════════════════════════
# INSTAGRAM — PROFİL SORGU
# ═════════════════════════════════════════════════════════════════════════════

async def ig_fetch_user(username: str) -> dict:
    username = username.lstrip("@").strip()
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{IG_BASE}/userinfo/",
            headers=IG_HEADERS,
            params={"username_or_id": username, "id": "instagram"}
        )
        if r.status_code == 403:
            return {"error": "403_sub"}
        if r.status_code == 404:
            return {"error": "404_notfound"}
        if r.status_code != 200:
            return {"error": f"API Hatası (Kod: {r.status_code})"}
        return r.json()

async def ig_fetch_followers(username: str) -> dict:
    username = username.lstrip("@").strip()
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{IG_BASE}/userfollowers/",
            headers=IG_HEADERS,
            params={"username_or_id": username, "id": "instagram"}
        )
        if r.status_code == 403:
            return {"error": "403_sub"}
        if r.status_code != 200:
            return {"error": f"API Hatası (Kod: {r.status_code})"}
        return r.json()

async def ig_fetch_posts(username: str) -> dict:
    username = username.lstrip("@").strip()
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{IG_BASE}/userposts/",
            headers=IG_HEADERS,
            params={"username_or_id": username, "id": "instagram"}
        )
        if r.status_code == 403:
            return {"error": "403_sub"}
        if r.status_code != 200:
            return {"error": f"API Hatası (Kod: {r.status_code})"}
        return r.json()

def format_number(n) -> str:
    try:
        n = int(n)
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)
    except:
        return str(n)

async def handle_ig_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip().lstrip("@")
    wait_msg = await update.message.reply_text(f"⏳ *@{username}* profili sorgulanıyor...", parse_mode="Markdown")

    data = await ig_fetch_user(username)
    context.user_data["mode"] = None

    if "error" in data:
        err = data["error"]
        if err == "403_sub":
            msg = (
                "❌ *RapidAPI Abonelik Hatası*\n\n"
                "Bu hatayı çözmek için şu adımları izleyin:\n\n"
                "1. [rapidapi.com](https://rapidapi.com) sitesine gidin\n"
                "2. Hesabınıza giriş yapın\n"
                "3. `Instagram Scraper 2025` API'sini bulun\n"
                "4. *\"Subscribe to Test\"* butonuna tıklayın\n"
                "5. *Free plan*'ı seçin (0$/ay)\n\n"
                "Abonelik onaylandıktan sonra tekrar deneyin."
            )
        elif err == "404_notfound":
            msg = f"❌ *@{username}* kullanıcısı Instagram'da bulunamadı.\nKullanıcı adını kontrol edin."
        else:
            msg = f"❌ Hata: {err}"
        await wait_msg.edit_text(msg, parse_mode="Markdown")
        await update.message.reply_text("🔄 Başka bir işlem?", reply_markup=main_menu_keyboard())
        return

    # API'nin döndürdüğü yapıyı esnek işle
    user = data.get("data", data)
    if isinstance(user, list):
        user = user[0] if user else {}

    full_name   = user.get("full_name") or user.get("fullName") or "—"
    uname       = user.get("username") or username
    bio         = user.get("biography") or user.get("bio") or "—"
    followers   = user.get("follower_count") or user.get("followers") or user.get("edge_followed_by", {}).get("count", 0)
    following   = user.get("following_count") or user.get("following") or user.get("edge_follow", {}).get("count", 0)
    post_count  = user.get("media_count") or user.get("posts") or user.get("edge_owner_to_timeline_media", {}).get("count", 0)
    is_private  = user.get("is_private", False)
    is_verified = user.get("is_verified", False)
    profile_pic = user.get("profile_pic_url_hd") or user.get("profile_pic_url") or user.get("profilePicUrl") or ""
    category    = user.get("category_name") or user.get("category") or ""

    lock  = "🔒 Gizli Hesap" if is_private else "🌍 Herkese Açık Hesap"
    tick  = " ✅ Doğrulanmış" if is_verified else ""
    cat   = f"\n📂 *Kategori:* {category}" if category else ""
    bio_s = bio[:200] + "..." if len(bio) > 200 else bio

    report = (
        f"📸 *Instagram Profil Raporu*\n\n"
        f"👤 *İsim:* {full_name}{tick}\n"
        f"🔗 *Kullanıcı Adı:* @{uname}\n"
        f"🔗 *Profil Linki:* instagram.com/{uname}\n"
        f"{lock}{cat}\n\n"
        f"📊 *İstatistikler:*\n"
        f"  • 👥 Takipçi: *{format_number(followers)}*\n"
        f"  • ➡️ Takip Edilen: *{format_number(following)}*\n"
        f"  • 📸 Gönderi: *{format_number(post_count)}*\n\n"
        f"📝 *Bio:*\n_{bio_s}_\n\n"
    )

    if is_private:
        report += "🔒 Bu hesap gizli olduğu için gönderiler ve takipçiler görüntülenemiyor."
    else:
        report += (
            f"📌 Gönderi listesi için: /gonderiler @{uname}\n"
            f"👥 Takipçi listesi için: /takipci @{uname}"
        )

    await wait_msg.delete()

    fake_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💀 Hesaba Sızılsın Mı?", callback_data="fake_hack_button")]
    ])

    # Profil fotoğrafı varsa fotoğrafla birlikte gönder
    if profile_pic:
        try:
            await update.message.reply_photo(photo=profile_pic, caption=report, parse_mode="Markdown", reply_markup=fake_keyboard)
        except Exception:
            await update.message.reply_text(report, parse_mode="Markdown", reply_markup=fake_keyboard)
    else:
        await update.message.reply_text(report, parse_mode="Markdown", reply_markup=fake_keyboard)

    await update.message.reply_text("🔄 Başka bir işlem?", reply_markup=main_menu_keyboard())


# ═════════════════════════════════════════════════════════════════════════════
# INSTAGRAM — TAKİPÇİ LİSTESİ
# ═════════════════════════════════════════════════════════════════════════════

async def cmd_takipci(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Kullanım: /takipci @kullaniciadi")
        return
    username = args[0].lstrip("@")
    wait_msg = await update.message.reply_text(f"⏳ *@{username}* takipçileri yükleniyor...", parse_mode="Markdown")
    data = await ig_fetch_followers(username)

    if "error" in data:
        await wait_msg.edit_text(f"❌ Hata: {data['error']}")
        return

    followers_list = data.get("data", data)
    if isinstance(followers_list, dict):
        followers_list = followers_list.get("users") or followers_list.get("followers") or followers_list.get("items") or []

    if not followers_list:
        await wait_msg.edit_text("❌ Takipçi listesi alınamadı (hesap gizli veya API hatası).")
        return

    text = f"👥 *@{username}* Takipçileri (ilk {min(20, len(followers_list))}):\n\n"
    for i, f in enumerate(followers_list[:20], 1):
        uname = f.get("username") or f.get("user", {}).get("username") or "?"
        fname = f.get("full_name") or f.get("fullName") or ""
        verified = " ✅" if f.get("is_verified") else ""
        text += f"{i}. @{uname}{verified}"
        if fname:
            text += f" _{fname}_"
        text += "\n"

    # Devam komutu için verileri kaydet
    context.user_data["followers_list"] = followers_list
    context.user_data["followers_offset"] = 20
    context.user_data["followers_username"] = username

    if len(followers_list) > 20:
        text += "\n🔄 *Sonraki 20 kişi için:* `/devam`"

    await wait_msg.edit_text(text, parse_mode="Markdown")

async def cmd_devam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    followers_list = context.user_data.get("followers_list", [])
    offset = context.user_data.get("followers_offset", 0)
    username = context.user_data.get("followers_username", "?")

    if not followers_list or offset >= len(followers_list):
        await update.message.reply_text("ℹ️ Gösterilecek başka takipçi kalmadı veya önce /takipci komutunu kullanmanız gerekiyor.")
        return

    next_offset = offset + 20
    chunk = followers_list[offset:next_offset]
    
    text = f"👥 *@{username}* Takipçileri (#{offset+1}–{offset+len(chunk)}):\n\n"
    for i, f in enumerate(chunk, offset + 1):
        uname = f.get("username") or f.get("user", {}).get("username") or "?"
        fname = f.get("full_name") or f.get("fullName") or ""
        verified = " ✅" if f.get("is_verified") else ""
        text += f"{i}. @{uname}{verified}"
        if fname:
            text += f" _{fname}_"
        text += "\n"

    context.user_data["followers_offset"] = next_offset

    if next_offset < len(followers_list):
        text += "\n🔄 *Sonraki 20 kişi için:* `/devam`"

    await update.message.reply_text(text, parse_mode="Markdown")


# ═════════════════════════════════════════════════════════════════════════════
# INSTAGRAM — GÖNDERİ LİSTESİ
# ═════════════════════════════════════════════════════════════════════════════

async def cmd_gonderiler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Kullanım: /gonderiler @kullaniciadi")
        return
    username = args[0].lstrip("@")
    wait_msg = await update.message.reply_text(f"⏳ *@{username}* gönderileri yükleniyor...", parse_mode="Markdown")
    data = await ig_fetch_posts(username)

    if "error" in data:
        await wait_msg.edit_text(f"❌ Hata: {data['error']}")
        return

    posts = data.get("data", data)
    if isinstance(posts, dict):
        posts = posts.get("posts") or posts.get("items") or posts.get("edges") or []

    if not posts:
        await wait_msg.edit_text("❌ Gönderi bulunamadı (hesap gizli veya gönderi yok).")
        return

    text = f"📸 *@{username}* — Son {min(10, len(posts))} Gönderi:\n\n"
    for i, post in enumerate(posts[:10], 1):
        # Farklı API yapılarını destekle
        node   = post.get("node", post)
        likes  = node.get("like_count") or node.get("edge_liked_by", {}).get("count", 0)
        comments = node.get("comment_count") or node.get("edge_media_to_comment", {}).get("count", 0)
        caption_obj = node.get("edge_media_to_caption", {}).get("edges", [])
        caption = ""
        if caption_obj:
            caption = caption_obj[0].get("node", {}).get("text", "")
        caption = caption[:80] + "..." if len(caption) > 80 else caption
        shortcode = node.get("shortcode") or node.get("code") or ""
        link = f"instagram.com/p/{shortcode}" if shortcode else ""

        text += f"{i}. ❤️ {format_number(likes)} 💬 {format_number(comments)}"
        if caption:
            text += f"\n   _{caption}_"
        if link:
            text += f"\n   🔗 {link}"
        text += "\n\n"

    await wait_msg.edit_text(text, parse_mode="Markdown")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    chat_id = update.message.chat_id
    current_msg_id = update.message.message_id

    # Silme işlemi başladı bilgisi
    notif = await update.message.reply_text("🗑️ Sohbet temizleniyor...")

    # Mevcut mesajdan geriye doğru son 200 mesajı silmeye çalış
    deleted = 0
    for msg_id in range(current_msg_id + 1, current_msg_id - 200, -1):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            deleted += 1
        except Exception:
            pass  # Silinemeyen mesajları (zaten silinmiş vb.) atla

    # Bildirim mesajını da sil
    try:
        await notif.delete()
    except Exception:
        pass

    # Ana menüyü yeni temiz sohbette göster
    await start(update, context)


# ═════════════════════════════════════════════════════════════════════════════
# YENİ MODÜLLER (QR & VİDEO İNDİRİCİ)
# ═════════════════════════════════════════════════════════════════════════════

async def handle_qr_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_data = update.message.text
    wait_msg = await update.message.reply_text("⏳ QR Kod oluşturuluyor...")
    
    def make_qr():
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(text_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        bio = BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        return bio
        
    try:
        bio = await asyncio.to_thread(make_qr)
        await wait_msg.delete()
        await update.message.reply_photo(photo=bio, caption="İşte QR Kodunuz! 🔲")
        context.user_data.clear() # Reset state
    except Exception as e:
        await wait_msg.edit_text(f"❌ Bir hata oluştu: {str(e)}")

async def handle_video_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    wait_msg = await update.message.reply_text("⏳ Video indiriliyor, lütfen bekleyin...")

    filename = None

    try:
        # ─── TİKTOK: Render IP'leri TikTok tarafından engellenir.
        # Bu yüzden ücretsiz tikwm.com API'sini kullanıyoruz. ─────────────────
        if "tiktok.com" in url or "vm.tiktok" in url or "vt.tiktok" in url:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                # Önce kısa URL'yi çöz
                resp = await client.get(url)
                final_url = str(resp.url)

                # tikwm API'ye gönder
                api = await client.post(
                    "https://www.tikwm.com/api/",
                    data={"url": final_url, "hd": 1},
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                data = api.json()

            if data.get("code") != 0 or not data.get("data"):
                raise Exception("TikTok videosu alınamadı. Video gizli veya silinmiş olabilir.")

            video_url = data["data"].get("hdplay") or data["data"].get("play")
            if not video_url:
                raise Exception("Video URL'si bulunamadı.")

            # Videoyu indir
            if not os.path.exists("downloads"):
                os.makedirs("downloads")
            filename = f"downloads/tiktok_{data['data'].get('id', 'video')}.mp4"
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.get(video_url)
                with open(filename, "wb") as f:
                    f.write(r.content)

        # ─── YOUTUBE / DİĞER PLATFORMLAR: yt-dlp ile ─────────────────────────
        else:
            def download_ydlp():
                if not os.path.exists("downloads"):
                    os.makedirs("downloads")
                ydl_opts = {
                    'format': 'best[height<=720][ext=mp4]/best[height<=720]/best',
                    'outtmpl': 'downloads/%(id)s.%(ext)s',
                    'quiet': True,
                    'noplaylist': True,
                    'max_filesize': 45000000,
                    'socket_timeout': 30,
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['ios'],  # ios istemcisi bot engelini geçer
                        }
                    },
                    'http_headers': {
                        'User-Agent': 'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X;)',
                    },
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info)

            filename = await asyncio.to_thread(download_ydlp)

        # ─── TELEGRAM'A YÜKLE ─────────────────────────────────────────────────
        await wait_msg.edit_text("⏳ Video Telegram'a yükleniyor...")
        with open(filename, 'rb') as video_file:
            await update.message.reply_video(
                video=video_file,
                caption="İşte videonuz! 📹",
                write_timeout=180,
                read_timeout=180,
                connect_timeout=60,
            )
        await wait_msg.delete()
        context.user_data.clear()

    except Exception as e:
        err_msg = str(e)[:120]
        await wait_msg.edit_text(f"❌ İndirilemedi.\nDetay: {err_msg}")
    finally:
        # Her durumda dosyayı temizle
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass


# /takipci komutu — IG hesabı takipçileri (veya sahte bot)
async def cmd_takipci(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if mode in ["fake_bot_ig", "fake_bot_tt"]:
        args = context.args
        if not args:
            await update.message.reply_text("❌ Lütfen bir sayı girin. Örnek: `/takipci 10000`")
            return
        
        target = context.user_data.get("fake_target", "Bilinmeyen Profil")
        amount = args[0]
        
        msg = await update.message.reply_text("⏳ Kullanıcı profili bulunuyor...")
        await asyncio.sleep(2)
        await msg.edit_text("🔍 Kullanıcı bulundu, analiz ediliyor...")
        await asyncio.sleep(2)
        await msg.edit_text("⚙️ Analiz edildi, botlar yükleniyor...")
        await asyncio.sleep(3)
        await msg.edit_text(f"✅ *{target}* adlı profilinize *{amount}* adet takipçiniz başarıyla ulaşmıştır.\n\nBizi tercih ettiğiniz için teşekkür ederiz, yine bekleriz! 🚀", parse_mode="Markdown")
        context.user_data.clear()
        return

    args = context.args

    if not args:
        await update.message.reply_text("Kullanım: /ig @kullaniciadi")
        return
        
    if context.user_data.get("mode") == "fake_bot_ig":
        pass


# /ig komutu — direkt profil
async def cmd_ig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Kullanım: /ig @kullaniciadi")
        return
        
    if context.user_data.get("mode") == "fake_bot_ig":
        context.user_data["fake_target"] = args[0]
        await update.message.reply_text(f"✅ Instagram kullanıcı adı ayarlandı: *{args[0]}*\n\nŞimdi lütfen kaç takipçi istediğinizi `/takipci <sayı>` komutu ile girin.\nÖrnek: `/takipci 10000`", parse_mode="Markdown")
        return
        
    context.user_data["mode"] = "ig_lookup"
    update.message.text = args[0]
    await handle_ig_lookup(update, context)

async def cmd_tt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Kullanım: /tt @kullaniciadi")
        return
        
    if context.user_data.get("mode") == "fake_bot_tt":
        context.user_data["fake_target"] = args[0]
        await update.message.reply_text(f"✅ TikTok kullanıcı adı ayarlandı: *{args[0]}*\n\nŞimdi lütfen kaç takipçi istediğinizi `/takipci <sayı>` komutu ile girin.\nÖrnek: `/takipci 5000`", parse_mode="Markdown")
        return
        
    await update.message.reply_text("❌ Bu komut sadece Bot Takipçi (TikTok) menüsünde geçerlidir.")




# ═════════════════════════════════════════════════════════════════════════════
# NEXUS BAĞLANTI & ALARM SİSTEMİ
# ═════════════════════════════════════════════════════════════════════════════
NEXUS_API_URL = "https://nexus-mboa.onrender.com"  # Render sunucu adresi
BOT_API_KEY = "gizli_anahtar_123"
NEXUS_PASSWORD = "e3n3s1234/*fb"
AUTHORIZED_USERS = set()

async def ping_nexus_server():
    """Render'ın uyumaması için her 14 dakikada bir sessizce ping atar."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.get(f"{NEXUS_API_URL}/api/bot/status")
    except Exception:
        pass  # Hata olursa sessizce geç, zaten sunucu uyuyor demektir

async def cmd_nexus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        context.user_data["mode"] = "nexus_login"
        await update.message.reply_text(
            "🔒 *Nexus Paneli Kilitli*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Lütfen erişim şifresini mesaj olarak yazın:",
            parse_mode="Markdown"
        )
        return

    wait_msg = await update.message.reply_text("⏳ Nexus sunucusu uykudaysa uyandırılıyor, bu 1-2 dakika sürebilir. Lütfen bekleyin...")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r_status = await client.get(f"{NEXUS_API_URL}/api/bot/status")

            if r_status.status_code != 200:
                await wait_msg.edit_text("⚠️ Sunucuya bağlanıldı ama hata döndü.")
                return

            data = r_status.json()
            uptime_sec = int(data.get('uptime', 0))
            uptime_str = f"{uptime_sec // 3600}s {(uptime_sec % 3600) // 60}dk {uptime_sec % 60}sn"

            text = (
                f"🟢 *Nexus Sunucusu Aktif!*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👥 Anlık Bağlı Kişi: `{data.get('online', 0)}`\n"
                f"⏱️ Uptime: `{uptime_str}`\n\n"
            )

            # Kullanıcı listesini dene (endpoint Render'a push edilmişse çalışır)
            try:
                r_users = await client.get(f"{NEXUS_API_URL}/api/bot/users")
                if r_users.status_code == 200:
                    user_list = r_users.json().get("users", [])
                    if user_list:
                        text += "📋 *Bağlı Kullanıcılar:*\n"
                        users_text = "\n".join(
                            f"{i+1}. 👤 İsim: `{u.get('device_id', 'Bilinmiyor')}`\n"
                            f"   🌐 IP: `{u.get('ip', 'bilinmiyor')}`\n"
                            f"   🔌 Socket: `{u.get('socket_id', '')}`\n"
                            f"   🏠 Oda: {', '.join(u.get('rooms', [])) or '—'}"
                            for i, u in enumerate(user_list)
                        )
                        text += users_text
                        text += f"\n\n━━━━━━━━━━━━━━━━━━\n"
                        text += "🔨 Birini banlamak için:\n`/ban <İsim veya IP>`\n"
                        text += "*(Örn: `/ban Ahmet` veya `/ban 192.168.1.5`)*"
                    else:
                        text += "_Şu an sitede kimse yok._"
            except Exception:
                text += "_Kullanıcı listesi için server.js'i güncelleyin._"

            await wait_msg.edit_text(text, parse_mode="Markdown")

    except Exception as e:
        await wait_msg.edit_text(
            "🔴 *Nexus Sunucusu ÇÖKTÜ veya Ulaşılamıyor!*\n\n"
            "Sunucunuzu başlatmayı deneyin:\n`node server.js`",
            parse_mode="Markdown"
        )

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: `/ban <İsim veya IP>`\nÖrnek: `/ban Ahmet` veya `/ban 37.234.10.5`", parse_mode="Markdown")
        return
    
    # İsimlerde boşluk olabileceği için tüm argümanları birleştiriyoruz
    target = " ".join(context.args)
    wait_msg = await update.message.reply_text(f"⏳ `{target}` banlanıyor...", parse_mode="Markdown")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{NEXUS_API_URL}/api/bot/ban", json={"api_key": BOT_API_KEY, "target": target})
            if r.status_code == 200:
                await wait_msg.edit_text(f"✅ {r.json().get('message')}")
            else:
                await wait_msg.edit_text(f"❌ Hata: {r.text[:100]}")
    except Exception:
        await wait_msg.edit_text("🔴 Sunucuya bağlanılamadı.")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: `/unban <İsim veya IP>`", parse_mode="Markdown")
        return
        
    target = " ".join(context.args)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{NEXUS_API_URL}/api/bot/unban", json={"api_key": BOT_API_KEY, "target": target})
            if r.status_code == 200:
                await update.message.reply_text(f"✅ {r.json().get('message')}")
            else:
                await update.message.reply_text("❌ Bir hata oluştu.")
    except Exception:
        await update.message.reply_text("🔴 Sunucuya bağlanılamadı.")

async def cmd_ekran(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("❌ Bu komutu kullanma yetkiniz yok.")
        return

    wait_msg = await update.message.reply_text("📸 Ekran görüntüsü alınıyor...")
    try:
        from PIL import ImageGrab
        import io
        
        # Ekran görüntüsünü al
        screenshot = ImageGrab.grab()
        
        # Hafızada (RAM) tut, diske kaydetmeye gerek yok
        img_byte_arr = io.BytesIO()
        screenshot.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        await wait_msg.delete()
        await update.message.reply_photo(
            photo=img_byte_arr,
            caption="💻 Bilgisayarınızın Anlık Ekran Görüntüsü"
        )
    except Exception as e:
        await wait_msg.edit_text(
            "❌ **Ekran görüntüsü alınamadı.**\n\n"
            "⚠️ _Not: Bu özellik sadece botu kendi kişisel bilgisayarınızda (Windows/Mac) çalıştırdığınızda çalışır. "
            "Eğer bot şu an Render veya uzak bir sunucuda çalışıyorsa, orada bir ekran olmadığı için bu hatayı verir._\n\n"
            f"Hata Detayı: `{str(e)[:50]}`",
            parse_mode="Markdown"
        )


# ALARM SİSTEMİ
async def send_sivilce_alarm(bot, chat_id):
    # Bu fonksiyon her gün saat 17:00'de çalışır
    await bot.send_message(
        chat_id=chat_id,
        text="⏰ *SİVİLCE BAKIM ZAMANI!*\n\nLütfen bakım rutinini yapmayı unutma.\n\nEğer şimdi yapamıyorsan ve gece 22:00'de hatırlatmamı istiyorsan /ertele komutunu kullan.",
        parse_mode="Markdown"
    )

async def cmd_ertele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    job_id = f"ertele_{chat_id}"
    
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    # Bugün 22:00 için yeni görev kur
    from datetime import datetime
    now = datetime.now(pytz.timezone("Europe/Istanbul"))
    run_time = now.replace(hour=22, minute=0, second=0, microsecond=0)
    if now > run_time:
        run_time = run_time.replace(day=now.day + 1) # if already past 22, run next day (edge case)

    scheduler.add_job(
        send_sivilce_alarm_ertele,
        'date',
        run_date=run_time,
        args=[context.bot, chat_id],
        id=job_id
    )
    await update.message.reply_text("✅ Anlaşıldı, bugün saat 22:00'de tekrar hatırlatacağım.")

async def send_sivilce_alarm_ertele(bot, chat_id):
    await bot.send_message(
        chat_id=chat_id,
        text="⏰ *ERTELENMİŞ SİVİLCE BAKIM ZAMANI!*\n\nGün içindeki rutinini ertelemiştin, artık yapma vakti geldi!",
        parse_mode="Markdown"
    )

# KEEP-ALIVE WEB SUNUCUSU (Flask)
from flask import Flask
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is awake and running!"

def run_web_server():
    # Render gibi sistemlerde PORT değişkeni otomatik verilir, yoksa 8080
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

async def post_init(app: Application):
    # Event loop oluştuktan sonra zamanlayıcıyı başlatıyoruz (Render hatasını önler)
    scheduler.start()

def main():
    if not TELEGRAM_TOKEN:
        print("HATA: TELEGRAM_TOKEN bulunamadı.")
        return

    # Python 3.11+ ve Render'ın bazı güncel sürümlerinde (3.14) döngü hatasını önlemek için 
    # manuel olarak yeni bir Event Loop (Olay Döngüsü) oluşturup ayarlıyoruz.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # PTB'nin dahili job_queue modülünü devre dışı bırakıyoruz ki Python hatası almayalım.
    app = Application.builder().token(TELEGRAM_TOKEN).job_queue(None).post_init(post_init).build()

    # Eğer her kullanıcıya özel yapmak isterseniz /start komutuna alarm kurdurtmalısınız.
    # Biz varsayılan olarak her gün 17:00'de botu başlatan sahibine atmak için start içine koyabiliriz
    # Veya direkt olarak çalıştırırken timezone belirtip Job eklenebilir.
    # Ancak chat_id bilinmeli. Bunun için start komutunda job'u kurmak daha mantıklı.

    # Komutlar
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("ig",         cmd_ig))
    app.add_handler(CommandHandler("tt",         cmd_tt))
    app.add_handler(CommandHandler("takipci",    cmd_takipci))
    app.add_handler(CommandHandler("devam",      cmd_devam))
    app.add_handler(CommandHandler("gonderiler", cmd_gonderiler))
    app.add_handler(CommandHandler("reset",      cmd_reset))
    app.add_handler(CommandHandler("nexus",      cmd_nexus))
    app.add_handler(CommandHandler("ban",        cmd_ban))
    app.add_handler(CommandHandler("unban",      cmd_unban))
    app.add_handler(CommandHandler("ertele",     cmd_ertele))
    app.add_handler(CommandHandler("ekran",      cmd_ekran))
    app.add_handler(CommandHandler("menu",       cmd_menu))
    
    # Buton tıklamaları
    app.add_handler(CallbackQueryHandler(button_handler))

    # Genel mesaj yönlendirici (Metin ve Fotoğraf)
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, message_router))

    # Keep-Alive Sunucuyu Başlat
    Thread(target=run_web_server, daemon=True).start()

    print("Bot baslatiliyor (Polling modu)... Cikmak icin Ctrl+C")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
