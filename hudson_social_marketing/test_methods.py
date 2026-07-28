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
    # Check what fields live_posts has (per-platform posts)
    res = _jsonrpc(endpoint, {
        "jsonrpc": "2.0", "method": "call", "id": 2,
        "params": {"service": "object", "method": "execute_kw", "args": [
            db, auth, api_key, "social.live.post", "fields_get", [], {"attributes": ["string", "type"]}
        ]}
    })
    if res:
        print("LIVE POST FIELDS:", json.dumps(list(res.keys())))
    else:
        print("social.live.post not available or returned null")
    
    # Also check what image upload method the social.post has
    # Try to see if image_ids can accept binary attachments
    post_res = _jsonrpc(endpoint, {
        "jsonrpc": "2.0", "method": "call", "id": 3,
        "params": {"service": "object", "method": "execute_kw", "args": [
            db, auth, api_key, "social.post", "search_read", [[]], 
            {"fields": ["id", "image_ids", "message", "state"], "limit": 2}
        ]}
    })
    print("POSTS:", json.dumps(post_res, indent=2))
