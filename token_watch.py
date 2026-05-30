#!/usr/bin/env python3
"""
META広告トークンの期限をAPIで自動取得し、7日前・3日前・当日にLINE通知。
トークンを更新するだけで次の期限に自動追従する。
"""
import os, json, datetime, urllib.request, urllib.parse
from pathlib import Path

# .env読み込み
env_path = Path(__file__).parent / '.env'
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

TOKEN = os.environ.get('META_ACCESS_TOKEN', '')

def send_line(msg: str):
    token_path = Path('/home/ubuntu/.secrets/line_seo_token.txt')
    owner_path = Path('/home/ubuntu/.secrets/owner_line_id.txt')
    if not token_path.exists() or not owner_path.exists():
        print('LINE設定なし')
        return
    token = token_path.read_text().strip()
    owner = owner_path.read_text().strip()
    body = json.dumps({'to': owner, 'messages': [{'type': 'text', 'text': msg}]}).encode()
    req = urllib.request.Request(
        'https://api.line.me/v2/bot/message/push',
        data=body,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print('LINE通知送信完了')
    except Exception as e:
        print(f'LINE通知エラー: {e}')

# META APIでトークンの実際の期限を取得
def get_token_expire_date(token: str):
    url = (f'https://graph.facebook.com/debug_token'
           f'?input_token={token}&access_token={token}')
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
        expires_at = data.get('data', {}).get('expires_at', 0)
        if expires_at:
            return datetime.date.fromtimestamp(expires_at)
    except Exception as e:
        print(f'API期限取得エラー: {e}')
    return None

if not TOKEN:
    print('トークン未設定')
    exit(1)

expire_date = get_token_expire_date(TOKEN)
if not expire_date:
    print('期限取得失敗（トークンが無効の可能性）')
    send_line('🔴 META広告トークンの期限が確認できません。\nトークンが無効になっている可能性があります。')
    exit(1)

today = datetime.date.today()
days_left = (expire_date - today).days
print(f'トークン期限: {expire_date}（残り{days_left}日）')

if days_left <= 0:
    send_line(
        f'🔴 META広告トークンが期限切れです！\n'
        f'広告の自動改善が止まっています。\n'
        f'すぐにトークンを更新してClaudeに送ってください。'
    )
elif days_left == 3:
    send_line(
        f'🚨 META広告トークンが3日後に期限切れです！\n'
        f'期限: {expire_date}\n\n'
        f'【更新手順】\n'
        f'① https://developers.facebook.com/tools/debug/accesstoken/ を開く\n'
        f'② 現在のトークンを貼り付けて「デバッグ」\n'
        f'③「アクセストークンを延長」をクリック\n'
        f'④ 新トークンをClaudeに送って更新してもらう'
    )
elif days_left == 7:
    send_line(
        f'⚠️ META広告トークンが7日後に期限切れになります\n'
        f'期限: {expire_date}\n\n'
        f'【更新手順】\n'
        f'① https://developers.facebook.com/tools/debug/accesstoken/ を開く\n'
        f'② 現在のトークンを貼り付けて「デバッグ」\n'
        f'③「アクセストークンを延長」をクリック\n'
        f'④ 新トークンをClaudeに送って更新してもらう'
    )
else:
    print(f'通知不要（残り{days_left}日）')
