import json
import urllib.request
import urllib.error

url = 'https://hudson-social.odoo.com'
db = 'hudson-social'
email = 'nandusaji20012001@gmail.com'
api_key = '04faf49029b6972ebea6c145572b4060bf372e05'

def _jsonrpc(endpoint, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        method='POST',
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8')).get('result')

endpoint = f"{url}/jsonrpc"
auth_payload = {
    "jsonrpc": "2.0",
    "method": "call",
    "id": 1,
    "params": {
        "service": "common",
        "method": "authenticate",
        "args": [db, email, api_key, {}],
    },
}
uid = _jsonrpc(endpoint, auth_payload)

if uid:
    read_payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "id": 2,
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [db, uid, api_key, "social.account", "search_read", [[]], {"fields": ["id", "name", "media_type", "media_id", "is_media_disconnected", "has_active_access_token"]}],
        },
    }
    accounts = _jsonrpc(endpoint, read_payload)
    print(json.dumps(accounts, indent=2))
