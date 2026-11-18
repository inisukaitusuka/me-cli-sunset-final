from app.client.engsel import send_api_request

def get_segments(
    api_key: str,
    tokens: dict,
    is_enterprise: bool = False,
):
    path = "api/v8/configs/store/segments"
    payload = {
        "is_enterprise": is_enterprise,
        "lang": "en"
    }
    
    res = send_api_request(api_key, path, payload, tokens["id_token"], "POST")
    if not isinstance(res, dict) or res.get("status") != "SUCCESS":
        print("Failed to fetch segments.")
        print(f"Error: {res}")
        return None
    
    return res