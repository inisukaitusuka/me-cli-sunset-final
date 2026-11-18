# MyEngsel Telegram Bot (Clean & Full Integrated Edition)

Bot Telegram interaktif untuk mengelola akun XL, mengecek sisa kuota paket aktif, mencari Family Code, mengatur urutan Bookmark, menjelajahi katalog Store & Promo Segments, hingga membeli paket langsung dari ruang chat Telegram. Dirancang dengan tampilan **ringkas 1 layar (anti-scroll)**, **auto-backup sesi token tanpa login OTP ulang**, serta mendukung instalasi otomatis (*fresh install*) di **Termux (Android)** maupun **VPS Linux (Ubuntu/Debian)**.

---

## Fitur Utama

* **Multi-Akun, Login OTP Popup & Backup/Restore Token (Tanpa OTP)**:
  * Tambah, ganti, dan hapus banyak nomor XL sekaligus, serta perbarui sesi token langsung dari ruang chat dengan dukungan popup input otomatis (`ForceReply`).
  * **Backup & Restore Akun Tanpa OTP**: Unduh file `refresh-tokens.json` atau salin teks `628xxxx:refresh_token` langsung melalui tombol **`Backup Akun (Token)`** di menu Kelola Akun. Saat pindah server atau instal ulang, cukup tekan **`Restore Token`** lalu kirimkan kembali file JSON atau tempelkan teks token ke chat untuk langsung aktif tanpa perlu SMS OTP lagi (dilengkapi sinkronisasi otomatis `UA` & *Device Fingerprint* `ax.fp`).
  * **Auto-Backup Permanen di Server (`~/.myxl_backup/`)**: Data sesi akun (`refresh-tokens.json`, `active.number`, `ax.fp`) dan `bookmark.json` otomatis dicadangkan di luar folder bot, sehingga saat mengganti atau menimpa folder `.zip` baru di server yang sama, akun dan bookmark langsung pulih otomatis.
* **Tampilan 1 Layar (Anti-Scroll) & Pembersihan Pesan Otomatis**:
  * Seluruh menu katalog dan detail paket dirancang ringkas agar langsung muat dalam **1 layar HP** tanpa perlu menggulir (*scroll*) pesan panjang.
  * Setiap berpindah menu atau memproses transaksi, bot otomatis memperbarui pesan di tempat atau menghapus pesan menu lama di atasnya agar menu aktif selalu berada di posisi paling bawah ruang chat.
* **Navigasi Ganda Setelah Transaksi (2 Opsi Kembali)**:
  * Setiap selesai atau gagal melakukan transaksi pembelian (Pulsa, QRIS, E-Wallet, Decoy, maupun Klaim Bonus/Poin), bot menyediakan opsi untuk **Kembali ke Detail Paket**, **Kembali ke Fitur yang Terakhir Dimasuki** (*Daftar Paket Family*, *Bookmark*, *Store Packages*, *Store Family List*, *Store Segments*, *Promo*, atau *Option Code*), serta **Kembali ke Menu Utama**.
* **Paket Aktif & Stop Paket**:
  * Cek sisa kuota Data/Voice/SMS secara *real-time*, lihat detail paket aktif, dan berhenti berlangganan (*Stop/Unsubscribe* paket) dengan konfirmasi aman.
* **Family Code, Deteksi UUID Otomatis & Riwayat Recent**:
  * **Deteksi Otomatis di Chat**: Tempelkan (*paste*) kode *Family Code* (format UUID seperti `23b71540-8785-4abe-816d-e9b4efa48f95`) kapan saja ke ruang chat tanpa perlu membuka menu terlebih dahulu — bot otomatis mengenali dan langsung membuka daftar paketnya.
  * **Tampilan 2 Kolom Ringkas**: Daftar paket di dalam *Family Code* ditampilkan dalam tombol **2 kolom (14 paket per halaman)** lengkap dengan navigasi halaman (`⏪ -5`, `⬅️`, `➡️`, `+5 ⏩`) sehingga tombol navigasi kembali tidak pernah terpotong.
  * **Riwayat Baru Dikunjungi (Recent)**: Menyimpan otomatis 15 riwayat *Family Code* terakhir dengan label tombol nama paket bawaan yang bersih.
* **Multi-Bookmark Checklist Sesuai Urutan Pilihan (`1, 2, 3...`)**:
  * Pilih banyak paket sekaligus di dalam *Family Code* menggunakan mode *checklist* yang menampilkan nomor urutan pilih secara langsung (`[#1 ✓]`, `[#2 ✓]`, dst.) beserta pratinjau urutan di layar.
  * Paket disimpan ke daftar Bookmark persis mengikuti urutan yang dipilih lebih dulu (`1, 2, 3, ...`) dan mendukung penyimpanan beberapa opsi dari varian paket yang sama.
* **Store Packages, Store Family List, Promo Redeemables & Store Segments**:
  * Jelajahi katalog *Store Packages* dan *Store Family List* (tampilan 2 kolom, 12 item per halaman) dengan fitur pencarian kata kunci instan di chat dan lompat halaman cepat.
  * **Store Segments & Promo Pilihan**: Menampilkan katalog *Store Segments* beserta daftar *banners* promo (seperti *Special For You*) secara rapi lengkap dengan harga dan tombol beli langsung tanpa menampilkan JSON mentah.
* **Metode Pembayaran & Klaim Lengkap**:
  * **Pulsa** (Normal & *Custom Nominal / Overwrite Harga*)
  * **QRIS** (Normal & *Custom Nominal* — otomatis merender gambar QR Code di chat + tombol buka di browser)
  * **E-Wallet**: DANA, ShopeePay, GoPay, dan OVO
  * **Paket Decoy**: Pulsa + Decoy (V1 & V2) serta QRIS + Decoy (+1K & Rp0)
  * **Bonus & Poin**: Klaim Bonus (*Bounty*), Tukar Poin (*Loyalty*), dan Kirim Bonus ke Nomor Lain (*Bounty Allotment*)
* **Tools Kartu & Registrasi Dukcapil (Bahasa Indonesia Rapi)**:
  * **Validasi Status Nomor**: Menampilkan informasi lengkap kartu (Nomor XL, ID Pelanggan, Jenis Kartu Prabayar/Pascabayar, Status Kartu, Status Blokir, Registrasi Dukcapil, Layanan Prio Flex, serta Kategori Pelanggan) dalam bahasa Indonesia yang bersih tanpa istilah teknis bot atau JSON mentah.
  * **Cek / Validasi PUK & Registrasi Dukcapil**: Validasi kode PUK kartu XL serta registrasi kartu perdana menggunakan NIK & Nomor KK langsung dari chat.
* **Hot-Reload `.env` via Chat (Tanpa Restart Bot)**:
  * Cukup tempelkan (*paste*) teks `.env` atau kirim file `.env` ke ruang chat bot — konfigurasi langsung tersimpan dan aktif seketika tanpa perlu mematikan bot.

---

## Daftar Command Bot

Seluruh command di bawah ini otomatis terdaftar ke tombol menu `/` Telegram saat bot dijalankan:

| Command | Fungsi |
| :--- | :--- |
| `/start` | Membuka Menu Utama & ringkasan akun aktif |
| `/paket` | Melihat daftar Paket Aktif, sisa kuota, detail & Stop Paket |
| `/bookmark` | Membuka daftar paket yang disimpan di Bookmark |
| `/familycode` | Mencari paket via Family Code & melihat riwayat Recent (bisa `/familycode <kode>` atau paste langsung UUID di chat) |
| `/optioncode` | Membeli paket menggunakan Option Code (bisa `/optioncode <kode>`) |
| `/store` | Membuka katalog Store Packages dengan fitur filter & lompat halaman |
| `/promo` | Membuka menu Promo Redeemables & Store Segments |
| `/riwayat` | Melihat riwayat transaksi terakhir |
| `/profil` | Melihat detail profil akun & daftar transaksi Pending |
| `/notifikasi` | Melihat dan menandai semua notifikasi akun |
| `/tools` | Membuka menu Validasi Status Nomor, Cek PUK & Registrasi Kartu Dukcapil |
| `/login` | Mengelola akun tersimpan, Backup/Restore Refresh Token, atau menambah nomor baru |
| `/id` | Menampilkan User ID & Chat ID Telegram Anda |

---

## Persiapan Awal (Fresh Install)

1. Buka aplikasi Telegram dan cari **`@BotFather`**.
2. Ketik `/newbot`, tentukan nama serta username bot Anda, lalu salin **HTTP API Token** yang diberikan.
3. *(Opsional)* Ketik `/id` di bot nantinya atau hubungi **`@userinfobot`** untuk mengetahui **User ID Telegram** Anda jika ingin membatasi agar bot hanya bisa diakses oleh Anda sendiri (Admin).

---

## Panduan Instalasi dari Nol (Fresh Install)

Skrip `setup.sh` sudah dilengkapi deteksi sistem otomatis untuk **Termux (Android)** maupun **VPS Linux (Ubuntu/Debian)**.

### A. Instalasi di Termux (Android)

1. Perbarui paket Termux dan instal peralatan dasar:
   ```bash
   pkg update && pkg upgrade -y
   pkg install git unzip -y
   ```
2. Ekstrak file `.zip` proyek lalu masuk ke foldernya:
   ```bash
   unzip -o me-cli-sunset-8.9.0-final.zip
   cd me-cli-sunset-main
   ```
3. Jalankan skrip instalasi otomatis:
   ```bash
   bash setup.sh
   ```
4. Jalankan bot:
   ```bash
   python bot.py
   ```

---

### B. Instalasi di VPS Linux (Ubuntu / Debian)

1. Perbarui paket sistem dan instal `git` serta `unzip`:
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install git unzip -y
   ```
2. Ekstrak file `.zip` proyek dan masuk ke foldernya:
   ```bash
   unzip -o me-cli-sunset-8.9.0-final.zip
   cd me-cli-sunset-main
   ```
3. Jalankan skrip instalasi otomatis (otomatis menyiapkan `python3-venv` dan menginstal seluruh pustaka di `requirements.txt`):
   ```bash
   bash setup.sh
   ```
4. Aktifkan *virtual environment* (`venv`) dan jalankan bot:
   ```bash
   source venv/bin/activate
   python bot.py
   ```

---

## Cara Mengisi Konfigurasi `.env` & Restore Akun

Di dalam paket `.zip` ini hanya disertakan file `.env.template` agar kredensial pribadi Anda tetap aman dan terpisah. Saat pertama kali menjalankan `python bot.py`:

1. Terminal akan otomatis menyalin `.env.template` menjadi `.env` dan meminta Anda memasukkan:
   * **`TELEGRAM_BOT_TOKEN`**: Tempelkan Token Bot dari `@BotFather`.
   * **`TELEGRAM_ADMIN_IDS`**: Masukkan User ID Telegram Anda (atau tekan `Enter` jika ingin bebas diakses).
2. Setelah bot aktif, buka bot di Telegram lalu kirim `/start`.
3. **Isi Variabel `.env` Lewat Chat**: Tempelkan (*paste*) teks isi `.env` Anda atau kirimkan file `.env` langsung ke ruang chat bot — seluruh variabel (`BASE_API_URL`, `BASE_CIAM_URL`, `BASIC_AUTH`, `UA`, `API_KEY`, dll.) akan otomatis disimpan dan diterapkan tanpa perlu me-*restart* bot.
4. **Restore Akun Tanpa Login OTP**: Jika Anda memiliki cadangan `refresh-tokens.json` atau teks `628xxxx:refresh_token`, klik tombol **`Restore Token`** di layar chat lalu kirimkan file/teks tersebut untuk langsung mengaktifkan nomor tanpa SMS OTP.

---

## Menjalankan Bot 24 Jam Nonstop di VPS (Background)

Agar bot tetap berjalan meskipun Anda menutup terminal SSH:

### Opsi 1: Menggunakan `systemd` (Direkomendasikan — Otomatis Menyala Saat VPS Reboot)
Jalankan perintah berikut satu kali di dalam folder `me-cli-sunset-main` di VPS Anda:
```bash
cat <<EOF | sudo tee /etc/systemd/system/myxlbot.service
[Unit]
Description=MyEngsel Telegram Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python $(pwd)/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable myxlbot
sudo systemctl start myxlbot
```

**Perintah kontrol `systemd` sehari-hari:**
* Cek status bot: `sudo systemctl status myxlbot`
* Lihat log aktivitas *real-time*: `journalctl -u myxlbot -f`
* Restart bot: `sudo systemctl restart myxlbot`
* Matikan bot: `sudo systemctl stop myxlbot`

### Opsi 2: Menggunakan `screen`
```bash
sudo apt install screen -y
screen -S myxlbot
source venv/bin/activate
python bot.py
```
* *Keluar dari layar screen tanpa mematikan bot*: Tekan **`Ctrl+A`** lalu tekan **`D`**.
* *Membuka kembali layar log bot*: Ketik `screen -r myxlbot`.
