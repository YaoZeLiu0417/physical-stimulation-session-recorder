# bd_init.py
import webbrowser, urllib.parse, requests, toml
from pathlib import Path

conf_path = Path("config.toml")
cfg = toml.loads(conf_path.read_text(encoding="utf-8"))["baidu"]
AK, SK, REDIR = cfg["app_key"], cfg["secret_key"], cfg["redirect_uri"]

auth_url = ("https://openapi.baidu.com/oauth/2.0/authorize?"
            + urllib.parse.urlencode({
                "response_type": "code",
                "client_id": AK,
                "redirect_uri": REDIR,
                "scope": "basic,netdisk"
            }))

print("1) 打开并授权：", auth_url)
webbrowser.open(auth_url)

code = input("\n2) 授权后跳转到 redirect_uri，把地址栏里的 code=... 复制到这里：\n> ").strip()

token_url = "https://openapi.baidu.com/oauth/2.0/token"
resp = requests.post(token_url, data={
    "grant_type": "authorization_code",
    "code": code,
    "client_id": AK,
    "client_secret": SK,
    "redirect_uri": REDIR
}, timeout=30)
j = resp.json()
print("\n3) 返回：", j)

if "access_token" not in j:
    raise SystemExit("换取 token 失败，请检查 AK/SK/redirect_uri 与 code。")

cfg["access_token"] = j["access_token"]
cfg["refresh_token"] = j["refresh_token"]
toml.dump({"baidu": cfg}, conf_path.open("w", encoding="utf-8"))
print("\n4) 已写入 config.toml，后续应用会自动用 refresh_token 刷新。")
