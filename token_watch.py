#!/usr/bin/env python3
"""
META広告トークンの期限を監視し、7日前・3日前・当日にLINE通知を送る。
cron: 毎日朝8時JST(23時UTC)に実行
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

# トークン期限チェック（.envのコメントから日付を取得）
env_text = env_path.read_text()
expire_date = None
for line in env_text.splitlines():
    if '有効期限' in line and '2026' in line:
        # "# 有効期限: 2026-07-30" から日付を抽出
        import re
        m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
        if m:
            expire_date = datetime.date.fromisoformat(m.group(1))
            break

if not expire_date:
    print('期限日が.envに見つかりません')
    exit(0)

today = datetime.date.today()
days_left = (expire_date - today).days

print(f'トークン期限: {expire_date} (残り{days_left}日)')

if days_left == 7:
    send_line(
        f'⚠️ META広告トークンが7日後に期限切れになります\n'
        f'期限: {expire_date}\n\n'
        f'【更新手順】\n'
        f'① https://developers.facebook.com/tools/debug/accesstoken/ を開く\n'
        f'② 現在のトークンを貼り付けて「デバッグ」\n'
        f'③「アクセストークンを延長」をクリック\n'
        f'④ 新トークンをClaudeに送って更新してもらう'
    )
elif days_left == 3:
    send_line(
        f'🚨 META広告トークンが3日後に期限切れです！\n'
        f'期限: {expire_date}\n'
        f'早めに更新してください！'
    )
elif days_left <= 0:
    send_line(
        f'🔴 META広告トークンが期限切れです！\n'
        f'広告の自動改善が止まっています。\n'
        f'すぐにトークンを更新してください。'
    )
else:
    print(f'期限まで{days_left}日。通知不要。')
