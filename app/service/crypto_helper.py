import hashlib, os, hmac, base64
from base64 import urlsafe_b64encode, urlsafe_b64decode
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

XDATA_KEY = os.getenv("XDATA_KEY", "")
AX_API_SIG_KEY = os.getenv("AX_API_SIG_KEY", "")
X_API_BASE_SECRET = os.getenv("X_API_BASE_SECRET", "")
ENCRYPTED_FIELD_KEY = os.getenv("ENCRYPTED_FIELD_KEY", "")

def _get_key(name: str, default: str = "") -> str:
    return os.getenv(name) or globals().get(name) or default

def derive_iv(xtime_ms: int) -> bytes:
    sha = hashlib.sha256(str(xtime_ms).encode()).hexdigest()
    return sha[:16].encode()

def encrypt_xdata(plaintext: str, xtime_ms: int) -> str:
    iv = derive_iv(xtime_ms)
    key_bytes = _get_key("XDATA_KEY").encode()
    
    cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
    return urlsafe_b64encode(cipher.encrypt(pad(plaintext.encode(), 16, style="pkcs7"))).decode()

def decrypt_xdata(xdata: str, xtime_ms: int) -> str:
    iv = derive_iv(xtime_ms)
    key_bytes = _get_key("XDATA_KEY").encode()
    
    ct = urlsafe_b64decode(xdata + "=" * ((4 - len(xdata) % 4) % 4))
    pt = AES.new(key_bytes, AES.MODE_CBC, iv).decrypt(ct)
    return unpad(pt, 16, style="pkcs7").decode()

def make_x_signature(
    id_token: str,
    method: str,
    path: str,
    sig_time_sec: int
) -> str:
    secret = _get_key("X_API_BASE_SECRET")
    key_str = f"{secret};{id_token};{method};{path};{sig_time_sec}"
    key_bytes = key_str.encode("utf-8")
    
    msg = f"{id_token};{sig_time_sec};".encode("utf-8")
    
    return hmac.new(key_bytes, msg, hashlib.sha512).hexdigest()

def make_x_signature_payment(
    access_token: str,
    sig_time_sec: int,
    package_code: str,
    token_payment: str,
    payment_method: str,
    payment_for: str,
    path: str,
) -> str:
    secret = _get_key("X_API_BASE_SECRET")
    key_str = f"{secret};{sig_time_sec}#ae-hei_9Tee6he+Ik3Gais5=;POST;{path};{sig_time_sec}"
    key_bytes = key_str.encode("utf-8")

    msg = f"{access_token};{token_payment};{sig_time_sec};{payment_for};{payment_method};{package_code};".encode("utf-8")

    return hmac.new(key_bytes, msg, hashlib.sha512).hexdigest()

def make_ax_api_signature(
    ts_for_sign: str,
    contact: str,
    code: str,
    contact_type: str
) -> str:
    key_bytes = _get_key("AX_API_SIG_KEY").encode("ascii")
    
    preimage = f"{ts_for_sign}password{contact_type}{contact}{code}openid"
    digest = hmac.new(key_bytes, preimage.encode("utf-8"), hashlib.sha256).digest()
    b64res = base64.b64encode(digest).decode("ascii")
    return b64res

def make_x_signature_bounty(
    access_token: str,
    sig_time_sec: int,
    package_code: str,
    token_payment: str,
) -> str:
    path = "api/v8/personalization/bounties-exchange"
    secret = _get_key("X_API_BASE_SECRET")

    key_str = f"{secret};{access_token};{sig_time_sec}#ae-hei_9Tee6he+Ik3Gais5=;POST;{path};{sig_time_sec}"
    key_bytes = key_str.encode("utf-8")

    msg = f"{access_token};{token_payment};{sig_time_sec};{package_code};".encode("utf-8")

    return hmac.new(key_bytes, msg, hashlib.sha512).hexdigest()

def make_x_signature_loyalty(
    sig_time_sec: int,
    package_code: str,
    token_confirmation: str,
    path: str,
) -> str:
    secret = _get_key("X_API_BASE_SECRET")
    key_str = f"{secret};{sig_time_sec}#ae-hei_9Tee6he+Ik3Gais5=;POST;{path};{sig_time_sec}"
    key_bytes = key_str.encode("utf-8")
    
    msg = f"{token_confirmation};{sig_time_sec};{package_code};".encode("utf-8")
    
    return hmac.new(key_bytes, msg, hashlib.sha512).hexdigest()

def make_x_signature_bounty_allotment(
    sig_time_sec: int,
    package_code: str,
    token_confirmation: str,
    path: str,
    destination_msisdn: str,
) -> str:
    secret = _get_key("X_API_BASE_SECRET")
    key_str = f"{secret};{sig_time_sec}#ae-hei_9Tee6he+Ik3Gais5=;{destination_msisdn};POST;{path};{sig_time_sec}"
    key_bytes = key_str.encode("utf-8")
    
    msg = f"{token_confirmation};{sig_time_sec};{destination_msisdn};{package_code};".encode("utf-8")
    
    return hmac.new(key_bytes, msg, hashlib.sha512).hexdigest()

def make_x_signature_basic(
    method: str,
    path: str,
    sig_time_sec: int,
) -> str:
    secret = _get_key("X_API_BASE_SECRET")
    key_str = f"{secret};{method};{path};{sig_time_sec}"
    key_bytes = key_str.encode("utf-8")

    msg = f"{sig_time_sec};en;".encode("utf-8")

    return hmac.new(key_bytes, msg, hashlib.sha512).hexdigest()
