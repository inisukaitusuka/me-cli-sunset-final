#!/usr/bin/env bash
set -e

echo "=========================================="
echo "   Instalasi Otomatis Bot Telegram MyXL   "
echo "=========================================="

if [ ! -f ".env" ] && [ -f ".env.template" ]; then
    cp .env.template .env
    echo "[+] File .env otomatis dibuat dari .env.template"
fi

# Cek apakah berjalan di Termux (Android) atau VPS Linux
if [ -n "$TERMUX_VERSION" ] || [ -d "/data/data/com.termux" ]; then
    echo "[+] Terdeteksi lingkungan: Termux (Android)"
    pkg update -y && pkg upgrade -y
    pkg install python python-pillow libjpeg-turbo zlib git -y
    pip install -r requirements.txt
    echo ""
    echo "[✓] Instalasi di Termux selesai!"
    echo "Cara menjalankan bot:"
    echo "  python bot.py"
else
    echo "[+] Terdeteksi lingkungan: Linux / VPS"
    if command -v apt >/dev/null 2>&1; then
        sudo apt update -y
        sudo apt install python3 python3-pip python3-venv git -y
    fi

    if [ ! -d "venv" ]; then
        echo "[+] Membuat virtual environment (venv)..."
        python3 -m venv venv
    fi

    echo "[+] Menginstal pustaka Python ke dalam venv..."
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r requirements.txt

    echo ""
    echo "[✓] Instalasi di VPS selesai!"
    echo "Cara menjalankan bot:"
    echo "  source venv/bin/activate && python bot.py"
fi
