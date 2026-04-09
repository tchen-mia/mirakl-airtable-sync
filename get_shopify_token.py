"""
One-time script to get a Shopify offline access token via OAuth.

1. Add http://localhost:3000/callback to your app's Redirect URLs in Partners dashboard
2. Fill in CLIENT_ID, CLIENT_SECRET, and SHOP below
3. Run: python get_shopify_token.py
4. Browser will open — click Install if prompted (or it redirects automatically)
5. Token will print in terminal — save it as SHOPIFY_API_TOKEN in GitHub Secrets
"""

import http.server
import urllib.parse
import webbrowser
import requests

CLIENT_ID = 'd9bc84dbc9f836c74952622ef1d0310b'
CLIENT_SECRET = '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'
SHOP = '198cg7-99.myshopify.com'
REDIRECT_URI = 'http://localhost:3000/callback'
SCOPES = 'read_products,write_orders,read_orders'

auth_url = (
    f"https://{SHOP}/admin/oauth/authorize"
    f"?client_id={CLIENT_ID}"
    f"&scope={SCOPES}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
    f"&grant_options[]=value"
)

print(f"Opening browser for OAuth authorization...")
webbrowser.open(auth_url)
print("Waiting for callback on http://localhost:3000 ...")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = params.get('code', [None])[0]
        if code:
            resp = requests.post(
                f"https://{SHOP}/admin/oauth/access_token",
                json={
                    'client_id': CLIENT_ID,
                    'client_secret': CLIENT_SECRET,
                    'code': code,
                },
                timeout=15,
            )
            print(f"Token exchange status: {resp.status_code}")
            print(f"Token exchange response: {resp.text!r}")
            data = resp.json() if resp.text.strip() else {}
            token = data.get('access_token')
            if token:
                print(f"\n✅ Access token: {token}")
                print("\nSave this as SHOPIFY_API_TOKEN in your GitHub Secrets.")
                body = b"Token captured! Check your terminal."
            else:
                print(f"\n❌ Error: {data}")
                body = b"Error capturing token. Check terminal."
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code received.")

    def log_message(self, format, *args):
        pass  # suppress request logs


server = http.server.HTTPServer(('localhost', 3000), Handler)
server.handle_request()
