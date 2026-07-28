import json
import urllib.request

url = 'https://hudson-social.odoo.com'
db = 'hudson-social'
email = 'nandusaji20012001@gmail.com'
api_key = '04faf49029b6972ebea6c145572b4060bf372e05'

def _jsonrpc(endpoint, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(endpoint, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8')).get('result')

endpoint = f"{url}/jsonrpc"
auth = _jsonrpc(endpoint, {
    "jsonrpc": "2.0", "method": "call", "id": 1,
    "params": {"service": "common", "method": "authenticate", "args": [db, email, api_key, {}]}
})

if auth:
    res1 = _jsonrpc(endpoint, {
        "jsonrpc": "2.0", "method": "call", "id": 2,
        "params": {"service": "object", "method": "execute_kw", "args": [
            db, auth, api_key, "social.post", "fields_get", [], {"attributes": ["string", "type"]}
        ]}
    })
    print("POST FIELDS:", json.dumps(list(res1.keys()) if res1 else None))

    res2 = _jsonrpc(endpoint, {
        "jsonrpc": "2.0", "method": "call", "id": 3,
        "params": {"service": "object", "method": "execute_kw", "args": [
            db, auth, api_key, "social.stream.post", "fields_get", [], {"attributes": ["string", "type"]}
        ]}
    })
    print("STREAM POST FIELDS:", json.dumps(list(res2.keys()) if res2 else None))
