import os
import json
import shutil
import time
from app.client.ciam import get_new_token
from app.client.engsel import get_profile
from app.client.encrypt import load_ax_fp, save_ax_fp
from app.util import ensure_api_key

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKUP_DIR = os.path.expanduser("~/.myxl_backup")
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

TOKENS_FILE = os.path.join(BASE_DIR, "refresh-tokens.json")
ACTIVE_FILE = os.path.join(BASE_DIR, "active.number")
BACKUP_TOKENS_FILE = os.path.join(BACKUP_DIR, "refresh-tokens.json")
BACKUP_ACTIVE_FILE = os.path.join(BACKUP_DIR, "active.number")


class Auth:
    _instance_ = None
    _initialized_ = False

    api_key = ""
    refresh_tokens = []
    active_user = None
    last_refresh_time = None
    failed_numbers = set()

    def __new__(cls, *args, **kwargs):
        if not cls._instance_:
            cls._instance_ = super().__new__(cls)
        return cls._instance_

    def __init__(self):
        if not self._initialized_:
            self.api_key = ensure_api_key()
            self.failed_numbers = set()
            self._ensure_files()
            self.load_tokens()
            self.load_active_number()
            self.last_refresh_time = int(time.time())
            self._initialized_ = True

    def _ensure_files(self):
        os.makedirs(BASE_DIR, exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if not os.path.exists(TOKENS_FILE) and os.path.exists(BACKUP_TOKENS_FILE):
            try:
                shutil.copy2(BACKUP_TOKENS_FILE, TOKENS_FILE)
            except Exception:
                pass
        if not os.path.exists(ACTIVE_FILE) and os.path.exists(BACKUP_ACTIVE_FILE):
            try:
                shutil.copy2(BACKUP_ACTIVE_FILE, ACTIVE_FILE)
            except Exception:
                pass
        if not os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, indent=4)

    def load_tokens(self):
        self._ensure_files()
        try:
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if (not data) and os.path.exists(BACKUP_TOKENS_FILE):
                with open(BACKUP_TOKENS_FILE, "r", encoding="utf-8") as bf:
                    backup_data = json.load(bf)
                if isinstance(backup_data, list) and backup_data:
                    data = backup_data
            self.refresh_tokens = [
                rt for rt in (data if isinstance(data, list) else [])
                if isinstance(rt, dict) and "number" in rt and "refresh_token" in rt
            ]
        except Exception as e:
            print(f"Error loading tokens: {e}")
            self.refresh_tokens = []

    def add_refresh_token(self, number: int, refresh_token: str, initial_tokens: dict | None = None, saved_ua: str = "", saved_fp: str = ""):
        self._ensure_files()
        number = int(number)
        refresh_token = str(refresh_token).strip()
        if not refresh_token:
            return False

        self.failed_numbers.discard(number)
        existing = next((rt for rt in self.refresh_tokens if int(rt["number"]) == number), None)
        entry_ua = (saved_ua or (existing.get("ua") if existing else "") or os.getenv("UA") or "").strip()
        entry_fp = (saved_fp or (existing.get("ax_fp") if existing else "") or load_ax_fp()).strip()
        if entry_fp:
            save_ax_fp(entry_fp)

        tokens = initial_tokens if (isinstance(initial_tokens, dict) and "access_token" in initial_tokens) else None
        if not tokens:
            tokens = get_new_token(
                self.api_key,
                refresh_token,
                existing.get("subscriber_id", "") if existing else "",
                saved_ua=entry_ua,
                saved_fp=entry_fp,
            )
        if not tokens or not isinstance(tokens, dict):
            return False

        final_rt = tokens.get("refresh_token") or refresh_token
        matched_ua = tokens.get("_used_ua") or entry_ua
        matched_fp = tokens.get("_used_fp") or entry_fp

        profile_data = get_profile(self.api_key, tokens["access_token"], tokens["id_token"]) or {}
        prof = profile_data.get("profile", {}) if isinstance(profile_data, dict) else {}
        sub_id = prof.get("subscriber_id") or (existing.get("subscriber_id", "") if existing else "")
        sub_type = prof.get("subscription_type") or (existing.get("subscription_type", "PREPAID") if existing else "PREPAID")

        if existing:
            existing["refresh_token"] = final_rt
            existing["subscriber_id"] = sub_id
            existing["subscription_type"] = sub_type
            if matched_ua:
                existing["ua"] = matched_ua
            if matched_fp:
                existing["ax_fp"] = matched_fp
        else:
            self.refresh_tokens.append({
                "number": number,
                "subscriber_id": sub_id,
                "subscription_type": sub_type,
                "refresh_token": final_rt,
                "ua": matched_ua,
                "ax_fp": matched_fp,
            })

        self.active_user = {
            "number": number,
            "subscriber_id": sub_id,
            "subscription_type": sub_type,
            "tokens": tokens,
        }
        self.last_refresh_time = int(time.time())
        self.write_tokens_to_file()
        self.write_active_number()
        return True

    def remove_refresh_token(self, number: int):
        number = int(number)
        self.failed_numbers.discard(number)
        self.refresh_tokens = [rt for rt in self.refresh_tokens if int(rt["number"]) != number]
        self.write_tokens_to_file()

        if self.active_user and int(self.active_user["number"]) == number:
            self.active_user = None
            if self.refresh_tokens:
                try:
                    self.set_active_user(int(self.refresh_tokens[0]["number"]))
                except Exception as e:
                    print(f"Failed auto-switching user: {e}")
            else:
                self.write_active_number()

    def set_active_user(self, number: int):
        number = int(number)
        rt_entry = next((rt for rt in self.refresh_tokens if int(rt["number"]) == number), None)
        if not rt_entry:
            print(f"No refresh token found for number: {number}")
            return False

        entry_ua = (rt_entry.get("ua") or os.getenv("UA") or "").strip()
        entry_fp = (rt_entry.get("ax_fp") or "").strip()
        if entry_fp:
            save_ax_fp(entry_fp)

        try:
            tokens = get_new_token(
                self.api_key,
                rt_entry["refresh_token"],
                rt_entry.get("subscriber_id", ""),
                saved_ua=entry_ua,
                saved_fp=entry_fp,
            )
            if not tokens or not isinstance(tokens, dict):
                print(f"Failed to get tokens for number: {number}.")
                self.failed_numbers.add(number)
                return False

            self.failed_numbers.discard(number)
            profile_data = get_profile(self.api_key, tokens["access_token"], tokens["id_token"]) or {}
            prof = profile_data.get("profile", {}) if isinstance(profile_data, dict) else {}
            subscriber_id = prof.get("subscriber_id") or rt_entry.get("subscriber_id", "")
            subscription_type = prof.get("subscription_type") or rt_entry.get("subscription_type", "PREPAID")

            self.active_user = {
                "number": number,
                "subscriber_id": subscriber_id,
                "subscription_type": subscription_type,
                "tokens": tokens
            }

            rt_entry["subscriber_id"] = subscriber_id
            rt_entry["subscription_type"] = subscription_type
            if "refresh_token" in tokens and tokens["refresh_token"]:
                rt_entry["refresh_token"] = tokens["refresh_token"]
            if tokens.get("_used_ua"):
                rt_entry["ua"] = tokens["_used_ua"]
            if tokens.get("_used_fp"):
                rt_entry["ax_fp"] = tokens["_used_fp"]
            self.write_tokens_to_file()

            self.last_refresh_time = int(time.time())
            self.write_active_number()
            return True
        except Exception as e:
            print(f"Error setting active user {number}: {e}")
            self.failed_numbers.add(number)
            return False

    def renew_active_user_token(self):
        if self.active_user:
            num = int(self.active_user["number"])
            rt_entry = next((rt for rt in self.refresh_tokens if int(rt["number"]) == num), {})
            entry_ua = (rt_entry.get("ua") or os.getenv("UA") or "").strip()
            entry_fp = (rt_entry.get("ax_fp") or "").strip()
            try:
                tokens = get_new_token(
                    self.api_key,
                    self.active_user["tokens"]["refresh_token"],
                    self.active_user.get("subscriber_id", ""),
                    saved_ua=entry_ua,
                    saved_fp=entry_fp,
                )
                if tokens and isinstance(tokens, dict):
                    self.active_user["tokens"] = tokens
                    self.last_refresh_time = int(time.time())
                    if "refresh_token" in tokens and tokens["refresh_token"] and rt_entry:
                        rt_entry["refresh_token"] = tokens["refresh_token"]
                        if tokens.get("_used_ua"):
                            rt_entry["ua"] = tokens["_used_ua"]
                        if tokens.get("_used_fp"):
                            rt_entry["ax_fp"] = tokens["_used_fp"]
                        self.write_tokens_to_file()
                    print("Active user token renewed successfully.")
                    return True
            except Exception as e:
                print(f"Failed to renew active user token: {e}")
        return False

    def get_active_user(self):
        if not self.active_user:
            if not self.refresh_tokens:
                self.load_tokens()
            for rt in self.refresh_tokens:
                num = int(rt["number"])
                if num in self.failed_numbers:
                    continue
                if self.set_active_user(num):
                    return self.active_user
            return None

        if self.last_refresh_time is None or (int(time.time()) - self.last_refresh_time) > 300:
            self.renew_active_user_token()
            self.last_refresh_time = int(time.time())

        return self.active_user

    def get_active_tokens(self) -> dict | None:
        active_user = self.get_active_user()
        return active_user["tokens"] if active_user else None

    def write_tokens_to_file(self):
        os.makedirs(BASE_DIR, exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        for path in (TOKENS_FILE, BACKUP_TOKENS_FILE):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.refresh_tokens, f, indent=4)

    def write_active_number(self):
        os.makedirs(BASE_DIR, exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if self.active_user:
            for path in (ACTIVE_FILE, BACKUP_ACTIVE_FILE):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(str(self.active_user["number"]))
        else:
            for path in (ACTIVE_FILE, BACKUP_ACTIVE_FILE):
                if os.path.exists(path):
                    os.remove(path)

    def load_active_number(self):
        self._ensure_files()
        if os.path.exists(ACTIVE_FILE):
            try:
                with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                    number_str = f.read().strip()
                    if number_str.isdigit():
                        self.set_active_user(int(number_str))
            except Exception as e:
                print(f"Failed loading active number: {e}")


AuthInstance = Auth()
