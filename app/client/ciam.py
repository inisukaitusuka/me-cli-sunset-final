import base64
import os
import json
import uuid
import requests
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta

from app.client.encrypt import (
    java_like_timestamp,
    ts_gmt7_without_colon,
    ax_api_signature,
    load_ax_fp,
    save_ax_fp,
    ax_device_id,
)

DEFAULT_UA = "myXL / 8.9.0(1202); com.android.vending; (samsung; SM-N935F; SDK 33; Android 13)"
BASE_CIAM_URL = os.getenv("BASE_CIAM_URL") or "https://gede.ciam.xlaxiata.co.id"
BASIC_AUTH = os.getenv("BASIC_AUTH") or ""
UA = os.getenv("UA") or DEFAULT_UA


def _get_ciam_cfg(override_ua: str | None = None, override_fp: str | None = None):
    base_url = (os.getenv("BASE_CIAM_URL") or BASE_CIAM_URL or "https://gede.ciam.xlaxiata.co.id").strip()
    basic_auth = (os.getenv("BASIC_AUTH") or BASIC_AUTH or "").strip()
    if override_ua is not None and override_ua.strip():
        ua_val = override_ua.strip()
    else:
        ua_val = (os.getenv("UA") or UA or DEFAULT_UA).strip()
    if override_fp and override_fp.strip():
        save_ax_fp(override_fp.strip())
        fp_val = override_fp.strip()
    else:
        fp_val = load_ax_fp()
    dev_id = ax_device_id(fp_val)
    host_val = base_url.replace("https://", "").replace("http://", "").split("/")[0]
    return base_url, host_val, basic_auth, ua_val, fp_val, dev_id


def validate_contact(contact: str) -> bool:
    if not contact.startswith("628") or len(contact) > 14:
        print("Invalid number")
        return False
    return True


def get_otp(contact: str) -> str | None:
    if not validate_contact(contact):
        return None

    base_url, host_val, basic_auth, ua_val, fp_val, dev_id = _get_ciam_cfg()
    url = base_url + "/realms/xl-ciam/auth/otp"

    querystring = {
        "contact": contact,
        "contactType": "SMS",
        "alternateContact": "false"
    }

    now = datetime.now(timezone(timedelta(hours=7)))
    ax_request_at = java_like_timestamp(now)
    ax_request_id = str(uuid.uuid4())

    headers = {
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": f"Basic {basic_auth}",
        "Ax-Device-Id": dev_id,
        "Ax-Fingerprint": fp_val,
        "Ax-Request-At": ax_request_at,
        "Ax-Request-Device": "samsung",
        "Ax-Request-Device-Model": "SM-N935F",
        "Ax-Request-Id": ax_request_id,
        "Ax-Substype": "PREPAID",
        "Content-Type": "application/json",
        "Host": host_val,
        "User-Agent": ua_val,
    }

    print("Requesting OTP...")
    try:
        response = requests.request("GET", url, data="", headers=headers, params=querystring, timeout=30)
        print("response body", response.text)
        json_body = json.loads(response.text)

        if "subscriber_id" not in json_body:
            print(json_body.get("error", "No error message in response"))
            raise ValueError("Subscriber ID not found in response")

        return json_body["subscriber_id"]
    except Exception as e:
        print(f"Error requesting OTP: {e}")
        return None


def extend_session(subscriber_id: str, override_ua: str | None = None, override_fp: str | None = None) -> str | None:
    if not subscriber_id:
        return None
    base_url, host_val, basic_auth, ua_val, fp_val, dev_id = _get_ciam_cfg(override_ua, override_fp)
    b64_subscriber_id = base64.b64encode(str(subscriber_id).encode()).decode()
    url = f"{base_url}/realms/xl-ciam/auth/extend-session"

    querystring = {
        "contact": b64_subscriber_id,
        "contactType": "DEVICEID"
    }

    now = datetime.now(timezone(timedelta(hours=7)))
    ax_request_at = java_like_timestamp(now)
    ax_request_id = str(uuid.uuid4())

    headers = {
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": f"Basic {basic_auth}",
        "Ax-Device-Id": dev_id,
        "Ax-Fingerprint": fp_val,
        "Ax-Request-At": ax_request_at,
        "Ax-Request-Device": "samsung",
        "Ax-Request-Device-Model": "SM-N935F",
        "Ax-Request-Id": ax_request_id,
        "Ax-Substype": "PREPAID",
        "Content-Type": "application/json",
        "Host": host_val,
        "User-Agent": ua_val,
    }

    print("Extending session...")
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=30)
        if response.status_code != 200:
            print(f"Failed to extend session: {response.status_code} - {response.text}")
            return None

        data = response.json()
        exchange_code = data.get("data", {}).get("exchange_code")
        return exchange_code
    except Exception as e:
        print(f"Error extending session: {e}")
        return None


def submit_otp(
    api_key: str,
    contact_type: str,
    contact: str,
    code: str,
    override_ua: str | None = None,
    override_fp: str | None = None,
):
    final_contact = ""
    final_code = ""

    if contact_type == "SMS":
        if not validate_contact(contact):
            print("Invalid number")
            return None
        final_contact = contact

        if not code or len(code) != 6:
            print("Invalid OTP code format")
            return None
        final_code = code
    elif contact_type == "DEVICEID":
        final_contact = base64.b64encode(str(contact).encode()).decode()
        final_code = code
    else:
        print("Unsupported contact type")
        return None

    base_url, host_val, basic_auth, ua_val, fp_val, dev_id = _get_ciam_cfg(override_ua, override_fp)
    url = base_url + "/realms/xl-ciam/protocol/openid-connect/token"

    now_gmt7 = datetime.now(timezone(timedelta(hours=7)))
    ts_for_sign = ts_gmt7_without_colon(now_gmt7)
    ts_header = ts_gmt7_without_colon(now_gmt7 - timedelta(minutes=5))
    signature = ax_api_signature(api_key, ts_for_sign, final_contact, code, contact_type)

    payload = f"contactType={contact_type}&code={final_code}&grant_type=password&contact={final_contact}&scope=openid"

    headers = {
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": f"Basic {basic_auth}",
        "Ax-Api-Signature": signature,
        "Ax-Device-Id": dev_id,
        "Ax-Fingerprint": fp_val,
        "Ax-Request-At": ts_header,
        "Ax-Request-Device": "samsung",
        "Ax-Request-Device-Model": "SM-N935F",
        "Ax-Request-Id": str(uuid.uuid4()),
        "Ax-Substype": "PREPAID",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": ua_val,
    }

    print("Submitting OTP...")
    try:
        response = requests.post(url, data=payload, headers=headers, timeout=30)
        json_body = json.loads(response.text)

        if "error" in json_body:
            print(f"[Error submit_otp]: {json_body}")
            return None

        json_body["_used_ua"] = ua_val
        json_body["_used_fp"] = fp_val
        print("Login successful.")
        return json_body
    except requests.RequestException as e:
        print(f"[Error submit_otp]: {e}")
        return None


def get_new_token(
    api_key: str,
    refresh_token: str,
    subscriber_id: str = "",
    saved_ua: str = "",
    saved_fp: str = "",
) -> dict | None:
    base_url, host_val, basic_auth, current_ua, fp_val, dev_id = _get_ciam_cfg(
        override_ua=(saved_ua if saved_ua else None),
        override_fp=(saved_fp if saved_fp else None),
    )
    url = base_url + "/realms/xl-ciam/protocol/openid-connect/token"

    now = datetime.now(timezone(timedelta(hours=7)))
    ax_request_at = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+0700"

    raw_candidates = [
        saved_ua.strip() if saved_ua else "",
        (os.getenv("UA") or "").strip(),
        current_ua,
        "myXL / 8.9.0(1202); com.android.vending; (samsung; SM-N935F; SDK 33; Android 13)",
        "myXL / 9.6.0(1249); com.android.vending; (samsung; SM-N935F; SDK 33; Android 13)",
        "myXL / 9.6.0(1311); com.android.vending; (samsung; SM-N935F; SDK 33; Android 13)",
        "myXL / 9.6.0(1202); com.android.vending; (samsung; SM-N935F; SDK 33; Android 13)",
        "myXL / 8.9.0(1249); com.android.vending; (samsung; SM-N935F; SDK 33; Android 13)",
        f"python-requests/{requests.__version__}",
    ]
    ua_candidates = []
    for u in raw_candidates:
        if u and u not in ua_candidates:
            ua_candidates.append(u)

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }

    print("Refreshing token...")
    resp = None
    matched_ua = current_ua

    for try_ua in ua_candidates:
        headers = {
            "Host": host_val,
            "ax-request-at": ax_request_at,
            "ax-device-id": dev_id,
            "ax-request-id": str(uuid.uuid4()),
            "ax-request-device": "samsung",
            "ax-request-device-model": "SM-N935F",
            "ax-fingerprint": fp_val,
            "authorization": f"Basic {basic_auth}",
            "user-agent": try_ua,
            "ax-substype": "PREPAID",
            "content-type": "application/x-www-form-urlencoded"
        }
        try:
            resp = requests.post(url, headers=headers, data=data, timeout=30)
        except Exception as e:
            print(f"Error connecting for token refresh: {e}")
            return None

        if resp.status_code == 200:
            matched_ua = try_ua
            break

        if resp.status_code == 400 and "User Agent mismatch" in resp.text:
            print(f"[!] UA mismatch dengan '{try_ua[:24]}...', mencoba UA berikutnya...")
            continue

        break

    if resp is None:
        return None

    if resp.status_code == 400:
        if subscriber_id:
            exchange_code = extend_session(subscriber_id, override_ua=matched_ua, override_fp=fp_val)
            if exchange_code:
                extend_result = submit_otp(
                    api_key,
                    "DEVICEID",
                    subscriber_id,
                    exchange_code,
                    override_ua=matched_ua,
                    override_fp=fp_val,
                )
                if isinstance(extend_result, dict) and "id_token" in extend_result:
                    return extend_result

        print(f"Failed to refresh token: {resp.status_code} - {resp.text}")
        return None

    try:
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        print(f"Error parsing refresh token response: {e}")
        return None

    if not isinstance(body, dict) or "id_token" not in body:
        print(f"ID token not found in response: {body}")
        return None

    body["_used_ua"] = matched_ua
    body["_used_fp"] = fp_val
    return body


def get_auth_code(tokens: dict, pin: str, msisdn: str):
    base_url, host_val, basic_auth, ua_val, fp_val, dev_id = _get_ciam_cfg()
    url = base_url + "/ciam/auth/authorization-token/generate"

    parsed = urlparse(base_url)
    host_header = parsed.netloc or host_val

    now = datetime.now(timezone(timedelta(hours=7)))
    ax_request_at = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+0700"
    ax_request_id = str(uuid.uuid4())

    headers = {
        "Host": host_header,
        "Ax-Request-At": ax_request_at,
        "Ax-Device-Id": dev_id,
        "Ax-Request-Id": ax_request_id,
        "Ax-Request-Device": "samsung",
        "Ax-Request-Device-Model": "SM-N935F",
        "Ax-Fingerprint": fp_val,
        "Authorization": f"Bearer {tokens['access_token']}",
        "User-Agent": ua_val,
        "Ax-Substype": "PREPAID",
        "Content-Type": "application/json",
    }

    pin_b64 = base64.b64encode(pin.encode("utf-8")).decode("utf-8")

    body = {
        "pin": pin_b64,
        "transaction_type": "SHARE_BALANCE",
        "receiver_msisdn": msisdn,
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
    except requests.RequestException as e:
        print(f"[get_auth_code] Request error: {e}")
        return None

    if resp.status_code != 200:
        print(f"Failed to get auth code: {resp.status_code} - {resp.text}")
        return None

    try:
        data = resp.json()
    except ValueError:
        print(f"Invalid JSON response: {resp.text}")
        return None

    if not isinstance(data, dict):
        return None

    if data.get("status", "") != "Success":
        return None

    return data.get("data", {}).get("authorization_code")
