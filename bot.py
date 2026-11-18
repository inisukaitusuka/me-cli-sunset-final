#!/usr/bin/env python3
import base64
import html
import importlib
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.isdir(BASE_DIR):
    os.chdir(BASE_DIR)

load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

import qrcode
import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    ForceReply,
)

REQUIRED_ENV_KEYS = [
    "BASE_API_URL",
    "BASE_CIAM_URL",
    "BASIC_AUTH",
    "AX_FP_KEY",
    "UA",
    "API_KEY",
    "ENCRYPTED_FIELD_KEY",
    "XDATA_KEY",
    "AX_API_SIG_KEY",
    "X_API_BASE_SECRET",
]

RECENT_FC_FILE = "recent_fc.json"
SP_PER_PAGE = 12
SFL_PER_PAGE = 12
FAM_BM_PER_PAGE = 10


def is_env_complete() -> bool:
    load_dotenv(override=True)
    return bool(os.getenv("BASE_API_URL") and os.getenv("BASE_CIAM_URL"))


def reload_app_modules():
    """Reload modul internal setelah variabel .env diperbarui via chat tanpa perlu restart bot."""
    load_dotenv(override=True)
    mod_names = [
        "app.service.crypto_helper",
        "app.client.encrypt",
        "app.client.ciam",
        "app.client.engsel",
        "app.client.registration",
        "app.client.store.search",
        "app.client.store.redeemables",
        "app.client.store.segments",
        "app.client.purchase.common",
        "app.client.purchase.balance",
        "app.client.purchase.qris",
        "app.client.purchase.ewallet",
        "app.client.purchase.redeem",
    ]
    for m_name in mod_names:
        if m_name in sys.modules:
            try:
                importlib.reload(sys.modules[m_name])
            except Exception as e:
                print(f"[reload warning] {m_name}: {e}")


def save_env_key(key: str, value: str, env_path: str = ".env"):
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

    key_found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f'{key}="{value}"\n')
            key_found = True
        else:
            new_lines.append(line)

    if not key_found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append(f'{key}="{value}"\n')

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    os.environ[key] = value
    load_dotenv(override=True)


def ensure_bot_config() -> str:
    if not os.path.exists(".env"):
        if os.path.exists(".env.template"):
            with open(".env.template", "r", encoding="utf-8") as src, open(".env", "w", encoding="utf-8") as dst:
                dst.write(src.read())
        else:
            default_keys = REQUIRED_ENV_KEYS + ["TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_IDS"]
            with open(".env", "w", encoding="utf-8") as dst:
                for k in default_keys:
                    dst.write(f'{k}=""\n')

    load_dotenv(override=True)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("==========================================")
        print("      Konfigurasi Awal Bot Telegram       ")
        print("==========================================")
        token = input("Masukkan TELEGRAM_BOT_TOKEN (dari @BotFather): ").strip()
        if not token:
            print("Token tidak boleh kosong. Silakan isi TELEGRAM_BOT_TOKEN di file .env")
            sys.exit(1)
        save_env_key("TELEGRAM_BOT_TOKEN", token)

        admin_ids = input("Masukkan Telegram User ID Admin (opsional, tekan Enter jika bebas diakses): ").strip()
        if admin_ids:
            save_env_key("TELEGRAM_ADMIN_IDS", admin_ids)

    return token


BOT_TOKEN = ensure_bot_config()
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
BOT_NAME = "MyEngsel"

user_states: dict[int, dict] = {}


def init_bot_info():
    """Ambil nama asli bot dari Telegram dan daftarkan command utama secara otomatis."""
    global BOT_NAME
    try:
        me = bot.get_me()
        if me and me.first_name:
            BOT_NAME = me.first_name
    except Exception:
        pass

    commands = [
        BotCommand("start", "Menu Utama"),
        BotCommand("paket", "Paket Aktif & Sisa Kuota"),
        BotCommand("bookmark", "Daftar Bookmark Paket"),
        BotCommand("familycode", "Cari Family Code & Riwayat Recent"),
        BotCommand("optioncode", "Beli Paket via Option Code"),
        BotCommand("store", "Store Packages & Family List"),
        BotCommand("promo", "Promo Redeemables & Segments"),
        BotCommand("riwayat", "Riwayat Transaksi & Pending"),
        BotCommand("notifikasi", "Notifikasi Akun"),
        BotCommand("tools", "Validasi Nomor, PUK & Dukcapil"),
        BotCommand("login", "Kelola Akun & Tambah Nomor"),
        BotCommand("id", "Cek User ID & Chat ID Telegram"),
    ]
    try:
        bot.set_my_commands(commands)
        print(f"[✓] Bot '{BOT_NAME}' siap. Command otomatis berhasil didaftarkan.")
    except Exception as e:
        print(f"[!] Gagal mendaftarkan command otomatis: {e}")


# ============================================================================
# HELPER RECENT FAMILY CODE & STATE PENGGUNA
# ============================================================================

def load_recent_fc() -> list[dict]:
    if not os.path.exists(RECENT_FC_FILE):
        return []
    try:
        with open(RECENT_FC_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def add_recent_fc(family_code: str, family_name: str, is_enterprise: bool | None = None):
    fc = family_code.strip()
    if not fc:
        return
    items = load_recent_fc()
    items = [x for x in items if x.get("family_code", "").lower() != fc.lower()]
    items.insert(0, {
        "family_code": fc,
        "family_name": family_name or "Family",
        "is_enterprise": is_enterprise,
        "visited_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    items = items[:15]
    try:
        with open(RECENT_FC_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
    except Exception:
        pass


def clear_recent_fc():
    try:
        if os.path.exists(RECENT_FC_FILE):
            os.remove(RECENT_FC_FILE)
    except Exception:
        pass


def get_state(chat_id: int) -> dict:
    if chat_id not in user_states:
        user_states[chat_id] = {"step": None, "data": {}}
    return user_states[chat_id]


def set_step(chat_id: int, step: str | None, **kwargs):
    st = get_state(chat_id)
    st["step"] = step
    st["data"].update(kwargs)


def get_allowed_admins() -> set[int]:
    raw = os.getenv("TELEGRAM_ADMIN_IDS", "").strip()
    if not raw:
        return set()
    return {int(p) for p in raw.replace(" ", "").split(",") if p.isdigit()}


def is_authorized(user_id: int) -> bool:
    admins = get_allowed_admins()
    return True if not admins else (user_id in admins)


def normalize_phone(phone: str) -> str:
    p = re.sub(r"[^0-9]", "", phone.strip())
    if p.startswith("08"):
        p = "628" + p[2:]
    elif p.startswith("8"):
        p = "628" + p[1:]
    return p


def parse_quota_input_to_bytes(raw_text: str) -> int | None:
    """Konversi input kuota seperti '10GB', '5.5 GB', '500MB', atau angka MB menjadi bytes."""
    txt = raw_text.strip().upper().replace(",", ".")
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(GB|G|MB|M|KB|K|B)?$", txt)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2) or "MB"
    if unit in ("GB", "G"):
        return int(val * (1024 ** 3))
    elif unit in ("MB", "M"):
        return int(val * (1024 ** 2))
    elif unit in ("KB", "K"):
        return int(val * 1024)
    return int(val)


def format_msisdn_validation(phone: str, res: dict) -> str:
    """Format hasil validasi nomor ke bahasa Indonesia yang rapi tanpa istilah teknis bot/JSON."""
    lines = [f"<b>Hasil Validasi Nomor <code>{html.escape(str(phone))}</code></b>\n"]
    if not isinstance(res, dict):
        lines.append("Gagal memvalidasi nomor. Layanan sedang tidak merespons.")
        return "\n".join(lines)

    d = res.get("data", {}) if isinstance(res.get("data"), dict) else {}
    if not d:
        msg = res.get("message") or res.get("error") or "Data nomor tidak ditemukan atau nomor bukan pelanggan XL."
        lines.append("• <b>Status Pemeriksaan</b>: Gagal / Tidak Ditemukan")
        lines.append(f"• <b>Keterangan</b>: {html.escape(str(msg))}")
        return "\n".join(lines)

    msisdn_val = d.get("msisdn") or phone
    sub_id = d.get("subscriber_id") or "-"

    raw_sub_type = str(d.get("subscription_type") or "").upper()
    sub_type_map = {
        "PREPAID": "Prabayar (XL Prepaid)",
        "POSTPAID": "Pascabayar (XL Prioritas)",
        "PRIORITAS": "Pascabayar (XL Prioritas)",
        "PRIOHYBRID": "XL Prio Hybrid",
        "GO": "XL GO",
    }
    jenis_kartu = sub_type_map.get(raw_sub_type, raw_sub_type or "Prabayar")

    raw_status = str(d.get("status") or "").upper()
    status_map = {
        "ACTIVE": "Aktif",
        "INACTIVE": "Tidak Aktif",
        "GRACE": "Masa Tenggang",
        "SOFT_BLOCK": "Masa Tenggang (Terblokir Sementara)",
        "SUSPENDED": "Ditangguhkan / Terblokir",
        "TERMINATED": "Hangus / Berakhir",
    }
    status_kartu = status_map.get(raw_status, raw_status or "-")

    susp = str(d.get("suspended_status") or "").strip()
    if not susp or susp.upper() in ("NONE", "NULL", "FALSE", "NORMAL"):
        status_blokir = "Normal (Tidak Terblokir)"
    else:
        status_blokir = susp

    is_reg = d.get("is_registered")
    reg_str = "Sudah Terdaftar (Aktif)" if is_reg else "Belum Terdaftar"

    prio_flex = "Aktif" if d.get("has_prio_flex") else "Tidak Aktif"
    jenis_pelanggan = "Kartu Korporat / Bisnis" if d.get("is_enterprise") else "Reguler (Pribadi)"

    bisnis_flags = []
    if d.get("has_bizon"):
        bisnis_flags.append("Bizon Aktif")
    if d.get("has_bizoptimus_package") or d.get("is_member_optimus"):
        bisnis_flags.append("BizOptimus Aktif")
    paket_bisnis = ", ".join(bisnis_flags) if bisnis_flags else "Tidak Aktif"

    lines.extend([
        f"• <b>Nomor XL</b>: <code>{html.escape(str(msisdn_val))}</code>",
        f"• <b>ID Pelanggan</b>: <code>{html.escape(str(sub_id))}</code>",
        f"• <b>Jenis Kartu</b>: {html.escape(jenis_kartu)}",
        f"• <b>Status Kartu</b>: {html.escape(status_kartu)}",
        f"• <b>Status Blokir</b>: {html.escape(status_blokir)}",
        f"• <b>Registrasi Dukcapil</b>: {html.escape(reg_str)}",
        f"• <b>Layanan Prio Flex</b>: {html.escape(prio_flex)}",
        f"• <b>Kategori Pelanggan</b>: {html.escape(jenis_pelanggan)}",
        f"• <b>Paket Bisnis (Bizon/Optimus)</b>: {html.escape(paket_bisnis)}",
    ])
    return "\n".join(lines)


def format_clean_api_result(title: str, res) -> str:
    """Format respons API ke bahasa Indonesia yang mudah dipahami tanpa kode JSON mentah."""
    lines = [f"<b>{html.escape(title)}</b>\n"]
    if not isinstance(res, dict):
        lines.append(f"• <b>Keterangan</b>: {html.escape(str(res or 'Tidak ada respons dari server.'))}")
        return "\n".join(lines)

    raw_status = str(res.get("status") or "").upper()
    code = str(res.get("code") or "")
    is_ok = raw_status in ("SUCCESS", "OK") or code in ("000", "200", "0")
    lines.append(f"• <b>Status</b>: {'Berhasil' if is_ok else 'Gagal'}")

    msg = res.get("message") or res.get("error_description") or res.get("error") or ""
    if msg:
        lines.append(f"• <b>Pesan</b>: {html.escape(str(msg))}")

    data = res.get("data")
    label_map = {
        "msisdn": "Nomor XL",
        "subscriber_id": "ID Pelanggan",
        "subscription_type": "Jenis Kartu",
        "status": "Status",
        "is_valid": "Kelayakan Nomor",
        "eligible": "Kelayakan Bergabung",
        "is_eligible": "Kelayakan Bergabung",
        "reason": "Alasan / Keterangan",
        "message": "Keterangan",
        "group_name": "Nama Grup",
        "group_id": "ID Grup",
        "member_name": "Nama Anggota",
        "alias": "Nama Anggota",
        "quota_allocated": "Alokasi Kuota",
        "total_spending": "Total Pemakaian",
        "spending": "Pemakaian",
        "puk": "Kode PUK",
        "puk1": "Kode PUK 1",
        "puk2": "Kode PUK 2",
    }
    if isinstance(data, dict) and data:
        for k, v in data.items():
            if isinstance(v, (dict, list)) or v is None or str(v).strip() == "":
                continue
            label = label_map.get(k, k.replace("_", " ").title())
            if isinstance(v, bool):
                val_str = "Ya" if v else "Tidak"
            elif str(v).upper() == "PREPAID":
                val_str = "Prabayar (XL Prepaid)"
            elif str(v).upper() == "POSTPAID":
                val_str = "Pascabayar (XL Prioritas)"
            elif str(v).upper() in ("ACTIVE", "SUCCESS"):
                val_str = "Aktif / Berhasil"
            else:
                val_str = str(v)
            lines.append(f"• <b>{html.escape(label)}</b>: {html.escape(val_str)}")
    elif isinstance(data, list) and data:
        for idx, item in enumerate(data[:15], 1):
            if isinstance(item, dict):
                name = item.get("name") or item.get("title") or item.get("msisdn") or f"Data #{idx}"
                desc = item.get("description") or item.get("status") or item.get("amount") or ""
                lines.append(f"{idx}. <b>{html.escape(str(name))}</b>" + (f" — {html.escape(str(desc))}" if desc else ""))
            else:
                lines.append(f"{idx}. {html.escape(str(item))}")
    return "\n".join(lines)


def send_or_edit(chat_id: int, text: str, markup=None, message_id: int | None = None):
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    st = get_state(chat_id)
    last_bot_mid = st["data"].get("last_bot_msg_id")

    # Jika message_id ada dan merupakan pesan terbaru, edit langsung di tempat.
    # Jika message_id tertinggal jauh di atas (karena ada pesan baru di bawahnya), hapus pesan lama lalu kirim di paling bawah agar tidak perlu scroll.
    if message_id:
        if last_bot_mid and message_id < last_bot_mid:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
            message_id = None
        else:
            try:
                res = bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode="HTML",
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )
                st["data"]["last_bot_msg_id"] = message_id
                return res
            except Exception as e:
                if "message is not modified" in str(e).lower():
                    return None
                try:
                    bot.delete_message(chat_id, message_id)
                except Exception:
                    pass

    # Saat mengirim pesan menu baru di paling bawah, hapus pesan menu lama (jika ada) agar tidak menumpuk di ruang chat
    if last_bot_mid:
        try:
            bot.delete_message(chat_id, last_bot_mid)
        except Exception:
            pass

    sent = bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    if sent and hasattr(sent, "message_id"):
        st["data"]["last_bot_msg_id"] = sent.message_id
    return sent


def back_home_markup() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
    return m


def after_purchase_markup(chat_id: int, include_pkg_detail: bool = True) -> InlineKeyboardMarkup:
    """Markup setelah transaksi selesai/gagal: menyediakan 2 opsi kembali (ke fitur yang dimasuki & ke Menu Utama)."""
    m = InlineKeyboardMarkup()
    st = get_state(chat_id)
    lf = st["data"].get("last_feature")
    cp = st["data"].get("current_pkg")

    if include_pkg_detail and cp and cp.get("option_code"):
        m.row(InlineKeyboardButton("Kembali ke Detail Paket", callback_data="back_current_pkg"))

    if lf and lf.get("cb") and lf.get("label"):
        m.row(
            InlineKeyboardButton(lf["label"], callback_data=lf["cb"]),
            InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"),
        )
    elif st["data"].get("current_fc"):
        m.row(
            InlineKeyboardButton("Kembali ke Daftar Paket Family", callback_data="fambm:back"),
            InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"),
        )
    else:
        m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
    return m


# ============================================================================
# MENU UTAMA, PROFIL & KELOLA AKUN
# ============================================================================

def render_home(chat_id: int, message_id: int | None = None, user_name: str | None = None):
    if not is_env_complete():
        text = (
            "<b>Konfigurasi .env Belum Lengkap</b>\n\n"
            "Variabel <code>BASE_API_URL</code> dan <code>BASE_CIAM_URL</code> belum diisi.\n"
            "Silakan <b>tempelkan (paste) teks .env</b> atau <b>kirim file .env</b> langsung ke ruang chat ini."
        )
        send_or_edit(chat_id, text, None, message_id)
        return

    from app.service.auth import AuthInstance
    from app.client.engsel import get_balance, get_tiering_info

    set_step(chat_id, None)
    if user_name:
        set_step(chat_id, None, user_name=user_name)
    else:
        user_name = get_state(chat_id)["data"].get("user_name", "User")

    AuthInstance.load_tokens()
    active_user = AuthInstance.get_active_user()

    if not active_user:
        render_welcome_login(chat_id, message_id, user_name=user_name)
        return

    greeting_block = (
        f"Halo, <b>{html.escape(user_name)}</b>! 👋 Selamat datang di <b>{html.escape(BOT_NAME)}</b>\n\n"
    )

    try:
        balance = get_balance(AuthInstance.api_key, active_user["tokens"]["id_token"]) or {}
        balance_remaining = balance.get("remaining", 0)
        exp_ts = balance.get("expired_at", 0)
        expired_at_dt = datetime.fromtimestamp(exp_ts).strftime("%Y-%m-%d") if exp_ts else "-"

        point_info = "Poin: - | Tier: -"
        if active_user.get("subscription_type") == "PREPAID":
            tiering = get_tiering_info(AuthInstance.api_key, active_user["tokens"]) or {}
            point_info = f"Poin: {tiering.get('current_point', 0):,} | Tier: {tiering.get('tier', '-')}"

        text = (
            f"{greeting_block}"
            "<b>Menu Utama</b>\n\n"
            f"Nomor: <code>{active_user['number']}</code> ({active_user.get('subscription_type', 'PREPAID')})\n"
            f"Pulsa: <b>Rp {balance_remaining:,}</b>\n"
            f"Masa Aktif: {expired_at_dt}\n"
            f"{point_info}\n\n"
            "Silakan pilih menu layanan di bawah ini:"
        )
    except Exception as e:
        text = (
            f"{greeting_block}"
            f"<b>Menu Utama</b>\n\n"
            f"Nomor: <code>{active_user.get('number')}</code>\n"
            f"Info Saldo: <code>{html.escape(str(e))}</code>"
        )

    m = InlineKeyboardMarkup()
    m.row(
        InlineKeyboardButton("Paket Aktif", callback_data="nav:my_pkg"),
        InlineKeyboardButton("Bookmark", callback_data="nav:bookmark"),
    )
    m.row(
        InlineKeyboardButton("Option Code", callback_data="nav:input_opt"),
        InlineKeyboardButton("Family Code", callback_data="nav:input_fam"),
    )
    m.row(
        InlineKeyboardButton("Store Packages", callback_data="nav:store_pkg"),
        InlineKeyboardButton("Store Family List", callback_data="nav:store_fam"),
    )
    m.row(
        InlineKeyboardButton("Promo & Redeemables", callback_data="nav:redeemables"),
        InlineKeyboardButton("Store Segments", callback_data="nav:segments"),
    )
    m.row(
        InlineKeyboardButton("Riwayat Transaksi", callback_data="nav:history"),
        InlineKeyboardButton("Notifikasi", callback_data="nav:notif"),
    )
    m.row(
        InlineKeyboardButton("Tools & Registrasi", callback_data="nav:tools"),
        InlineKeyboardButton("Profil & Pending", callback_data="nav:profile"),
    )
    m.row(
        InlineKeyboardButton("Login / Tambah Akun", callback_data="acc:login_popup"),
        InlineKeyboardButton("Kelola Akun", callback_data="nav:accounts"),
    )
    m.row(
        InlineKeyboardButton("Refresh", callback_data="nav:home"),
    )
    send_or_edit(chat_id, text, m, message_id)


def render_welcome_login(chat_id: int, message_id: int | None = None, user_name: str | None = None):
    set_step(chat_id, "WAIT_PHONE")
    if not user_name:
        user_name = get_state(chat_id)["data"].get("user_name", "User")

    text = (
        f"Halo, <b>{html.escape(user_name)}</b>! 👋 Selamat datang di <b>{html.escape(BOT_NAME)}</b>\n\n"
        "Belum ada akun yang aktif saat ini. Yuk, mulai dengan memasukkan nomor XL kamu:"
    )
    m = InlineKeyboardMarkup()
    m.row(
        InlineKeyboardButton("Login / Tambah Akun", callback_data="acc:login_popup"),
        InlineKeyboardButton("Restore Token", callback_data="acc:restore_prompt"),
    )

    from app.service.auth import AuthInstance
    if AuthInstance.refresh_tokens:
        m.row(InlineKeyboardButton("Kelola Akun Tersimpan", callback_data="nav:accounts"))

    send_or_edit(chat_id, text, m, message_id)


def render_accounts_menu(chat_id: int, message_id: int | None = None):
    from app.service.auth import AuthInstance

    set_step(chat_id, None)
    AuthInstance.load_tokens()
    users = AuthInstance.refresh_tokens
    active_user = AuthInstance.get_active_user()

    lines = ["<b>Kelola Akun</b>\n"]
    m = InlineKeyboardMarkup()

    if not users:
        lines.append("Belum ada akun yang tersimpan.")
    else:
        lines.append("Pilih nomor di bawah untuk mengganti akun aktif:")
        for u in users:
            num = u.get("number")
            stype = u.get("subscription_type", "PREPAID")
            is_act = active_user and active_user.get("number") == num
            label = f"[Aktif] {num} ({stype})" if is_act else f"{num} ({stype})"
            m.row(
                InlineKeyboardButton(label, callback_data=f"acc:set:{num}"),
                InlineKeyboardButton("Hapus", callback_data=f"acc:del:{num}"),
            )

    m.row(InlineKeyboardButton("Login / Tambah Akun Baru", callback_data="acc:login_popup"))
    m.row(
        InlineKeyboardButton("Backup Akun (Token)", callback_data="acc:backup"),
        InlineKeyboardButton("Restore Token", callback_data="acc:restore_prompt"),
    )
    if active_user:
        m.row(InlineKeyboardButton("Perbarui Sesi Token Aktif", callback_data="acc:refresh_token"))
        m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))

    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def render_profile_pending(chat_id: int, message_id: int | None = None):
    """Tampilkan detail profil lengkap beserta daftar transaksi yang masih Pending."""
    from app.service.auth import AuthInstance
    from app.client.engsel import get_profile, get_balance, get_tiering_info

    active_user = AuthInstance.get_active_user()
    if not active_user:
        render_welcome_login(chat_id, message_id)
        return

    send_or_edit(chat_id, "Memuat detail profil & status transaksi pending...", None, message_id)
    tokens = active_user["tokens"]
    prof_data = get_profile(AuthInstance.api_key, tokens["access_token"], tokens["id_token"]) or {}
    prof = prof_data.get("profile", {}) if isinstance(prof_data, dict) else {}
    pending_list = prof_data.get("pending_payment", []) if isinstance(prof_data, dict) else []

    balance = get_balance(AuthInstance.api_key, tokens["id_token"]) or {}
    bal_rem = balance.get("remaining", 0)
    exp_ts = balance.get("expired_at", 0)
    exp_str = datetime.fromtimestamp(exp_ts).strftime("%d %b %Y") if exp_ts else "-"

    lines = [
        "<b>Profil Akun & Transaksi Pending</b>\n",
        f"Nomor MSISDN: <code>{active_user.get('number')}</code>",
        f"Subscriber ID: <code>{html.escape(str(prof.get('subscriber_id') or active_user.get('subscriber_id', '-')))}</code>",
        f"Tipe Kartu: <b>{html.escape(str(prof.get('subscription_type') or active_user.get('subscription_type', '-')))}</b>",
        f"Nama / Alias: {html.escape(str(prof.get('name') or '-'))}",
        f"Email: {html.escape(str(prof.get('email') or '-'))}",
        f"Pulsa: Rp {bal_rem:,} (Aktif s/d {exp_str})",
    ]

    if active_user.get("subscription_type") == "PREPAID":
        tier = get_tiering_info(AuthInstance.api_key, tokens) or {}
        lines.append(f"Poin Loyalty: {tier.get('current_point', 0):,} | Tier: {tier.get('tier', '-')}")

    m = InlineKeyboardMarkup()
    if pending_list:
        lines.append(f"\n<b>Transaksi Pending ({len(pending_list)}):</b>")
        for idx, p in enumerate(pending_list[:8], 1):
            p_title = p.get("package_name") or p.get("title") or "Transaksi"
            p_price = p.get("price") or f"Rp {p.get('raw_price', 0):,}"
            p_with = p.get("payment_with_label") or p.get("payment_with") or "-"
            p_date = p.get("formated_date") or "-"
            p_id = p.get("payment_id") or p.get("reference_id") or ""
            lines.append(
                f"{idx}. <b>{html.escape(str(p_title))}</b> ({html.escape(str(p_price))})\n"
                f"   Metode: {html.escape(str(p_with))} | {html.escape(str(p_date))}\n"
                f"   ID: <code>{html.escape(str(p_id))}</code>"
            )
            if "QRIS" in str(p_with).upper() and p_id:
                m.row(InlineKeyboardButton(f"Lihat QRIS Pending #{idx}", callback_data=f"pend:qris:{p_id}"))
    else:
        lines.append("\n<i>Tidak ada transaksi yang sedang pending.</i>")

    m.row(
        InlineKeyboardButton("Perbarui Token", callback_data="acc:refresh_token"),
        InlineKeyboardButton("Riwayat Transaksi", callback_data="nav:history"),
    )
    m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def trigger_login_popup(call):
    """Tampilkan Popup Alert di layar Telegram sekaligus membuka kotak input balasan otomatis."""
    chat_id = call.message.chat.id
    set_step(chat_id, "WAIT_PHONE")

    try:
        bot.answer_callback_query(
            call.id,
            "Silakan masukkan nomor XL kamu (contoh: 081234567890) pada kolom chat di bawah.",
            show_alert=True,
        )
    except Exception:
        pass

    force_markup = ForceReply(
        selective=False,
        input_field_placeholder="Masukkan nomor XL (0812xxxx / 62812xxxx)...",
    )
    bot.send_message(
        chat_id,
        "Masukkan nomor XL kamu (contoh: <code>081234567890</code> atau <code>6281234567890</code>):",
        parse_mode="HTML",
        reply_markup=force_markup,
    )


# ============================================================================
# PAKET AKTIF, ADDONS, FAMILY CODE (+ RECENT), MULTI-BOOKMARK, & DETAIL PAKET
# ============================================================================

def render_my_packages(chat_id: int, message_id: int | None = None):
    from app.service.auth import AuthInstance
    from app.client.engsel import send_api_request
    from app.menus.util import format_quota_byte

    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        render_welcome_login(chat_id, message_id)
        return

    send_or_edit(chat_id, "Sedang mengambil daftar paket aktif...", None, message_id)

    payload = {"is_enterprise": False, "lang": "en", "family_member_id": ""}
    res = send_api_request(AuthInstance.api_key, "api/v8/packages/quota-details", payload, tokens["id_token"], "POST")

    if not isinstance(res, dict) or res.get("status") != "SUCCESS":
        send_or_edit(chat_id, f"Gagal mengambil paket:\n<code>{html.escape(str(res))}</code>", back_home_markup(), message_id)
        return

    quotas = res.get("data", {}).get("quotas", [])
    if not quotas:
        send_or_edit(chat_id, "<b>Paket Aktif</b>\n\nTidak ada paket aktif saat ini.", back_home_markup(), message_id)
        return

    lines = ["<b>Paket Aktif</b>\n"]
    m = InlineKeyboardMarkup()
    my_pkgs_cache = []

    for idx, q in enumerate(quotas, 1):
        q_name = q.get("name", "Paket")
        q_code = q.get("quota_code", "")
        sub_type = q.get("product_subscription_type", "")
        domain = q.get("product_domain", "")
        my_pkgs_cache.append({
            "name": q_name,
            "quota_code": q_code,
            "sub_type": sub_type,
            "domain": domain,
        })

        lines.append(f"<b>{idx}. {html.escape(q_name)}</b>")
        for b in q.get("benefits", []):
            b_name = b.get("name", "")
            dtype = b.get("data_type", "")
            rem = b.get("remaining", 0)
            tot = b.get("total", 0)
            if dtype == "DATA":
                q_str = f"{format_quota_byte(rem)} / {format_quota_byte(tot)}"
            elif dtype == "VOICE":
                q_str = f"{rem/60:.0f} / {tot/60:.0f} menit"
            else:
                q_str = f"{rem} / {tot}"
            lines.append(f"- {html.escape(b_name)}: {q_str}")
        lines.append("")

        m.row(
            InlineKeyboardButton(f"Detail #{idx}", callback_data=f"mypkg:view:{idx-1}"),
            InlineKeyboardButton(f"Stop #{idx}", callback_data=f"mypkg:del:{idx-1}"),
        )

    set_step(chat_id, None, my_pkgs=my_pkgs_cache)
    m.row(
        InlineKeyboardButton("Refresh Paket", callback_data="nav:my_pkg"),
        InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
    )
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def render_package_addons(chat_id: int, option_code: str, pkg_name: str = "Paket", message_id: int | None = None):
    """Tampilkan daftar Addons (Pinky Box / Tambahan) untuk suatu Option Code."""
    from app.service.auth import AuthInstance
    from app.client.engsel import get_addons

    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        render_welcome_login(chat_id, message_id)
        return

    send_or_edit(chat_id, f"Mengecek Addons untuk <b>{html.escape(pkg_name)}</b>...", None, message_id)
    data = get_addons(AuthInstance.api_key, tokens, option_code) or {}

    addons_list = []
    if isinstance(data, dict):
        for k in ("addons", "package_options", "options", "items", "list"):
            if isinstance(data.get(k), list):
                addons_list = data.get(k)
                break

    lines = [
        f"<b>Addons Paket: {html.escape(pkg_name)}</b>",
        f"Option Code: <code>{html.escape(option_code)}</code>\n",
    ]
    m = InlineKeyboardMarkup()

    if addons_list:
        for idx, item in enumerate(addons_list[:15], 1):
            a_name = item.get("name") or item.get("title") or f"Addon #{idx}"
            a_price = item.get("price", 0)
            a_code = item.get("package_option_code") or item.get("option_code") or item.get("code") or ""
            lines.append(f"{idx}. <b>{html.escape(str(a_name))}</b> — Rp {a_price:,}")
            if a_code:
                m.row(InlineKeyboardButton(f"Buka {idx}. {str(a_name)[:24]} (Rp {a_price:,})", callback_data=f"addon_open:{idx-1}"))
        set_step(chat_id, None, addons_cache=addons_list)
    elif data:
        raw_preview = json.dumps(data, indent=2)
        if len(raw_preview) > 2500:
            raw_preview = raw_preview[:2500] + "\n..."
        lines.append(f"<code>{html.escape(raw_preview)}</code>")
    else:
        lines.append("Tidak ada Addons yang tersedia untuk paket ini.")

    set_step(chat_id, None, last_addon_pkg_code=option_code)
    m.row(
        InlineKeyboardButton("Kembali ke Paket", callback_data="nav:my_pkg"),
        InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
    )
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def render_fc_search_menu(chat_id: int, message_id: int | None = None):
    """Tampilkan menu Family Code beserta daftar Recent Family Code yang baru dikunjungi."""
    set_step(chat_id, "WAIT_FAMILY_CODE")
    recent_list = load_recent_fc()

    lines = [
        "<b>Family Code</b>\n",
        "Silakan ketik dan kirim <b>Family Code</b> ke ruang chat.",
    ]

    m = InlineKeyboardMarkup()
    if recent_list:
        lines.append("\n<b>Baru Dikunjungi (Recent):</b>")
        for idx, item in enumerate(recent_list, 1):
            fname = item.get("family_name", "Family")
            fcode = item.get("family_code", "")
            vtime = item.get("visited_at", "")
            time_info = f" ({vtime})" if vtime else ""
            lines.append(f"{idx}. <b>{html.escape(fname)}</b>{time_info}\n   <code>{html.escape(fcode)}</code>")
            btn_label = f"{idx}. {fname}"
            m.row(InlineKeyboardButton(btn_label, callback_data=f"recfc:open:{idx-1}"))

        m.row(InlineKeyboardButton("Hapus Riwayat Recent", callback_data="recfc:clear"))

    m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


FAM_PKG_PER_PAGE = 14


def render_family_packages(chat_id: int, family_code: str, is_enterprise: bool | None = None, message_id: int | None = None, use_cache: bool = False, page: int = 0):
    from app.service.auth import AuthInstance
    from app.client.engsel import get_family

    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        render_welcome_login(chat_id, message_id)
        return

    st = get_state(chat_id)
    if use_cache and st["data"].get("current_fc") == family_code and st["data"].get("fam_options"):
        fam_name = st["data"].get("current_fam_name", "Family")
        currency = st["data"].get("current_fam_currency", "Rp")
        pkg_options = st["data"]["fam_options"]
    else:
        w_msg = send_or_edit(chat_id, f"Mencari daftar paket untuk Family Code <code>{html.escape(family_code)}</code>...", None, message_id)
        if w_msg and hasattr(w_msg, "message_id"):
            message_id = w_msg.message_id

        data = get_family(AuthInstance.api_key, tokens, family_code, is_enterprise)
        if not data and is_enterprise is not None:
            data = get_family(AuthInstance.api_key, tokens, family_code, None)

        if not data:
            set_step(chat_id, "WAIT_FAMILY_CODE")
            m = InlineKeyboardMarkup()
            m.row(
                InlineKeyboardButton("Kembali ke Family Code", callback_data="nav:input_fam"),
                InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
            )
            send_or_edit(chat_id, f"Family Code <code>{html.escape(family_code)}</code> tidak ditemukan.\nSilakan kirim Family Code lain atau klik tombol di bawah:", m, message_id)
            return

        fam_name = data["package_family"].get("name", "Family")
        currency = "Poin" if data["package_family"].get("rc_bonus_type") == "MYREWARDS" else "Rp"
        variants = data.get("package_variants", [])

        add_recent_fc(family_code, fam_name, is_enterprise)

        pkg_options = []
        for v in variants:
            v_name = v.get("name", "")
            for opt in v.get("package_options", []):
                o_name = opt.get("name", "Opsi")
                o_price = opt.get("price", 0)
                o_code = opt.get("package_option_code", "")
                o_order = opt.get("order", -1)

                pkg_options.append({
                    "code": o_code,
                    "family_code": family_code,
                    "family_name": fam_name,
                    "is_enterprise": bool(is_enterprise),
                    "variant_name": v_name,
                    "option_name": o_name,
                    "price": o_price,
                    "currency": currency,
                    "order": o_order,
                })

        set_step(
            chat_id,
            None,
            current_fc=family_code,
            current_fam_name=fam_name,
            current_fam_currency=currency,
            fam_options=pkg_options,
            bm_selected=[],
            fam_page=0,
        )

    total_items = len(pkg_options)
    total_pages = max(1, (total_items + FAM_PKG_PER_PAGE - 1) // FAM_PKG_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    st["data"]["fam_page"] = page

    start_idx = page * FAM_PKG_PER_PAGE
    end_idx = min(start_idx + FAM_PKG_PER_PAGE, total_items)

    variants_in_page = []
    for idx in range(start_idx, end_idx):
        vn = (pkg_options[idx].get("variant_name") or "").strip()
        if vn and vn not in variants_in_page:
            variants_in_page.append(vn)

    page_info = f" — Hal {page+1}/{total_pages}" if total_pages > 1 else ""
    var_line = f"Varian: <b>{html.escape(', '.join(variants_in_page))}</b> | " if variants_in_page else ""
    text_lines = [
        f"<b>Family: {html.escape(fam_name)}</b>{page_info}",
        f"Code: <code>{html.escape(family_code)}</code>",
        f"{var_line}Total: <b>{total_items} Paket</b> (Pilih di bawah):",
    ]
    variants_text = "\n".join(text_lines)

    m = InlineKeyboardMarkup()
    row_btns = []
    for idx in range(start_idx, end_idx):
        opt = pkg_options[idx]
        o_name = opt["option_name"]
        o_price = opt["price"]
        row_btns.append(
            InlineKeyboardButton(
                f"{idx+1}. {o_name[:18]} ({currency} {o_price:,})",
                callback_data=f"famopt:{idx}",
            )
        )
        if len(row_btns) == 2:
            m.row(*row_btns)
            row_btns = []
    if row_btns:
        m.row(*row_btns)

    if total_pages > 1:
        nav_row = []
        if page >= 5:
            nav_row.append(InlineKeyboardButton("⏪ -5", callback_data=f"fampage:{page-5}"))
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"fampage:{page-1}"))
        nav_row.append(InlineKeyboardButton(f"Hal {page+1}/{total_pages}", callback_data="fampage:info"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"fampage:{page+1}"))
        if page + 5 < total_pages:
            nav_row.append(InlineKeyboardButton("+5 ⏩", callback_data=f"fampage:{page+5}"))
        m.row(*nav_row)

    if pkg_options:
        m.row(InlineKeyboardButton("Tambah Banyak ke Bookmark", callback_data="fambm:mode:0"))

    parent_nav = st["data"].get("fam_parent_nav")
    if parent_nav and parent_nav.get("cb") and parent_nav.get("label"):
        m.row(
            InlineKeyboardButton(parent_nav["label"], callback_data=parent_nav["cb"]),
            InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
        )
    else:
        m.row(
            InlineKeyboardButton("Kembali ke Family Code", callback_data="nav:input_fam"),
            InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
        )

    send_or_edit(chat_id, variants_text, m, message_id)


def render_family_bulk_bookmark(chat_id: int, message_id: int | None = None, page: int = 0):
    """Mode checklist untuk memilih banyak paket sekaligus di dalam Family Code untuk ditambahkan ke Bookmark."""
    st = get_state(chat_id)
    pkg_options = st["data"].get("fam_options", [])
    fam_name = st["data"].get("current_fam_name", "Family")
    family_code = st["data"].get("current_fc", "")
    selected: list[int] = st["data"].get("bm_selected", [])

    if not pkg_options:
        render_fc_search_menu(chat_id, message_id)
        return

    total_items = len(pkg_options)
    total_pages = max(1, (total_items + FAM_BM_PER_PAGE - 1) // FAM_BM_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    st["data"]["fambm_page"] = page

    start_idx = page * FAM_BM_PER_PAGE
    end_idx = min(start_idx + FAM_BM_PER_PAGE, total_items)

    selected_preview_lines = []
    if selected:
        selected_preview_lines.append("\n<b>Urutan Nomor di Bookmark Nanti:</b>")
        for order_no, sel_idx in enumerate(selected, 1):
            if 0 <= sel_idx < len(pkg_options):
                s_opt = pkg_options[sel_idx]
                s_v = f"{s_opt['variant_name']} - " if s_opt.get("variant_name") else ""
                selected_preview_lines.append(
                    f"<b>{order_no}.</b> {html.escape(s_v + s_opt['option_name'])} <i>(Pilihan dari No. {sel_idx+1})</i>"
                )
        selected_preview_lines.append("")

    preview_block = "\n".join(selected_preview_lines) + "\n" if selected_preview_lines else "\n"

    text = (
        f"<b>Pilih Paket ke Bookmark</b>\n\n"
        f"Family: <b>{html.escape(fam_name)}</b>\n"
        f"Code: <code>{html.escape(family_code)}</code>\n"
        f"Terpilih: <b>{len(selected)}</b> dari {total_items} paket"
        f"{preview_block}"
        "Klik paket sesuai urutan yang diinginkan (paket yang dipilih duluan akan menjadi nomor 1, 2, 3, dst di Bookmark), lalu tekan <b>Simpan ke Bookmark</b>:"
    )

    m = InlineKeyboardMarkup()
    for idx in range(start_idx, end_idx):
        opt = pkg_options[idx]
        if idx in selected:
            sel_order = selected.index(idx) + 1
            mark = f"[#{sel_order} ✓]"
        else:
            mark = "[ ]"
        v_prefix = f"{opt['variant_name']} - " if opt.get("variant_name") else ""
        label = f"{mark} {idx+1}. {v_prefix}{opt['option_name']} ({opt['currency']} {opt['price']:,})"
        m.row(InlineKeyboardButton(label[:48], callback_data=f"fambm:toggle:{idx}"))

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"fambm:mode:{page-1}"))
        nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="fambm:page_info"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"fambm:mode:{page+1}"))
        m.row(*nav_row)

    m.row(
        InlineKeyboardButton("Pilih Semua", callback_data="fambm:all"),
        InlineKeyboardButton("Reset Pilihan", callback_data="fambm:none"),
    )
    m.row(InlineKeyboardButton(f"Simpan ke Bookmark ({len(selected)} dipilih)", callback_data="fambm:save"))
    m.row(InlineKeyboardButton("Kembali ke Daftar Paket", callback_data="fambm:back"))

    send_or_edit(chat_id, text, m, message_id)


def render_package_detail(chat_id: int, option_code: str, is_enterprise: bool = False, option_order: int = -1, message_id: int | None = None):
    from app.service.auth import AuthInstance
    from app.client.engsel import get_package
    from app.menus.util import format_quota_byte

    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        render_welcome_login(chat_id, message_id)
        return

    w_msg = send_or_edit(chat_id, "Sedang memuat detail paket...", None, message_id)
    if w_msg and hasattr(w_msg, "message_id"):
        message_id = w_msg.message_id

    pkg = get_package(AuthInstance.api_key, tokens, option_code)
    if not pkg:
        send_or_edit(chat_id, "Gagal memuat detail paket. Pastikan Option Code benar.", after_purchase_markup(chat_id, include_pkg_detail=False), message_id)
        return

    price = pkg["package_option"].get("price", 0)
    validity = pkg["package_option"].get("validity", "-")
    point = pkg["package_option"].get("point", 0)
    option_name = pkg.get("package_option", {}).get("name", "")
    family_name = pkg.get("package_family", {}).get("name", "")
    variant_name = pkg.get("package_detail_variant", {}).get("name", "")
    family_code = pkg.get("package_family", {}).get("package_family_code", "")
    payment_for = pkg.get("package_family", {}).get("payment_for", "") or "BUY_PACKAGE"

    title = f"{family_name} - {variant_name} - {option_name}".strip(" -")

    lines = [
        f"<b>{html.escape(title)}</b>",
        f"Harga: <b>Rp {price:,}</b> | Aktif: {html.escape(str(validity))} | Poin: {point}",
    ]
    if family_code:
        lines.append(f"Family Code: <code>{html.escape(family_code)}</code>")

    benefits = pkg["package_option"].get("benefits", [])
    if benefits:
        lines.append("\n<b>Benefit Kuota:</b>")
        for b in benefits:
            b_name = b.get("name", "")
            dtype = b.get("data_type", "")
            tot = b.get("total", 0)
            unlim = " (Unlimited)" if b.get("is_unlimited") else ""
            if dtype == "DATA" and tot > 0:
                val_str = format_quota_byte(int(tot))
            elif dtype == "VOICE" and tot > 0:
                val_str = f"{tot/60:.0f} menit"
            elif dtype == "TEXT" and tot > 0:
                val_str = f"{tot} SMS"
            else:
                val_str = f"{tot}"
            lines.append(f"• {html.escape(b_name)}: <b>{val_str}{unlim}</b>")

    lines.append("\nPilih metode pembelian:")

    set_step(
        chat_id,
        None,
        current_pkg={
            "option_code": option_code,
            "is_enterprise": is_enterprise,
            "option_order": option_order,
            "price": price,
            "variant_name": variant_name,
            "option_name": option_name,
            "family_code": family_code,
            "family_name": family_name,
            "token_confirmation": pkg.get("token_confirmation", ""),
            "timestamp": pkg.get("timestamp", 0),
            "payment_for": payment_for,
        },
    )

    m = InlineKeyboardMarkup()
    m.row(
        InlineKeyboardButton("Beli Pulsa", callback_data="buy:bal"),
        InlineKeyboardButton("Bayar QRIS", callback_data="buy:qris"),
    )
    m.row(
        InlineKeyboardButton("Pulsa (Custom Rp)", callback_data="buy:bal_custom"),
        InlineKeyboardButton("QRIS (Custom Rp)", callback_data="buy:qris_custom"),
    )
    m.row(
        InlineKeyboardButton("DANA", callback_data="buy:ew:DANA"),
        InlineKeyboardButton("ShopeePay", callback_data="buy:ew:SHOPEEPAY"),
    )
    m.row(
        InlineKeyboardButton("GoPay", callback_data="buy:ew:GOPAY"),
        InlineKeyboardButton("OVO", callback_data="buy:ew:OVO"),
    )
    m.row(
        InlineKeyboardButton("Pulsa + Decoy V1", callback_data="buy:decoy_bal1"),
        InlineKeyboardButton("Pulsa + Decoy V2", callback_data="buy:decoy_bal2"),
    )
    m.row(
        InlineKeyboardButton("QRIS + Decoy (+1K)", callback_data="buy:decoy_qris1"),
        InlineKeyboardButton("QRIS + Decoy Rp0", callback_data="buy:decoy_qris0"),
    )
    m.row(
        InlineKeyboardButton("Klaim Bonus (Bounty)", callback_data="buy:bounty"),
        InlineKeyboardButton("Tukar Poin (Loyalty)", callback_data="buy:loyalty"),
    )
    if option_order != -1:
        m.row(
            InlineKeyboardButton("Kirim Bonus", callback_data="buy:bounty_allot"),
            InlineKeyboardButton("Simpan ke Bookmark", callback_data="buy:bookmark"),
        )
    else:
        m.row(InlineKeyboardButton("Kirim Bonus ke Nomor Lain", callback_data="buy:bounty_allot"))

    st_data = get_state(chat_id)["data"]
    lf = st_data.get("last_feature")
    if lf and lf.get("cb") and lf.get("label"):
        m.row(
            InlineKeyboardButton(lf["label"], callback_data=lf["cb"]),
            InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
        )
    elif st_data.get("current_fc") == family_code and family_code:
        m.row(
            InlineKeyboardButton("Kembali ke Daftar Paket Family", callback_data="fambm:back"),
            InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
        )
    else:
        m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))

    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def send_qris_result(chat_id: int, qris_code: str, title: str, amount: int, message_id: int | None = None):
    qris_b64 = base64.urlsafe_b64encode(qris_code.encode()).decode()
    qris_url = f"https://ki-ar-kod.netlify.app/?data={qris_b64}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=2,
    )
    qr.add_data(qris_code)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    bio.name = "qris.png"
    img.save(bio, "PNG")
    bio.seek(0)

    st = get_state(chat_id)
    last_bot_mid = st["data"].get("last_bot_msg_id")
    for mid_to_del in {message_id, last_bot_mid}:
        if mid_to_del:
            try:
                bot.delete_message(chat_id, mid_to_del)
            except Exception:
                pass

    m = InlineKeyboardMarkup()
    m.row(InlineKeyboardButton("Buka QRIS di Browser", url=qris_url))
    lf = st["data"].get("last_feature")
    if st["data"].get("current_pkg"):
        m.row(InlineKeyboardButton("Kembali ke Detail Paket", callback_data="back_current_pkg"))
    if lf and lf.get("cb") and lf.get("label"):
        m.row(
            InlineKeyboardButton(lf["label"], callback_data=lf["cb"]),
            InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"),
        )
    else:
        m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))

    caption = (
        f"<b>QRIS Pembayaran</b>\n\n"
        f"Paket: {html.escape(title)}\n"
        f"Nominal: <b>Rp {amount:,}</b>\n\n"
        f"Silakan scan gambar QRIS di atas untuk menyelesaikan pembayaran."
    )
    sent = bot.send_photo(chat_id, bio, caption=caption, parse_mode="HTML", reply_markup=m)
    if sent and hasattr(sent, "message_id"):
        st["data"]["last_bot_msg_id"] = sent.message_id


def execute_single_purchase(chat_id: int, mode: str, wallet_number: str = "", custom_amount: int | None = None, target_msisdn: str = "", message_id: int | None = None):
    from app.service.auth import AuthInstance
    from app.client.engsel import get_package
    from app.service.decoy import DecoyInstance
    from app.type_dict import PaymentItem
    from app.client.purchase.balance import settlement_balance
    from app.client.purchase.qris import settlement_qris, get_qris_code
    from app.client.purchase.ewallet import settlement_multipayment
    from app.client.purchase.redeem import settlement_bounty, settlement_loyalty, bounty_allotment

    st = get_state(chat_id)
    cp = st["data"].get("current_pkg")
    if not cp:
        render_home(chat_id, message_id)
        return

    api_key = AuthInstance.api_key
    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        render_welcome_login(chat_id, message_id)
        return

    title = f"{cp['variant_name']} {cp['option_name']}".strip() or cp["option_code"]
    price = cp["price"]
    payment_for = cp["payment_for"]

    payment_items = [
        PaymentItem(
            item_code=cp["option_code"],
            product_type="",
            item_price=price,
            item_name=title,
            tax=0,
            token_confirmation=cp["token_confirmation"],
        )
    ]

    wait_msg = send_or_edit(chat_id, f"Memproses transaksi untuk <b>{html.escape(title)}</b>...", None, message_id)
    active_mid = wait_msg.message_id if (wait_msg and hasattr(wait_msg, "message_id")) else (message_id or st["data"].get("last_bot_msg_id"))
    ret_markup = after_purchase_markup(chat_id)

    try:
        if mode in ("bal", "bal_custom"):
            amt = custom_amount if custom_amount is not None else price
            res = settlement_balance(api_key, tokens, payment_items, payment_for, False, overwrite_amount=amt)
            status = res.get("status") if isinstance(res, dict) else "ERROR"
            msg = res.get("message", "") if isinstance(res, dict) else str(res)
            if status == "SUCCESS":
                send_or_edit(chat_id, f"<b>Pembelian Berhasil</b>\nPaket <b>{html.escape(title)}</b> sedang diproses. Silakan cek di aplikasi MyXL.", ret_markup, active_mid)
            else:
                send_or_edit(chat_id, f"<b>Pembelian Gagal</b>\nStatus: <code>{status}</code>\nPesan: <code>{html.escape(str(msg))}</code>", ret_markup, active_mid)

        elif mode in ("qris", "qris_custom"):
            amt = custom_amount if custom_amount is not None else price
            trx_id = settlement_qris(api_key, tokens, payment_items, payment_for, False, overwrite_amount=amt)
            if not trx_id or not isinstance(trx_id, str):
                send_or_edit(chat_id, "<b>Pembelian Gagal</b>\nGagal membuat transaksi QRIS.", ret_markup, active_mid)
                return
            qris_code = get_qris_code(api_key, tokens, trx_id)
            if not qris_code:
                send_or_edit(chat_id, "<b>Pembelian Gagal</b>\nGagal mengambil kode QRIS.", ret_markup, active_mid)
                return
            send_qris_result(chat_id, qris_code, title, amt, active_mid)

        elif mode.startswith("ew:"):
            method = mode.split(":", 1)[1]
            amt = custom_amount if custom_amount is not None else price
            res = settlement_multipayment(api_key, tokens, payment_items, wallet_number, method, payment_for, False, overwrite_amount=amt)
            if not isinstance(res, dict) or res.get("status") != "SUCCESS":
                send_or_edit(chat_id, f"<b>Gagal membuat pembayaran {method}:</b>\n<code>{html.escape(str(res))}</code>", ret_markup, active_mid)
                return
            deeplink = res.get("data", {}).get("deeplink", "")
            m = InlineKeyboardMarkup()
            if deeplink:
                m.row(InlineKeyboardButton(f"Bayar via {method}", url=deeplink))
            m.row(InlineKeyboardButton("Kembali ke Detail Paket", callback_data="back_current_pkg"))
            lf = st["data"].get("last_feature")
            if lf and lf.get("cb") and lf.get("label"):
                m.row(
                    InlineKeyboardButton(lf["label"], callback_data=lf["cb"]),
                    InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"),
                )
            else:
                m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
            msg_text = (
                f"<b>Tagihan {method} Berhasil Dibuat</b>\n\n"
                + (f"Klik tombol di bawah untuk menyelesaikan pembayaran di aplikasi {method}." if deeplink else "Silakan buka aplikasi OVO Anda untuk konfirmasi pembayaran.")
            )
            send_or_edit(chat_id, msg_text, m, active_mid)

        elif mode in ("decoy_bal1", "decoy_bal2"):
            decoy = DecoyInstance.get_decoy("balance")
            decoy_pkg = get_package(api_key, tokens, decoy["option_code"]) if decoy else None
            if not decoy_pkg:
                send_or_edit(chat_id, "Gagal memuat paket Decoy Balance.", ret_markup, active_mid)
                return
            payment_items.append(
                PaymentItem(
                    item_code=decoy_pkg["package_option"]["package_option_code"],
                    product_type="",
                    item_price=decoy_pkg["package_option"]["price"],
                    item_name=decoy_pkg["package_option"]["name"],
                    tax=0,
                    token_confirmation=decoy_pkg["token_confirmation"],
                )
            )
            overwrite_amt = price + decoy_pkg["package_option"]["price"]
            p_for = "🤫" if mode == "decoy_bal2" else payment_for
            t_idx = 1 if mode == "decoy_bal2" else 0
            res = settlement_balance(api_key, tokens, payment_items, p_for, False, overwrite_amount=overwrite_amt, token_confirmation_idx=t_idx)
            if isinstance(res, dict) and res.get("status") != "SUCCESS":
                err = res.get("message", "")
                if "Bizz-err.Amount.Total" in err and "=" in err:
                    valid_amt = int(err.split("=")[1].strip())
                    res = settlement_balance(
                        api_key, tokens, payment_items, p_for, False,
                        overwrite_amount=valid_amt,
                        token_confirmation_idx=(-1 if mode == "decoy_bal2" else 0),
                    )
            if isinstance(res, dict) and res.get("status") == "SUCCESS":
                send_or_edit(chat_id, "<b>Pembelian Pulsa + Decoy Berhasil</b>\nSilakan cek aplikasi MyXL Anda.", ret_markup, active_mid)
            else:
                status = res.get("status") if isinstance(res, dict) else "ERROR"
                msg = res.get("message", "") if isinstance(res, dict) else str(res)
                send_or_edit(chat_id, f"<b>Pembelian Gagal</b>\nStatus: <code>{status}</code>\nPesan: <code>{html.escape(str(msg))}</code>", ret_markup, active_mid)

        elif mode in ("decoy_qris1", "decoy_qris0"):
            dtype = "qris" if mode == "decoy_qris1" else "qris0"
            decoy = DecoyInstance.get_decoy(dtype)
            decoy_pkg = get_package(api_key, tokens, decoy["option_code"]) if decoy else None
            if not decoy_pkg:
                send_or_edit(chat_id, f"Gagal memuat paket Decoy {dtype}.", ret_markup, active_mid)
                return
            payment_items.append(
                PaymentItem(
                    item_code=decoy_pkg["package_option"]["package_option_code"],
                    product_type="",
                    item_price=decoy_pkg["package_option"]["price"],
                    item_name=decoy_pkg["package_option"]["name"],
                    tax=0,
                    token_confirmation=decoy_pkg["token_confirmation"],
                )
            )
            amt = custom_amount if custom_amount is not None else (price + decoy_pkg["package_option"]["price"])
            trx_id = settlement_qris(api_key, tokens, payment_items, "SHARE_PACKAGE", False, overwrite_amount=amt, token_confirmation_idx=1)
            if not trx_id or not isinstance(trx_id, str):
                send_or_edit(chat_id, f"Gagal membuat QRIS Decoy (Nominal Rp {amt:,}).", ret_markup, active_mid)
                return
            qris_code = get_qris_code(api_key, tokens, trx_id)
            if not qris_code:
                send_or_edit(chat_id, "Gagal mengambil kode QRIS.", ret_markup, active_mid)
                return
            send_qris_result(chat_id, qris_code, f"{title} + Decoy", amt, active_mid)

        elif mode == "bounty":
            res = settlement_bounty(api_key, tokens, cp["token_confirmation"], cp["timestamp"], cp["option_code"], price, cp["variant_name"])
            send_or_edit(chat_id, format_clean_api_result(f"Hasil Klaim Bonus ({title})", res), ret_markup, active_mid)

        elif mode == "loyalty":
            res = settlement_loyalty(api_key, tokens, cp["token_confirmation"], cp["timestamp"], cp["option_code"], price)
            send_or_edit(chat_id, format_clean_api_result(f"Hasil Tukar Poin ({title})", res), ret_markup, active_mid)

        elif mode == "bounty_allot":
            res = bounty_allotment(api_key, tokens, cp["timestamp"], target_msisdn, title, cp["option_code"], cp["token_confirmation"])
            send_or_edit(chat_id, format_clean_api_result(f"Hasil Kirim Bonus ke {target_msisdn}", res), ret_markup, active_mid)

    except Exception as e:
        send_or_edit(chat_id, f"Terjadi kesalahan saat transaksi:\n<code>{html.escape(str(e))}</code>", ret_markup, active_mid)


# ============================================================================
# BOOKMARK, RIWAYAT, NOTIFIKASI, STORE, PROMO REDEEMABLES & SEGMENTS
# ============================================================================

def render_bookmarks(chat_id: int, message_id: int | None = None):
    from app.service.bookmark import BookmarkInstance

    bms = BookmarkInstance.get_bookmarks()
    if not bms:
        send_or_edit(chat_id, "<b>Bookmark</b>\n\nBelum ada paket yang disimpan di Bookmark.", back_home_markup(), message_id)
        return

    lines = [
        f"<b>Daftar Bookmark ({len(bms)} Paket)</b>",
        "Pilih paket di bawah untuk membeli atau tekan Hapus:",
    ]
    m = InlineKeyboardMarkup()
    for idx, b in enumerate(bms):
        fam_n = (b.get("family_name") or "").strip()
        var_n = (b.get("variant_name") or "").strip()
        opt_n = (b.get("option_name") or "").strip()
        btn_title = opt_n or var_n or fam_n or "Paket"
        m.row(
            InlineKeyboardButton(f"{idx+1}. {btn_title}", callback_data=f"bm:open:{idx}"),
            InlineKeyboardButton("Hapus", callback_data=f"bm:del:{idx}"),
        )

    m.row(
        InlineKeyboardButton("Hapus Semua", callback_data="bm:clear_confirm"),
        InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
    )
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def render_history(chat_id: int, message_id: int | None = None):
    from app.service.auth import AuthInstance
    from app.client.engsel import get_transaction_history

    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        render_welcome_login(chat_id, message_id)
        return

    send_or_edit(chat_id, "Sedang memuat riwayat transaksi...", None, message_id)
    try:
        data = get_transaction_history(AuthInstance.api_key, tokens) or {}
        history = data.get("list", [])
    except Exception:
        history = []

    lines = ["<b>Riwayat Transaksi</b>\n"]
    if not history:
        lines.append("Belum ada riwayat transaksi.")
    else:
        for idx, trx in enumerate(history[:12], 1):
            ts = trx.get("timestamp", 0)
            dt_str = (datetime.fromtimestamp(ts) - timedelta(hours=7)).strftime("%d %b %Y %H:%M") if ts else (trx.get("formated_date") or "-")
            lines.append(
                f"<b>{idx}. {html.escape(str(trx.get('title', '-')))}</b> ({html.escape(str(trx.get('price', '-')))})\n"
                f"Tanggal: {dt_str} | Metode: {trx.get('payment_method_label', '-')}\n"
                f"Status: <code>{trx.get('status', '-')} / {trx.get('payment_status', '-')}</code>\n"
            )

    m = InlineKeyboardMarkup()
    m.row(
        InlineKeyboardButton("Cek Transaksi Pending", callback_data="nav:profile"),
        InlineKeyboardButton("Refresh", callback_data="nav:history"),
    )
    m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def render_notifications(chat_id: int, message_id: int | None = None):
    from app.service.auth import AuthInstance
    from app.client.engsel import dashboard_segments, get_notifications

    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        render_welcome_login(chat_id, message_id)
        return

    send_or_edit(chat_id, "Sedang memuat notifikasi...", None, message_id)
    res = dashboard_segments(AuthInstance.api_key, tokens) or {}
    notifs = []
    if isinstance(res, dict):
        notifs = res.get("data", {}).get("notification", {}).get("data", [])

    if not notifs:
        res_alt = get_notifications(AuthInstance.api_key, tokens) or {}
        if isinstance(res_alt, dict):
            d = res_alt.get("data", {})
            if isinstance(d, list):
                notifs = d
            elif isinstance(d, dict):
                notifs = d.get("data", []) or d.get("list", [])

    lines = ["<b>Notifikasi</b>\n"]
    if not notifs:
        lines.append("Tidak ada notifikasi.")
    else:
        for idx, n in enumerate(notifs[:10], 1):
            flag = "[Baru]" if not n.get("is_read") else "[Dibaca]"
            brief = n.get("brief_message") or n.get("title") or "Notifikasi"
            full = n.get("full_message") or n.get("message") or ""
            lines.append(f"<b>{idx}. {flag} {html.escape(str(brief))}</b>\n{html.escape(str(full)[:140])}\n")

    set_step(chat_id, None, notifs=notifs)
    m = InlineKeyboardMarkup()
    if any(not n.get("is_read") for n in notifs):
        m.row(InlineKeyboardButton("Tandai Semua Sudah Dibaca", callback_data="notif:read_all"))
    m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def render_redeemables(chat_id: int, message_id: int | None = None):
    """Tampilkan daftar Promo & Redeemables dari app/client/store/redeemables.py."""
    from app.service.auth import AuthInstance
    from app.client.store.redeemables import get_redeemables

    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        render_welcome_login(chat_id, message_id)
        return

    send_or_edit(chat_id, "Memuat daftar Promo & Redeemables...", None, message_id)
    res = get_redeemables(AuthInstance.api_key, tokens, False) or {}
    data = res.get("data", {}) if isinstance(res, dict) else {}

    lines = ["<b>Promo & Redeemables (Bonus / Loyalty)</b>\n"]
    m = InlineKeyboardMarkup()
    red_items = []

    categories = data.get("categories", []) if isinstance(data, dict) else []
    if categories:
        for cat in categories:
            c_name = cat.get("category_name") or cat.get("name") or "Kategori"
            lines.append(f"<b>• {html.escape(str(c_name))}</b>")
            for r in cat.get("redeemables", []) or cat.get("items", []):
                r_name = r.get("name") or r.get("title") or "Promo"
                r_code = r.get("action_param") or r.get("package_option_code") or r.get("code") or ""
                r_type = r.get("action_type") or ""
                r_price = r.get("price") or r.get("points") or 0
                idx = len(red_items) + 1
                red_items.append({"name": r_name, "code": r_code, "type": r_type})
                lines.append(f"  {idx}. {html.escape(str(r_name))} ({r_price:,}) — <code>{html.escape(str(r_code))}</code>")
                if r_code:
                    m.row(InlineKeyboardButton(f"{idx}. {str(r_name)[:28]}", callback_data=f"red_open:{idx-1}"))
            lines.append("")
    elif isinstance(data, dict) and data:
        # Fallback jika struktur langsung berupa list/dict lain
        raw_list = data.get("redeemables") or data.get("list") or data.get("results") or []
        if isinstance(raw_list, list) and raw_list:
            for idx, r in enumerate(raw_list[:20], 1):
                r_name = r.get("name") or r.get("title") or f"Item #{idx}"
                r_code = r.get("action_param") or r.get("package_option_code") or r.get("code") or ""
                r_type = r.get("action_type") or ""
                red_items.append({"name": r_name, "code": r_code, "type": r_type})
                lines.append(f"{idx}. <b>{html.escape(str(r_name))}</b> — <code>{html.escape(str(r_code))}</code>")
                if r_code:
                    m.row(InlineKeyboardButton(f"{idx}. {str(r_name)[:28]}", callback_data=f"red_open:{idx-1}"))
        else:
            preview = json.dumps(data, indent=2)[:2500]
            lines.append(f"<code>{html.escape(preview)}</code>")
    else:
        lines.append("Tidak ada promo atau bonus redeemable yang tersedia saat ini.")

    set_step(chat_id, None, red_items=red_items)
    m.row(
        InlineKeyboardButton("Store Segments", callback_data="nav:segments"),
        InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
    )
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def render_store_segments(chat_id: int, message_id: int | None = None):
    """Tampilkan daftar Store Segments & Promo Banner dari app/client/store/segments.py."""
    from app.service.auth import AuthInstance
    from app.client.store.segments import get_segments

    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        render_welcome_login(chat_id, message_id)
        return

    send_or_edit(chat_id, "Memuat katalog Store Segments...", None, message_id)
    res = get_segments(AuthInstance.api_key, tokens, False) or {}
    data = res.get("data", {}) if isinstance(res, dict) else {}

    lines = ["<b>Store Segments & Promo Pilihan</b>\n"]
    m = InlineKeyboardMarkup()
    seg_cats = []
    seg_items = []

    raw_segs = []
    if isinstance(data, list):
        raw_segs = data
    elif isinstance(data, dict):
        for k in ("store_segments", "segments", "categories", "list", "results"):
            if isinstance(data.get(k), list):
                raw_segs = data.get(k)
                break

    if raw_segs:
        row_btns = []
        for seg_idx, s in enumerate(raw_segs, 1):
            if not isinstance(s, dict):
                continue
            s_name = s.get("title") or s.get("name") or s.get("label") or f"Segmen #{seg_idx}"
            banners = s.get("banners") or s.get("items") or s.get("packages") or []

            if isinstance(banners, list) and banners:
                lines.append(f"<b>• {html.escape(str(s_name))}</b>")
                for b in banners:
                    if not isinstance(b, dict):
                        continue
                    b_title = (b.get("title") or b.get("name") or "Paket Promo").strip()
                    b_fam = (b.get("family_name") or "").strip()
                    b_desc = (b.get("description") or "").strip()
                    b_val = (b.get("validity") or "").strip()
                    disc_p = b.get("discounted_price") or 0
                    orig_p = b.get("original_price") or 0
                    price = disc_p if (isinstance(disc_p, (int, float)) and disc_p > 0) else (orig_p if isinstance(orig_p, (int, float)) else 0)
                    act_type = str(b.get("action_type") or "PDP").upper()
                    act_param = str(b.get("action_param") or b.get("package_option_code") or b.get("code") or "").strip()

                    item_no = len(seg_items) + 1
                    full_label = f"{b_fam} - {b_title}".strip(" -") if b_fam else b_title
                    price_str = f"Rp {int(price):,}" if price > 0 else "Promo"
                    val_str = f" ({b_val})" if b_val else ""
                    desc_str = f" — <i>{html.escape(b_desc[:60])}</i>" if b_desc else ""

                    lines.append(f"  {item_no}. <b>{html.escape(full_label)}</b> — {price_str}{html.escape(val_str)}{desc_str}")

                    if act_param and len(seg_items) < 30:
                        seg_items.append({
                            "name": full_label,
                            "code": act_param,
                            "action_type": act_type,
                        })
                        short_price = f"{int(price)//1000}k" if price >= 1000 else price_str
                        btn_text = f"{item_no}. {b_title[:18]} ({short_price})"
                        row_btns.append(InlineKeyboardButton(btn_text, callback_data=f"seg_item:{item_no-1}"))
                        if len(row_btns) == 2:
                            m.row(*row_btns)
                            row_btns = []
                lines.append("")
            else:
                s_code = s.get("package_category_code") or s.get("category_code") or s.get("code") or s.get("id") or ""
                if s_code:
                    cat_no = len(seg_cats) + 1
                    lines.append(f"{cat_no}. <b>{html.escape(str(s_name))}</b>")
                    seg_cats.append({"name": str(s_name), "code": str(s_code)})
                    row_btns.append(InlineKeyboardButton(f"Kategori: {str(s_name)[:22]}", callback_data=f"seg_cat:{cat_no-1}"))
                    if len(row_btns) == 2:
                        m.row(*row_btns)
                        row_btns = []

        if row_btns:
            m.row(*row_btns)

        if not seg_items and not seg_cats:
            lines.append("Tidak ada paket atau promo yang tersedia pada Store Segments saat ini.")
    else:
        lines.append("Tidak ada daftar Store Segments yang tersedia saat ini.")

    set_step(chat_id, None, seg_cats=seg_cats, seg_items=seg_items)
    m.row(
        InlineKeyboardButton("Store Packages", callback_data="nav:store_pkg"),
        InlineKeyboardButton("Store Family List", callback_data="nav:store_fam"),
    )
    m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def render_category_families(chat_id: int, cat_code: str, cat_name: str, message_id: int | None = None):
    """Tampilkan daftar Family di dalam suatu Package Category Code menggunakan get_families."""
    from app.service.auth import AuthInstance
    from app.client.engsel import get_families

    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        render_welcome_login(chat_id, message_id)
        return

    send_or_edit(chat_id, f"Memuat daftar Family untuk kategori <b>{html.escape(cat_name)}</b>...", None, message_id)
    data = get_families(AuthInstance.api_key, tokens, cat_code) or {}

    fams = []
    if isinstance(data, list):
        fams = data
    elif isinstance(data, dict):
        for k in ("package_families", "families", "list", "results"):
            if isinstance(data.get(k), list):
                fams = data.get(k)
                break

    lines = [f"<b>Kategori: {html.escape(cat_name)}</b> (<code>{html.escape(cat_code)}</code>)\n"]
    m = InlineKeyboardMarkup()

    if fams:
        for idx, f in enumerate(fams[:25], 1):
            f_name = f.get("name") or f.get("label") or f"Family #{idx}"
            f_code = f.get("package_family_code") or f.get("family_code") or f.get("id") or ""
            lines.append(f"{idx}. <b>{html.escape(str(f_name))}</b> — <code>{html.escape(str(f_code))}</code>")
            if f_code:
                m.row(InlineKeyboardButton(f"{idx}. {str(f_name)[:26]}", callback_data=f"stfam:{f_code}"))
    else:
        lines.append("Tidak ditemukan daftar Family pada kategori ini.")

    m.row(
        InlineKeyboardButton("Kembali ke Segments", callback_data="nav:segments"),
        InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
    )
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def render_store_family_list(chat_id: int, message_id: int | None = None, page: int = 0, reload_data: bool = False, search_query: str | None = None):
    from app.service.auth import AuthInstance
    from app.client.store.search import get_family_list

    active_user = AuthInstance.get_active_user()
    if not active_user:
        render_welcome_login(chat_id, message_id)
        return

    st = get_state(chat_id)
    all_results = st["data"].get("sfl_full")
    if reload_data or not all_results:
        send_or_edit(chat_id, "Memuat daftar Family dari Store...", None, message_id)
        res = get_family_list(AuthInstance.api_key, active_user["tokens"], active_user.get("subscription_type", "PREPAID"), False)
        all_results = (res or {}).get("data", {}).get("results", [])
        st["data"]["sfl_full"] = all_results
        st["data"]["sfl_query"] = ""

    if search_query is not None:
        st["data"]["sfl_query"] = search_query.strip()
    query = st["data"].get("sfl_query", "")

    if query:
        q_low = query.lower()
        results = [f for f in all_results if q_low in f.get("label", "").lower() or q_low in f.get("id", "").lower()]
    else:
        results = all_results

    set_step(chat_id, "SFL_BROWSE")

    if not results:
        m = InlineKeyboardMarkup()
        if query:
            m.row(InlineKeyboardButton("Reset Filter Pencarian", callback_data="sfl_clear_filter"))
        m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
        send_or_edit(chat_id, f"<b>Store Family List</b>\n\nTidak ditemukan Family untuk kata kunci: <code>{html.escape(query)}</code>", m, message_id)
        return

    total_items = len(results)
    total_pages = max(1, (total_items + SFL_PER_PAGE - 1) // SFL_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    st["data"]["sfl_total_pages"] = total_pages
    st["data"]["sfl_page"] = page

    start_idx = page * SFL_PER_PAGE
    end_idx = min(start_idx + SFL_PER_PAGE, total_items)

    filter_info = f" | Filter: <code>{html.escape(query)}</code> ({total_items})" if query else f" (Total {total_items})"
    lines = [
        f"<b>Store Family List</b> — Hal {page+1}/{total_pages}{filter_info}",
        "<i>Ketik nama Family di chat untuk memfilter, atau ketik angka untuk lompat halaman:</i>",
    ]
    m = InlineKeyboardMarkup()
    row_btns = []

    for idx in range(start_idx, end_idx):
        fam = results[idx]
        label = fam.get("label", "Family")
        fcode = fam.get("id", "")
        row_btns.append(InlineKeyboardButton(f"{idx+1}. {label[:22]}", callback_data=f"stfam:{fcode}"))
        if len(row_btns) == 2:
            m.row(*row_btns)
            row_btns = []
    if row_btns:
        m.row(*row_btns)

    if total_pages > 1:
        nav_row = []
        if page >= 5:
            nav_row.append(InlineKeyboardButton("⏪ -5", callback_data=f"sfl_page:{page-5}"))
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"sfl_page:{page-1}"))
        nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages} (Lompat)", callback_data="sfl_jump_prompt"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"sfl_page:{page+1}"))
        if page + 5 < total_pages:
            nav_row.append(InlineKeyboardButton("+5 ⏩", callback_data=f"sfl_page:{page+5}"))
        m.row(*nav_row)

    filter_row = [InlineKeyboardButton("Cari / Filter Nama", callback_data="sfl_search_prompt")]
    if query:
        filter_row.append(InlineKeyboardButton("Reset Filter", callback_data="sfl_clear_filter"))
    m.row(*filter_row)
    m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


def render_store_packages(chat_id: int, message_id: int | None = None, page: int = 0, reload_data: bool = False, search_query: str | None = None):
    from app.service.auth import AuthInstance
    from app.client.store.search import get_store_packages

    active_user = AuthInstance.get_active_user()
    if not active_user:
        render_welcome_login(chat_id, message_id)
        return

    st = get_state(chat_id)
    all_items = st["data"].get("st_pkgs_full")

    if reload_data or not all_items:
        send_or_edit(chat_id, "Memuat seluruh paket dari Store...", None, message_id)
        res = get_store_packages(AuthInstance.api_key, active_user["tokens"], active_user.get("subscription_type", "PREPAID"), False)
        all_items = (res or {}).get("data", {}).get("results_price_only", [])
        st_pkgs = [p.get("action_param", "") for p in all_items]
        st["data"]["st_pkgs_full"] = all_items
        st["data"]["st_pkgs"] = st_pkgs
        st["data"]["sp_query"] = ""

    if search_query is not None:
        st["data"]["sp_query"] = search_query.strip()
    query = st["data"].get("sp_query", "")

    if query:
        q_low = query.lower()
        filtered = [
            (orig_idx, p)
            for orig_idx, p in enumerate(all_items)
            if q_low in p.get("title", "").lower() or q_low in p.get("family_name", "").lower()
        ]
    else:
        filtered = list(enumerate(all_items))

    set_step(chat_id, "SP_BROWSE")

    if not filtered:
        m = InlineKeyboardMarkup()
        if query:
            m.row(InlineKeyboardButton("Reset Filter Pencarian", callback_data="sp_clear_filter"))
        m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
        send_or_edit(chat_id, f"<b>Store Packages</b>\n\nTidak ditemukan paket untuk kata kunci: <code>{html.escape(query)}</code>", m, message_id)
        return

    total_items = len(filtered)
    total_pages = max(1, (total_items + SP_PER_PAGE - 1) // SP_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    st["data"]["sp_total_pages"] = total_pages
    st["data"]["sp_page"] = page

    start_idx = page * SP_PER_PAGE
    end_idx = min(start_idx + SP_PER_PAGE, total_items)

    filter_info = f" | Filter: <code>{html.escape(query)}</code> ({total_items})" if query else f" (Total {total_items} Paket)"
    lines = [
        f"<b>Store Packages</b> — Hal {page+1}/{total_pages}{filter_info}",
        "<i>Ketik nama paket di chat untuk memfilter, atau ketik angka untuk lompat halaman:</i>",
    ]
    m = InlineKeyboardMarkup()
    row_btns = []

    for display_num in range(start_idx, end_idx):
        orig_idx, p = filtered[display_num]
        title = p.get("title", "Paket")
        price = p.get("discounted_price") if p.get("discounted_price", 0) > 0 else p.get("original_price", 0)
        p_label = f"{price//1000}k" if price >= 1000 else f"Rp{price}"
        row_btns.append(InlineKeyboardButton(f"{display_num+1}. {title[:18]} ({p_label})", callback_data=f"stpkg:{orig_idx}"))
        if len(row_btns) == 2:
            m.row(*row_btns)
            row_btns = []
    if row_btns:
        m.row(*row_btns)

    if total_pages > 1:
        nav_row = []
        if page >= 5:
            nav_row.append(InlineKeyboardButton("⏪ -5", callback_data=f"sp_page:{page-5}"))
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"sp_page:{page-1}"))
        nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages} (Lompat)", callback_data="sp_jump_prompt"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"sp_page:{page+1}"))
        if page + 5 < total_pages:
            nav_row.append(InlineKeyboardButton("+5 ⏩", callback_data=f"sp_page:{page+5}"))
        m.row(*nav_row)

    filter_row = [InlineKeyboardButton("Cari / Filter Paket", callback_data="sp_search_prompt")]
    if query:
        filter_row.append(InlineKeyboardButton("Reset Filter", callback_data="sp_clear_filter"))
    m.row(*filter_row)
    m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
    send_or_edit(chat_id, "\n".join(lines), m, message_id)


# ============================================================================
# TOOLS NOMOR: VALIDASI MSISDN, CEK PUK & REGISTRASI DUKCAPIL
# ============================================================================

def render_tools_menu(chat_id: int, message_id: int | None = None):
    set_step(chat_id, None)
    text = (
        "<b>Tools Nomor & Registrasi Kartu</b>\n\n"
        "Pilih layanan utilitas kartu XL yang ingin Anda gunakan:"
    )
    m = InlineKeyboardMarkup()
    m.row(
        InlineKeyboardButton("Validasi Status Nomor", callback_data="nav:val_msisdn"),
        InlineKeyboardButton("Cek / Validasi PUK", callback_data="tools:puk"),
    )
    m.row(
        InlineKeyboardButton("Registrasi Kartu (Dukcapil)", callback_data="tools:dukcapil"),
    )
    m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
    send_or_edit(chat_id, text, m, message_id)


# ============================================================================
# HANDLER PERINTAH (COMMANDS), TOMBOL CALLBACK, DAN INPUT TEKS CHAT
# ============================================================================

@bot.message_handler(commands=["start", "menu", "restart"])
def handle_start(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    first_name = message.from_user.first_name or "User"
    render_home(message.chat.id, user_name=first_name)


@bot.message_handler(commands=["paket"])
def handle_paket_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    render_my_packages(message.chat.id)


@bot.message_handler(commands=["bookmark"])
def handle_bookmark_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    render_bookmarks(message.chat.id)


@bot.message_handler(commands=["optioncode", "oc"])
def handle_optioncode_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    parts = message.text.strip().split(maxsplit=1)
    set_step(message.chat.id, None, last_feature={"label": "Kembali ke Option Code", "cb": "nav:input_opt"})
    if len(parts) > 1 and parts[1].strip():
        render_package_detail(message.chat.id, parts[1].strip(), False, -1)
    else:
        set_step(message.chat.id, "WAIT_OPTION_CODE")
        send_or_edit(
            message.chat.id,
            "<b>Option Code</b>\n\nSilakan ketik dan kirim <b>Option Code</b> paket ke chat:",
            back_home_markup(),
        )


@bot.message_handler(commands=["familycode", "fc"])
def handle_familycode_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    parts = message.text.strip().split(maxsplit=1)
    set_step(message.chat.id, None, fam_parent_nav={"label": "Kembali ke Family Code", "cb": "nav:input_fam"})
    if len(parts) > 1 and parts[1].strip():
        render_family_packages(message.chat.id, parts[1].strip(), None)
    else:
        render_fc_search_menu(message.chat.id)


@bot.message_handler(commands=["store"])
def handle_store_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    render_store_packages(message.chat.id, page=0, reload_data=True, search_query="")


@bot.message_handler(commands=["promo", "redeem"])
def handle_promo_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    render_redeemables(message.chat.id)


@bot.message_handler(commands=["riwayat"])
def handle_riwayat_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    render_history(message.chat.id)


@bot.message_handler(commands=["notifikasi"])
def handle_notifikasi_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    render_notifications(message.chat.id)


@bot.message_handler(commands=["login", "akun"])
def handle_login_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    render_accounts_menu(message.chat.id)


@bot.message_handler(commands=["tools", "validasi"])
def handle_tools_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    render_tools_menu(message.chat.id)


@bot.message_handler(commands=["profil", "pending"])
def handle_profil_cmd(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return
    render_profile_pending(message.chat.id)


@bot.message_handler(commands=["id"])
def handle_id(message):
    bot.reply_to(
        message,
        f"<b>User ID:</b> <code>{message.from_user.id}</code>\n<b>Chat ID:</b> <code>{message.chat.id}</code>",
        parse_mode="HTML",
    )


@bot.message_handler(content_types=["document"])
def handle_document(message):
    if not is_authorized(message.from_user.id):
        return
    doc = message.document
    fname = (doc.file_name or "").lower()
    if fname.endswith(".json") and ("token" in fname or "backup" in fname or "akun" in fname):
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path).decode("utf-8", errors="ignore")
        restore_tokens_from_text(message.chat.id, downloaded)
        return
    if fname.endswith(".env") or "env" in fname:
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path).decode("utf-8", errors="ignore")
        apply_env_text(message.chat.id, downloaded)


def restore_tokens_from_text(chat_id: int, raw_text: str):
    """Restore akun tersimpan dari file refresh-tokens.json atau teks format 628xxx:refresh_token tanpa OTP."""
    from app.service.auth import AuthInstance
    restored = 0
    failed = 0
    try:
        data = json.loads(raw_text)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("number") and item.get("refresh_token"):
                    if AuthInstance.add_refresh_token(
                        int(item["number"]),
                        str(item["refresh_token"]).strip(),
                        saved_ua=str(item.get("ua") or ""),
                        saved_fp=str(item.get("ax_fp") or ""),
                    ):
                        restored += 1
                    else:
                        failed += 1
    except Exception:
        for line in raw_text.splitlines():
            line = line.strip()
            if ":" in line:
                num_part, tok_part = line.split(":", 1)
                num_clean = normalize_phone(num_part)
                if num_clean.startswith("628") and tok_part.strip():
                    if AuthInstance.add_refresh_token(int(num_clean), tok_part.strip()):
                        restored += 1
                    else:
                        failed += 1

    if restored > 0:
        msg = f"<b>Restore Berhasil!</b>\n<b>{restored}</b> akun berhasil dipulihkan menggunakan Refresh Token tanpa perlu OTP."
        if failed > 0:
            msg += f"\n({failed} token gagal/kadaluarsa)"
        bot.send_message(chat_id, msg, parse_mode="HTML")
        render_home(chat_id)
    else:
        bot.send_message(
            chat_id,
            "<b>Restore Gagal</b>\nPastikan file <code>refresh-tokens.json</code> atau teks format <code>628xxx:refresh_token</code> valid dan belum kadaluarsa.",
            parse_mode="HTML",
            reply_markup=back_home_markup(),
        )


def apply_env_text(chat_id: int, env_text: str):
    count = 0
    for line in env_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k in REQUIRED_ENV_KEYS and v:
            save_env_key(k, v)
            count += 1

    if count > 0:
        reload_app_modules()
        bot.send_message(
            chat_id,
            f"Berhasil menyimpan dan menerapkan <b>{count}</b> variabel ke <code>.env</code> secara otomatis.",
            parse_mode="HTML",
        )
        render_home(chat_id)
    else:
        bot.send_message(chat_id, "Tidak ditemukan variabel .env yang valid.")


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if not is_authorized(call.from_user.id):
        bot.answer_callback_query(call.id, "Akses ditolak.", show_alert=True)
        return

    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    data = call.data or ""
    user_first_name = call.from_user.first_name or "User"

    if data in ("acc:login_popup", "acc:add"):
        trigger_login_popup(call)
        return

    if data == "sp_jump_prompt":
        tot_p = get_state(chat_id)["data"].get("sp_total_pages", 1)
        set_step(chat_id, "SP_BROWSE", sp_last_msg_id=msg_id)
        bot.answer_callback_query(
            call.id,
            f"Ketik angka halaman (1 - {tot_p}) di kolom chat untuk langsung melompat ke halaman tersebut.",
            show_alert=True,
        )
        return

    if data == "sp_search_prompt":
        set_step(chat_id, "SP_BROWSE", sp_last_msg_id=msg_id)
        bot.answer_callback_query(
            call.id,
            "Ketik nama paket atau kata kunci (contoh: xtra / flex / 20gb) di kolom chat untuk memfilter daftar.",
            show_alert=True,
        )
        return

    if data == "sfl_jump_prompt":
        tot_p = get_state(chat_id)["data"].get("sfl_total_pages", 1)
        set_step(chat_id, "SFL_BROWSE", sfl_last_msg_id=msg_id)
        bot.answer_callback_query(
            call.id,
            f"Ketik angka halaman (1 - {tot_p}) di kolom chat untuk langsung melompat ke halaman tersebut.",
            show_alert=True,
        )
        return

    if data == "sfl_search_prompt":
        set_step(chat_id, "SFL_BROWSE", sfl_last_msg_id=msg_id)
        bot.answer_callback_query(
            call.id,
            "Ketik nama Family di kolom chat untuk memfilter Store Family List.",
            show_alert=True,
        )
        return

    if data == "fambm:page_info":
        st = get_state(chat_id)
        sel_count = len(st["data"].get("bm_selected", []))
        bot.answer_callback_query(call.id, f"Terpilih: {sel_count} paket untuk di-bookmark", show_alert=True)
        return

    from app.service.auth import AuthInstance
    from app.client.engsel import get_family, unsubscribe, get_notification_detail
    from app.service.bookmark import BookmarkInstance

    if data == "fambm:save":
        st = get_state(chat_id)
        pkg_options = st["data"].get("fam_options", [])
        selected: list[int] = st["data"].get("bm_selected", [])
        if not selected:
            bot.answer_callback_query(call.id, "Pilih minimal 1 paket terlebih dahulu!", show_alert=True)
            return

        added_count = 0
        exist_count = 0
        for idx in selected:
            if 0 <= idx < len(pkg_options):
                opt = pkg_options[idx]
                ok = BookmarkInstance.add_bookmark(
                    opt["family_code"],
                    opt["family_name"],
                    opt["is_enterprise"],
                    opt["variant_name"],
                    opt["option_name"],
                    opt["order"],
                    option_code=opt.get("code", ""),
                    reorder_if_exists=True,
                )
                if ok:
                    added_count += 1
                else:
                    exist_count += 1

        st["data"]["bm_selected"] = []
        info_msg = f"Berhasil menyimpan {added_count} paket ke Bookmark!"
        if exist_count > 0:
            info_msg += f" ({exist_count} paket sudah ada sebelumnya)"
        bot.answer_callback_query(call.id, info_msg, show_alert=True)
        render_family_packages(chat_id, st["data"].get("current_fc", ""), None, msg_id, use_cache=True, page=st["data"].get("fam_page", 0))
        return

    if data == "recfc:clear":
        clear_recent_fc()
        bot.answer_callback_query(call.id, "Riwayat Family Code berhasil dihapus.", show_alert=True)
        render_fc_search_menu(chat_id, msg_id)
        return

    if data == "acc:refresh_token":
        ok = AuthInstance.renew_active_user_token()
        bot.answer_callback_query(
            call.id,
            "Sesi token akun aktif berhasil diperbarui!" if ok else "Gagal memperbarui token. Silakan login ulang jika sesi kadaluarsa.",
            show_alert=True,
        )
        render_home(chat_id, msg_id, user_name=user_first_name)
        return

    bot.answer_callback_query(call.id)

    if data == "nav:home":
        render_home(chat_id, msg_id, user_name=user_first_name)
    elif data == "acc:backup":
        from app.service.auth import TOKENS_FILE
        AuthInstance.load_tokens()
        if not AuthInstance.refresh_tokens:
            send_or_edit(chat_id, "Belum ada akun tersimpan untuk di-backup.", back_home_markup(), msg_id)
        else:
            lines = [
                "<b>Backup Nomor & Refresh Token</b>\n",
                "<i>Simpan file atau teks di bawah ini. Saat ganti server/zip baru, cukup kirim balik file JSON atau paste baris di bawah ke bot (tidak perlu login OTP lagi):</i>\n",
            ]
            for idx, u in enumerate(AuthInstance.refresh_tokens, 1):
                lines.append(f"{idx}. <code>{u['number']}:{u['refresh_token']}</code>")
            bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")
            if os.path.exists(TOKENS_FILE):
                with open(TOKENS_FILE, "rb") as tf:
                    bot.send_document(chat_id, tf, caption="Backup Akun MyXL (refresh-tokens.json) — Teruskan file ini ke bot untuk Restore tanpa OTP.")
    elif data == "acc:restore_prompt":
        set_step(chat_id, "WAIT_RESTORE_TOKEN")
        m = InlineKeyboardMarkup()
        m.row(
            InlineKeyboardButton("Kembali ke Kelola Akun", callback_data="nav:accounts"),
            InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
        )
        send_or_edit(
            chat_id,
            "<b>Restore Nomor (Tanpa OTP)</b>\n\n"
            "Silakan <b>kirim/teruskan file <code>refresh-tokens.json</code></b> ke chat ini, ATAU tempelkan teks dengan format:\n"
            "<code>6281234567890:refresh_token_kamu</code>",
            m,
            msg_id,
        )
    elif data == "nav:accounts":
        render_accounts_menu(chat_id, msg_id)
    elif data == "nav:profile":
        render_profile_pending(chat_id, msg_id)
    elif data == "nav:tools":
        render_tools_menu(chat_id, msg_id)
    elif data == "nav:redeemables":
        render_redeemables(chat_id, msg_id)
    elif data == "nav:segments":
        render_store_segments(chat_id, msg_id)

    elif data.startswith("acc:set:"):
        num = int(data.split(":")[2])
        send_or_edit(chat_id, f"Mengaktifkan akun <code>{num}</code>...", None, msg_id)
        AuthInstance.set_active_user(num)
        render_home(chat_id, msg_id, user_name=user_first_name)
    elif data.startswith("acc:del:"):
        num = int(data.split(":")[2])
        AuthInstance.remove_refresh_token(num)
        render_accounts_menu(chat_id, msg_id)
    elif data == "otp:resend":
        phone = get_state(chat_id)["data"].get("login_phone")
        if phone:
            process_phone_input(chat_id, phone)
        else:
            render_welcome_login(chat_id, msg_id, user_name=user_first_name)

    elif data.startswith("pend:qris:"):
        from app.client.purchase.qris import get_qris_code
        trx_id = data.split(":", 2)[2]
        tokens = AuthInstance.get_active_tokens()
        qris_code = get_qris_code(AuthInstance.api_key, tokens, trx_id)
        if qris_code:
            send_qris_result(chat_id, qris_code, f"Transaksi Pending ({trx_id})", 0)
        else:
            bot.send_message(chat_id, f"Gagal mengambil kode QRIS untuk ID <code>{html.escape(trx_id)}</code>.", parse_mode="HTML")

    elif data == "nav:my_pkg":
        render_my_packages(chat_id, msg_id)
    elif data.startswith("mypkg:view:"):
        idx = int(data.split(":")[2])
        my_pkgs = get_state(chat_id)["data"].get("my_pkgs", [])
        if 0 <= idx < len(my_pkgs):
            set_step(chat_id, None, last_feature={"label": "Kembali ke Paket Aktif", "cb": "nav:my_pkg"})
            render_package_detail(chat_id, my_pkgs[idx]["quota_code"], False, -1, msg_id)
    elif data.startswith("mypkg:addons:"):
        idx = int(data.split(":")[2])
        my_pkgs = get_state(chat_id)["data"].get("my_pkgs", [])
        if 0 <= idx < len(my_pkgs):
            render_package_addons(chat_id, my_pkgs[idx]["quota_code"], my_pkgs[idx]["name"], msg_id)
    elif data.startswith("mypkg:del:"):
        idx = int(data.split(":")[2])
        my_pkgs = get_state(chat_id)["data"].get("my_pkgs", [])
        if 0 <= idx < len(my_pkgs):
            pkg = my_pkgs[idx]
            m = InlineKeyboardMarkup()
            m.row(
                InlineKeyboardButton("Ya, Stop Paket", callback_data=f"mypkg:confirm_del:{idx}"),
                InlineKeyboardButton("Batal", callback_data="nav:my_pkg"),
            )
            send_or_edit(chat_id, f"Apakah Anda yakin ingin berhenti berlangganan dari paket <b>{html.escape(pkg['name'])}</b>?", m, msg_id)
    elif data.startswith("mypkg:confirm_del:"):
        idx = int(data.split(":")[2])
        my_pkgs = get_state(chat_id)["data"].get("my_pkgs", [])
        if 0 <= idx < len(my_pkgs):
            pkg = my_pkgs[idx]
            tokens = AuthInstance.get_active_tokens()
            ok = unsubscribe(AuthInstance.api_key, tokens, pkg["quota_code"], pkg["domain"], pkg["sub_type"])
            msg = f"Berhasil berhenti berlangganan paket <b>{html.escape(pkg['name'])}</b>." if ok else f"Gagal berhenti berlangganan paket <b>{html.escape(pkg['name'])}</b>."
            m = InlineKeyboardMarkup()
            m.row(
                InlineKeyboardButton("Kembali ke Paket Aktif", callback_data="nav:my_pkg"),
                InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
            )
            send_or_edit(chat_id, msg, m, msg_id)

    elif data == "nav:input_opt":
        set_step(chat_id, "WAIT_OPTION_CODE", last_feature={"label": "Kembali ke Option Code", "cb": "nav:input_opt"})
        send_or_edit(chat_id, "<b>Option Code</b>\n\nSilakan ketik dan kirim <b>Option Code</b> paket ke chat:", back_home_markup(), msg_id)
    elif data == "nav:input_fam":
        set_step(chat_id, None, fam_parent_nav={"label": "Kembali ke Family Code", "cb": "nav:input_fam"})
        render_fc_search_menu(chat_id, msg_id)
    elif data.startswith("recfc:open:"):
        idx = int(data.split(":")[2])
        recent_list = load_recent_fc()
        if 0 <= idx < len(recent_list):
            item = recent_list[idx]
            set_step(chat_id, None, fam_parent_nav={"label": "Kembali ke Family Code", "cb": "nav:input_fam"})
            render_family_packages(chat_id, item["family_code"], item.get("is_enterprise"), msg_id)
    elif data.startswith("famopt:"):
        idx = int(data.split(":")[1])
        opts = get_state(chat_id)["data"].get("fam_options", [])
        if 0 <= idx < len(opts):
            o = opts[idx]
            set_step(chat_id, None, last_feature={"label": "Kembali ke Daftar Paket Family", "cb": "fambm:back"})
            render_package_detail(chat_id, o["code"], o["is_enterprise"], o["order"], msg_id)

    elif data.startswith("fambm:mode:"):
        page = int(data.split(":")[2])
        render_family_bulk_bookmark(chat_id, msg_id, page=page)
    elif data.startswith("fambm:toggle:"):
        idx = int(data.split(":")[2])
        st = get_state(chat_id)
        selected: list[int] = st["data"].get("bm_selected", [])
        if idx in selected:
            selected.remove(idx)
        else:
            selected.append(idx)
        st["data"]["bm_selected"] = selected
        page = st["data"].get("fambm_page", 0)
        render_family_bulk_bookmark(chat_id, msg_id, page=page)
    elif data == "fambm:all":
        st = get_state(chat_id)
        opts = st["data"].get("fam_options", [])
        st["data"]["bm_selected"] = list(range(len(opts)))
        page = st["data"].get("fambm_page", 0)
        render_family_bulk_bookmark(chat_id, msg_id, page=page)
    elif data == "fambm:none":
        st = get_state(chat_id)
        st["data"]["bm_selected"] = []
        page = st["data"].get("fambm_page", 0)
        render_family_bulk_bookmark(chat_id, msg_id, page=page)
    elif data.startswith("fampage:"):
        arg = data.split(":")[1]
        st = get_state(chat_id)
        fc = st["data"].get("current_fc", "")
        if arg != "info" and fc:
            render_family_packages(chat_id, fc, None, msg_id, use_cache=True, page=int(arg))
    elif data == "fambm:back":
        st = get_state(chat_id)
        fc = st["data"].get("current_fc", "")
        cur_p = st["data"].get("fam_page", 0)
        if fc:
            render_family_packages(chat_id, fc, None, msg_id, use_cache=True, page=cur_p)
        else:
            render_fc_search_menu(chat_id, msg_id)

    elif data == "back_current_pkg":
        cp = get_state(chat_id)["data"].get("current_pkg")
        if cp and cp.get("option_code"):
            render_package_detail(chat_id, cp["option_code"], cp.get("is_enterprise", False), cp.get("option_order", -1), msg_id)
        else:
            render_home(chat_id, msg_id, user_name=user_first_name)
    elif data.startswith("back_pkg:"):
        ocode = data.split(":", 1)[1]
        render_package_detail(chat_id, ocode, False, -1, msg_id)
    elif data.startswith("addon_open:"):
        idx = int(data.split(":")[1])
        addons_cache = get_state(chat_id)["data"].get("addons_cache", [])
        if 0 <= idx < len(addons_cache):
            item = addons_cache[idx]
            a_code = item.get("package_option_code") or item.get("option_code") or item.get("code") or ""
            if a_code:
                render_package_detail(chat_id, a_code, False, -1, msg_id)

    elif data.startswith("buy:"):
        act = data[4:]
        cp = get_state(chat_id)["data"].get("current_pkg")
        if act == "bookmark":
            if cp:
                ok = BookmarkInstance.add_bookmark(
                    cp["family_code"], cp["family_name"], cp["is_enterprise"],
                    cp["variant_name"], cp["option_name"], cp["option_order"],
                    option_code=cp.get("option_code", ""),
                )
                bot.answer_callback_query(call.id, "Paket berhasil disimpan ke Bookmark!" if ok else "Paket sudah ada di Bookmark.", show_alert=True)
        elif act == "addons":
            if cp:
                title = f"{cp['variant_name']} {cp['option_name']}".strip() or "Paket"
                render_package_addons(chat_id, cp["option_code"], title, msg_id)
        elif act == "bounty_allot":
            set_step(chat_id, "WAIT_BOUNTY_ALLOT_MSISDN", prompt_msg_id=msg_id)
            send_or_edit(
                chat_id,
                "<b>Kirim Bonus (Bounty Allotment)</b>\n\nSilakan ketik dan kirim <b>nomor XL tujuan</b> (contoh: <code>081234567890</code>):",
                after_purchase_markup(chat_id),
                msg_id,
            )
        elif act in ("ew:DANA", "ew:OVO"):
            m_name = act.split(":")[1]
            set_step(chat_id, "WAIT_EWALLET_NUM", buy_mode=act, prompt_msg_id=msg_id)
            send_or_edit(chat_id, f"Silakan ketik dan kirim nomor <b>{m_name}</b> Anda (contoh: <code>081234567890</code>):", after_purchase_markup(chat_id), msg_id)
        elif act in ("decoy_qris1", "decoy_qris0", "bal_custom", "qris_custom"):
            set_step(chat_id, "WAIT_CUSTOM_AMOUNT", buy_mode=act, prompt_msg_id=msg_id)
            m = InlineKeyboardMarkup()
            m.row(InlineKeyboardButton("Gunakan Nominal Default", callback_data=f"exec_default:{act}"))
            m.row(InlineKeyboardButton("Kembali ke Detail Paket", callback_data="back_current_pkg"))
            lf = get_state(chat_id)["data"].get("last_feature")
            if lf and lf.get("cb") and lf.get("label"):
                m.row(
                    InlineKeyboardButton(lf["label"], callback_data=lf["cb"]),
                    InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
                )
            else:
                m.row(InlineKeyboardButton("Kembali ke Menu Utama", callback_data="nav:home"))
            send_or_edit(
                chat_id,
                "<b>Input Nominal Pembayaran</b>\n\n"
                "Ketik nominal pembayaran baru (angka saja, contoh: <code>10000</code>) jika ingin mengubah harga/nominal, atau klik tombol <b>Gunakan Nominal Default</b> di bawah:",
                m,
                msg_id,
            )
        else:
            execute_single_purchase(chat_id, act, message_id=msg_id)

    elif data.startswith("exec_default:"):
        act = data.split(":", 1)[1]
        set_step(chat_id, None)
        execute_single_purchase(chat_id, act, message_id=msg_id)

    elif data == "nav:bookmark":
        render_bookmarks(chat_id, msg_id)
    elif data == "bm:clear_confirm":
        m = InlineKeyboardMarkup()
        m.row(
            InlineKeyboardButton("Ya, Hapus Semua", callback_data="bm:clear_all"),
            InlineKeyboardButton("Batal", callback_data="nav:bookmark"),
        )
        send_or_edit(chat_id, "Apakah Anda yakin ingin menghapus <b>seluruh paket</b> dari Bookmark?", m, msg_id)
    elif data == "bm:clear_all":
        BookmarkInstance.clear_bookmarks()
        render_bookmarks(chat_id, msg_id)
    elif data.startswith("bm:open:"):
        idx = int(data.split(":")[2])
        bms = BookmarkInstance.get_bookmarks()
        if 0 <= idx < len(bms):
            bm = bms[idx]
            set_step(chat_id, None, last_feature={"label": "Kembali ke Bookmark", "cb": "nav:bookmark"})
            opt_code = bm.get("option_code") or None
            if not opt_code:
                fam_data = get_family(AuthInstance.api_key, AuthInstance.get_active_tokens(), bm["family_code"], bm["is_enterprise"])
                if not fam_data:
                    fam_data = get_family(AuthInstance.api_key, AuthInstance.get_active_tokens(), bm["family_code"], None)
                if fam_data:
                    for v in fam_data.get("package_variants", []):
                        if v.get("name") == bm.get("variant_name"):
                            for o in v.get("package_options", []):
                                if bm.get("option_name") and o.get("name") == bm.get("option_name"):
                                    opt_code = o.get("package_option_code")
                                    break
                                if o.get("order") == bm.get("order"):
                                    opt_code = o.get("package_option_code")
                            if opt_code:
                                break
            if opt_code:
                render_package_detail(chat_id, opt_code, bm["is_enterprise"], bm["order"], msg_id)
            else:
                send_or_edit(chat_id, "Gagal memuat opsi paket dari Bookmark.", after_purchase_markup(chat_id, include_pkg_detail=False), msg_id)
    elif data.startswith("bm:del:"):
        idx = int(data.split(":")[2])
        BookmarkInstance.remove_bookmark_by_index(idx)
        render_bookmarks(chat_id, msg_id)

    elif data == "nav:history":
        render_history(chat_id, msg_id)
    elif data == "nav:notif":
        render_notifications(chat_id, msg_id)
    elif data == "notif:read_all":
        notifs = get_state(chat_id)["data"].get("notifs", [])
        tokens = AuthInstance.get_active_tokens()
        for n in notifs:
            if not n.get("is_read"):
                get_notification_detail(AuthInstance.api_key, tokens, n.get("notification_id"))
        render_notifications(chat_id, msg_id)

    elif data.startswith("red_open:"):
        idx = int(data.split(":")[1])
        red_items = get_state(chat_id)["data"].get("red_items", [])
        if 0 <= idx < len(red_items):
            item = red_items[idx]
            code = item.get("code", "")
            rtype = str(item.get("type", "")).upper()
            if "FAMILY" in rtype or len(code) == 36 and "-" in code:
                set_step(chat_id, None, fam_parent_nav={"label": "Kembali ke Promo", "cb": "nav:redeemables"})
                render_family_packages(chat_id, code, None, msg_id)
            else:
                set_step(chat_id, None, last_feature={"label": "Kembali ke Promo", "cb": "nav:redeemables"})
                render_package_detail(chat_id, code, False, -1, msg_id)

    elif data.startswith("seg_cat:"):
        idx = int(data.split(":")[1])
        seg_cats = get_state(chat_id)["data"].get("seg_cats", [])
        if 0 <= idx < len(seg_cats):
            cat = seg_cats[idx]
            render_category_families(chat_id, cat["code"], cat["name"], msg_id)
    elif data.startswith("seg_item:"):
        idx = int(data.split(":")[1])
        seg_items = get_state(chat_id)["data"].get("seg_items", [])
        if 0 <= idx < len(seg_items):
            item = seg_items[idx]
            code = item.get("code", "")
            atype = str(item.get("action_type", "PDP")).upper()
            if atype in ("PLP", "FAMILY", "PACKAGE_FAMILY") or (len(code) == 36 and "-" in code and atype != "PDP"):
                set_step(chat_id, None, fam_parent_nav={"label": "Kembali ke Store Segments", "cb": "nav:segments"})
                render_family_packages(chat_id, code, None, msg_id)
            elif atype in ("CATEGORY", "PACKAGE_CATEGORY"):
                render_category_families(chat_id, code, item.get("name", "Kategori"), msg_id)
            else:
                set_step(chat_id, None, last_feature={"label": "Kembali ke Store Segments", "cb": "nav:segments"})
                render_package_detail(chat_id, code, False, -1, msg_id)

    elif data == "nav:store_fam":
        render_store_family_list(chat_id, msg_id, page=0, reload_data=True, search_query="")
    elif data == "sfl_clear_filter":
        render_store_family_list(chat_id, msg_id, page=0, reload_data=False, search_query="")
    elif data.startswith("sfl_page:"):
        page = int(data.split(":")[1])
        render_store_family_list(chat_id, msg_id, page=page, reload_data=False)
    elif data.startswith("stfam:"):
        fcode = data.split(":", 1)[1]
        cur_sfl_page = get_state(chat_id)["data"].get("sfl_page", 0)
        set_step(chat_id, None, fam_parent_nav={"label": "Kembali ke Store Family List", "cb": f"sfl_page:{cur_sfl_page}"})
        render_family_packages(chat_id, fcode, False, msg_id)

    elif data == "nav:store_pkg":
        render_store_packages(chat_id, msg_id, page=0, reload_data=True, search_query="")
    elif data == "sp_clear_filter":
        render_store_packages(chat_id, msg_id, page=0, reload_data=False, search_query="")
    elif data.startswith("sp_page:"):
        page = int(data.split(":")[1])
        render_store_packages(chat_id, msg_id, page=page, reload_data=False)
    elif data.startswith("stpkg:"):
        idx = int(data.split(":")[1])
        st_data = get_state(chat_id)["data"]
        st_pkgs = st_data.get("st_pkgs", [])
        if 0 <= idx < len(st_pkgs):
            cur_sp_page = st_data.get("sp_page", 0)
            set_step(chat_id, None, last_feature={"label": "Kembali ke Store Packages", "cb": f"sp_page:{cur_sp_page}"})
            render_package_detail(chat_id, st_pkgs[idx], False, -1, msg_id)

    # ---- TOOLS & REGISTRASI CALLBACKS ----
    elif data == "nav:val_msisdn":
        set_step(chat_id, "WAIT_VALIDATE_MSISDN")
        send_or_edit(chat_id, "<b>Validasi Status Nomor</b>\n\nSilakan ketik dan kirim nomor XL yang ingin dicek:", back_home_markup(), msg_id)
    elif data == "tools:puk":
        set_step(chat_id, "WAIT_PUK_MSISDN")
        m = InlineKeyboardMarkup()
        m.row(InlineKeyboardButton("Batal", callback_data="nav:tools"))
        send_or_edit(
            chat_id,
            "<b>Cek / Validasi PUK (1/2)</b>\n\nSilakan ketik dan kirim <b>nomor XL</b> yang ingin divalidasi PUK-nya:",
            m,
            msg_id,
        )
    elif data == "tools:dukcapil":
        set_step(chat_id, "WAIT_DUKCAPIL_MSISDN")
        m = InlineKeyboardMarkup()
        m.row(InlineKeyboardButton("Batal", callback_data="nav:tools"))
        send_or_edit(
            chat_id,
            "<b>Registrasi Kartu Dukcapil (1/3)</b>\n\nSilakan ketik dan kirim <b>nomor XL</b> yang ingin diregistrasi:",
            m,
            msg_id,
        )


def process_phone_input(chat_id: int, raw_phone: str):
    from app.client.ciam import get_otp

    phone = normalize_phone(raw_phone)
    if not phone.startswith("628") or len(phone) < 10 or len(phone) > 14:
        m = InlineKeyboardMarkup()
        m.row(InlineKeyboardButton("Login / Tambah Akun", callback_data="acc:login_popup"))
        bot.send_message(
            chat_id,
            "<b>Format Nomor Tidak Valid</b>\nPastikan nomor XL kamu benar (contoh: <code>081234567890</code> atau <code>6281234567890</code>).",
            parse_mode="HTML",
            reply_markup=m,
        )
        return

    wait_msg = bot.send_message(chat_id, f"Meminta kode OTP SMS untuk nomor <code>{phone}</code>...", parse_mode="HTML")
    try:
        sub_id = get_otp(phone)
        if not sub_id:
            m = InlineKeyboardMarkup()
            m.row(InlineKeyboardButton("Coba Lagi / Ganti Nomor", callback_data="acc:login_popup"))
            bot.edit_message_text(
                f"<b>Gagal Meminta OTP untuk <code>{phone}</code></b>\n\n"
                "Pastikan nomor XL aktif, tidak sedang terkena limit OTP, dan konfigurasi <code>.env</code> sudah benar.",
                chat_id=chat_id,
                message_id=wait_msg.message_id,
                parse_mode="HTML",
                reply_markup=m,
            )
            return

        set_step(chat_id, "WAIT_OTP", login_phone=phone)
        m = InlineKeyboardMarkup()
        m.row(
            InlineKeyboardButton("Kirim Ulang OTP", callback_data="otp:resend"),
            InlineKeyboardButton("Ganti Nomor", callback_data="acc:login_popup"),
        )
        bot.edit_message_text(
            f"<b>Kode OTP Terkirim</b>\n\n"
            f"Kode OTP telah dikirim via SMS ke nomor <code>{phone}</code>.\n"
            f"Silakan ketik dan kirim <b>6 digit angka OTP</b> ke chat ini:",
            chat_id=chat_id,
            message_id=wait_msg.message_id,
            parse_mode="HTML",
            reply_markup=m,
        )
    except Exception as e:
        bot.edit_message_text(
            f"Error saat meminta OTP: <code>{html.escape(str(e))}</code>",
            chat_id=chat_id,
            message_id=wait_msg.message_id,
            parse_mode="HTML",
        )


def process_otp_input(chat_id: int, raw_otp: str, user_name: str | None = None):
    from app.service.auth import AuthInstance
    from app.client.ciam import submit_otp

    otp = re.sub(r"[^0-9]", "", raw_otp.strip())
    if len(otp) != 6:
        bot.send_message(chat_id, "Kode OTP harus terdiri dari <b>6 digit angka</b>. Silakan ketik ulang kode OTP kamu:", parse_mode="HTML")
        return

    phone = get_state(chat_id)["data"].get("login_phone")
    if not phone:
        render_welcome_login(chat_id, user_name=user_name)
        return

    wait_msg = bot.send_message(chat_id, "Memverifikasi kode OTP...", parse_mode="HTML")
    try:
        tokens = submit_otp(AuthInstance.api_key, "SMS", phone, otp)
        if not tokens or "refresh_token" not in tokens:
            m = InlineKeyboardMarkup()
            m.row(
                InlineKeyboardButton("Kirim Ulang OTP", callback_data="otp:resend"),
                InlineKeyboardButton("Ganti Nomor", callback_data="acc:login_popup"),
            )
            bot.edit_message_text(
                "<b>Kode OTP Salah atau Kadaluarsa</b>\nSilakan periksa kembali SMS kamu dan kirim ulang 6 digit OTP:",
                chat_id=chat_id,
                message_id=wait_msg.message_id,
                parse_mode="HTML",
                reply_markup=m,
            )
            return

        AuthInstance.add_refresh_token(int(phone), tokens.get("refresh_token", ""), initial_tokens=tokens, saved_ua=tokens.get("_used_ua", ""), saved_fp=tokens.get("_used_fp", ""))
        set_step(chat_id, None)
        bot.edit_message_text(
            f"<b>Login Berhasil</b>\nNomor <code>{phone}</code> telah disimpan dan diaktifkan.",
            chat_id=chat_id,
            message_id=wait_msg.message_id,
            parse_mode="HTML",
        )
        render_home(chat_id, user_name=user_name)
    except Exception as e:
        bot.edit_message_text(
            f"Gagal verifikasi OTP: <code>{html.escape(str(e))}</code>",
            chat_id=chat_id,
            message_id=wait_msg.message_id,
            parse_mode="HTML",
        )


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "Anda tidak memiliki akses ke bot ini.")
        return

    chat_id = message.chat.id
    text = message.text.strip()
    first_name = message.from_user.first_name or "User"

    if "BASE_API_URL=" in text and "BASE_CIAM_URL=" in text:
        apply_env_text(chat_id, text)
        return

    st = get_state(chat_id)
    step = st.get("step")

    # Deteksi otomatis jika pengguna langsung menempelkan (paste) Family Code UUID kapan saja di chat
    if re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", text):
        set_step(chat_id, None, fam_parent_nav={"label": "Kembali ke Family Code", "cb": "nav:input_fam"})
        render_family_packages(chat_id, text, None)
        return

    if step == "WAIT_RESTORE_TOKEN":
        set_step(chat_id, None)
        restore_tokens_from_text(chat_id, text)
        return

    if step == "WAIT_PHONE":
        process_phone_input(chat_id, text)
    elif step == "WAIT_OTP":
        process_otp_input(chat_id, text, user_name=first_name)
    elif step == "WAIT_OPTION_CODE":
        set_step(chat_id, None, last_feature={"label": "Kembali ke Option Code", "cb": "nav:input_opt"})
        render_package_detail(chat_id, text, False, -1)
    elif step == "WAIT_FAMILY_CODE":
        set_step(chat_id, None, fam_parent_nav={"label": "Kembali ke Family Code", "cb": "nav:input_fam"})
        render_family_packages(chat_id, text, None)
    elif step == "SP_BROWSE":
        if text.isdigit():
            target_page = max(0, int(text) - 1)
            render_store_packages(chat_id, page=target_page, reload_data=False)
        else:
            render_store_packages(chat_id, page=0, reload_data=False, search_query=text)
    elif step == "SFL_BROWSE":
        if text.isdigit():
            target_page = max(0, int(text) - 1)
            render_store_family_list(chat_id, page=target_page, reload_data=False)
        else:
            render_store_family_list(chat_id, page=0, reload_data=False, search_query=text)
    elif step == "WAIT_EWALLET_NUM":
        w_num = re.sub(r"[^0-9]", "", text)
        if w_num.startswith("628"):
            w_num = "08" + w_num[3:]
        if not w_num.startswith("08") or len(w_num) < 10:
            bot.send_message(chat_id, "Nomor E-Wallet tidak valid. Gunakan awalan <code>08...</code>:", parse_mode="HTML")
            return
        mode = st["data"].get("buy_mode", "ew:DANA")
        set_step(chat_id, None)
        execute_single_purchase(chat_id, mode, wallet_number=w_num)
    elif step == "WAIT_CUSTOM_AMOUNT":
        clean_num = re.sub(r"[^0-9]", "", text)
        if not clean_num:
            bot.send_message(chat_id, "Masukkan angka saja untuk nominal (contoh: <code>1000</code>).", parse_mode="HTML")
            return
        mode = st["data"].get("buy_mode", "decoy_qris1")
        set_step(chat_id, None)
        execute_single_purchase(chat_id, mode, custom_amount=int(clean_num))
    elif step == "WAIT_BOUNTY_ALLOT_MSISDN":
        phone = normalize_phone(text)
        if not phone.startswith("628") or len(phone) < 10:
            bot.send_message(chat_id, "Nomor tujuan tidak valid. Gunakan format <code>0812xxxx</code> atau <code>62812xxxx</code>:", parse_mode="HTML")
            return
        set_step(chat_id, None)
        execute_single_purchase(chat_id, "bounty_allot", target_msisdn=phone)

    # ---- TOOLS & REGISTRASI TEXT STEPS ----
    elif step == "WAIT_VALIDATE_MSISDN":
        from app.service.auth import AuthInstance
        from app.client.registration import validate_msisdn
        set_step(chat_id, None)
        phone = normalize_phone(text)
        tokens = AuthInstance.get_active_tokens()
        res = validate_msisdn(AuthInstance.api_key, tokens, phone)
        m = InlineKeyboardMarkup()
        m.row(
            InlineKeyboardButton("Kembali ke Tools", callback_data="nav:tools"),
            InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
        )
        send_or_edit(
            chat_id,
            format_msisdn_validation(phone, res),
            m,
        )
    elif step == "WAIT_PUK_MSISDN":
        phone = normalize_phone(text)
        set_step(chat_id, "WAIT_PUK_CODE", puk_msisdn=phone)
        bot.send_message(chat_id, f"Nomor: <code>{phone}</code>\n<b>Cek / Validasi PUK (2/2)</b>: Ketik <b>8 digit kode PUK</b>:", parse_mode="HTML")
    elif step == "WAIT_PUK_CODE":
        from app.service.auth import AuthInstance
        from app.client.registration import validate_puk
        phone = st["data"].get("puk_msisdn", "")
        puk = text.strip()
        set_step(chat_id, None)
        res = validate_puk(AuthInstance.api_key, phone, puk)
        m = InlineKeyboardMarkup()
        m.row(
            InlineKeyboardButton("Kembali ke Tools", callback_data="nav:tools"),
            InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
        )
        send_or_edit(
            chat_id,
            format_clean_api_result(f"Hasil Validasi PUK Nomor {phone}", res),
            m,
        )
    elif step == "WAIT_DUKCAPIL_MSISDN":
        phone = normalize_phone(text)
        set_step(chat_id, "WAIT_DUKCAPIL_NIK", duk_msisdn=phone)
        bot.send_message(chat_id, f"Nomor: <code>{phone}</code>\n<b>Registrasi Dukcapil (2/3)</b>: Ketik <b>16 digit NIK KTP</b>:", parse_mode="HTML")
    elif step == "WAIT_DUKCAPIL_NIK":
        nik = re.sub(r"[^0-9]", "", text)
        if len(nik) != 16:
            bot.send_message(chat_id, "NIK harus terdiri dari 16 digit angka. Silakan ketik ulang NIK:", parse_mode="HTML")
            return
        set_step(chat_id, "WAIT_DUKCAPIL_KK", duk_nik=nik)
        bot.send_message(chat_id, "<b>Registrasi Dukcapil (3/3)</b>: Ketik <b>16 digit Nomor KK (Kartu Keluarga)</b>:", parse_mode="HTML")
    elif step == "WAIT_DUKCAPIL_KK":
        from app.service.auth import AuthInstance
        from app.client.registration import dukcapil
        kk = re.sub(r"[^0-9]", "", text)
        if len(kk) != 16:
            bot.send_message(chat_id, "Nomor KK harus terdiri dari 16 digit angka. Silakan ketik ulang Nomor KK:", parse_mode="HTML")
            return
        phone = st["data"].get("duk_msisdn", "")
        nik = st["data"].get("duk_nik", "")
        set_step(chat_id, None)
        res = dukcapil(AuthInstance.api_key, phone, kk, nik)
        m = InlineKeyboardMarkup()
        m.row(
            InlineKeyboardButton("Kembali ke Tools", callback_data="nav:tools"),
            InlineKeyboardButton("Menu Utama", callback_data="nav:home"),
        )
        send_or_edit(
            chat_id,
            format_clean_api_result(f"Hasil Registrasi Kartu Dukcapil ({phone})", res),
            m,
        )

    else:
        maybe_phone = normalize_phone(text)
        if maybe_phone.startswith("628") and 10 <= len(maybe_phone) <= 14:
            process_phone_input(chat_id, maybe_phone)
        else:
            render_home(chat_id, user_name=first_name)


if __name__ == "__main__":
    init_bot_info()
    print("[✓] Bot Telegram Aktif. Buka bot di Telegram dan kirim /start")
    bot.infinity_polling(timeout=30, long_polling_timeout=20)
