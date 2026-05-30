#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
魂のナビ診断 — META広告 自動改善スクリプト

実行するたびに以下を行う:
  1. 全広告のパフォーマンスを取得・分析
  2. 低パフォーマンス広告を自動停止（¥500以上消化・リード0）
  3. 勝ち広告のコピーをベースにClaude APIで新バリエーション生成
  4. 新広告をPAUSEDで自動投入（人間が確認してからpublish）
  5. LINE通知でレポート送信

安全設計:
  - 新広告は必ずPAUSEDで作成（いきなり課金されない）
  - 広告の削除は行わない（停止のみ）
  - 最低消化額に達していない広告は判断しない
  - レポートをログファイルに保存

使い方:
  python3 meta_ad_auto_improve.py          # 通常実行
  python3 meta_ad_auto_improve.py --dry-run # 実際には変更しない確認モード
"""

import os, sys, json, base64, datetime, urllib.request, urllib.parse, urllib.error

# ── .env 読み込み ─────────────────────────────────────────
def load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    for fname in ['.env', '../../.env']:
        path = os.path.join(here, fname)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break

load_env()

TOKEN      = os.environ.get('META_ACCESS_TOKEN', '')
AD_ACCOUNT = os.environ.get('META_AD_ACCOUNT_ID', '')
PAGE_ID    = os.environ.get('META_PAGE_ID', '')
IG_USER_ID = os.environ.get('META_INSTAGRAM_USER_ID', '')
LINK_URL   = os.environ.get('META_LINK_URL', 'https://tamashiinavi.com/navi')
API_VER    = os.environ.get('META_API_VERSION', 'v25.0')
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
LINE_TOKEN = os.environ.get('LINE_NOTIFY_TOKEN', '')  # LINE Notify token（オプション）
BASE       = f'https://graph.facebook.com/{API_VER}'

# 対象広告セットID（32-45_キャリア迷子_広め(Adv+)）
TARGET_ADSET_ID = '120243807308920485'

# 判断基準
MIN_SPEND_TO_JUDGE = 500     # ¥500以上消化した広告のみ判断
PAUSE_IF_CPR_OVER  = 800     # CPR ¥800超 → 停止候補
MIN_LEADS_FOR_WIN  = 2       # 勝ち広告の最低リード数
DRY_RUN = '--dry-run' in sys.argv

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, 'improve_logs')
os.makedirs(LOG_DIR, exist_ok=True)
today = datetime.date.today().isoformat()
LOG_FILE = os.path.join(LOG_DIR, f'improve_{today}.log')
BANNER_DIR = os.path.abspath(os.path.join(HERE, 'ad_banners'))

log_lines = []

def log(msg):
    print(msg)
    log_lines.append(msg)

def die(msg):
    log(f'[ERROR] {msg}')
    sys.exit(1)


# ── META API ─────────────────────────────────────────────
def meta_get(path, **params):
    params['access_token'] = TOKEN
    url = f'{BASE}/{path}?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        die(f'API GET エラー {e.code}: {e.read().decode()}')

def meta_post(path, **data):
    data['access_token'] = TOKEN
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(f'{BASE}/{path}', data=body, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        die(f'API POST エラー {e.code}: {e.read().decode()}')


# ── Claude API でコピー生成 ───────────────────────────────
def generate_copy_variations(winning_ads: list) -> list:
    """勝ち広告のコピーをベースに、新しいテキストバリエーションを生成する。"""
    if not ANTHROPIC_KEY:
        log('  ANTHROPIC_API_KEY 未設定 → コピー生成スキップ')
        return []

    winners_text = '\n'.join([
        f'【{a["name"]}】CPR ¥{a["cpr"]:.0f} / {a["leads"]}件\n'
        f'メインテキスト: {a["message"]}\n見出し: {a["headline"]}'
        for a in winning_ads
    ])

    prompt = f"""あなたはMETA広告のコピーライターです。
以下は「魂のナビ診断」という8問の無料診断LP（https://tamashiinavi.com/navi）の
META広告で成果が出ているクリエイティブです。

{winners_text}

ターゲット: 32〜45歳、キャリアに迷いや違和感を感じているビジネスパーソン（男女）
目標: リード獲得（無料診断への誘導）
禁止: 効果保証・体験談の断言・「必ず」「絶対」などの過剰表現

上記の「刺さっている角度・言葉の質感」を活かしながら、
**まだ試していない新しい切り口**で2パターンのテキストを作成してください。

各パターンを以下のJSON形式で返してください（他の説明は不要）:
[
  {{
    "name_tag": "06_[テーマ名]",
    "message": "メインテキスト（150文字以内、改行\\nで表現）",
    "headline": "見出し（20文字以内）",
    "description": "説明文（15文字以内）"
  }},
  {{
    "name_tag": "07_[テーマ名]",
    "message": "メインテキスト（150文字以内、改行\\nで表現）",
    "headline": "見出し（20文字以内）",
    "description": "説明文（15文字以内）"
  }}
]"""

    req_body = json.dumps({
        'model': 'claude-sonnet-4-6',
        'max_tokens': 1000,
        'messages': [{'role': 'user', 'content': prompt}]
    }).encode()

    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=req_body,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': ANTHROPIC_KEY,
            'anthropic-version': '2023-06-01',
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
            text = resp['content'][0]['text'].strip()
            # JSON部分を抽出
            start = text.find('[')
            end = text.rfind(']') + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
    except Exception as e:
        log(f'  Claude API エラー: {e}')
    return []


# ── 画像アップロード ──────────────────────────────────────
def upload_image(filepath):
    with open(filepath, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    res = meta_post(f'{AD_ACCOUNT}/adimages', bytes=b64)
    images = res.get('images', {})
    if not images:
        die(f'画像アップロード失敗: {filepath}')
    return next(iter(images.values()))['hash']


# ── 新広告を作成（PAUSED） ────────────────────────────────
def create_ad(adset_id: str, banner: dict, image_hash: str) -> str:
    story = {
        'page_id': PAGE_ID,
        'link_data': {
            'image_hash': image_hash,
            'link': LINK_URL,
            'message': banner['message'],
            'name': banner['headline'],
            'description': banner['description'],
            'call_to_action': {'type': 'SEE_DETAILS', 'value': {'link': LINK_URL}},
        },
    }
    if IG_USER_ID:
        story['instagram_user_id'] = IG_USER_ID

    cr = meta_post(f'{AD_ACCOUNT}/adcreatives',
                   name=f'魂ナビ_{banner["name_tag"]}',
                   object_story_spec=json.dumps(story, ensure_ascii=False))
    ad = meta_post(f'{AD_ACCOUNT}/ads',
                   name=f'魂ナビ_{banner["name_tag"]}',
                   adset_id=adset_id,
                   creative=json.dumps({'creative_id': cr['id']}),
                   status='PAUSED')
    return ad['id']


# ── LINE通知 ──────────────────────────────────────────────
def send_line(msg: str):
    # LINE Notify
    if LINE_TOKEN:
        try:
            body = urllib.parse.urlencode({'message': msg}).encode()
            req = urllib.request.Request(
                'https://notify-api.line.me/api/notify',
                data=body,
                headers={'Authorization': f'Bearer {LINE_TOKEN}'}
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            log(f'  LINE通知エラー: {e}')

    # LINE Messaging API (seo-improver と同じ仕組み)
    line_hair = os.path.expanduser('~/.secrets/line_seo_token.txt')
    owner_id  = os.path.expanduser('~/.secrets/owner_line_id.txt')
    if os.path.exists(line_hair) and os.path.exists(owner_id):
        try:
            token  = open(line_hair).read().strip()
            owner  = open(owner_id).read().strip()
            body   = json.dumps({'to': owner, 'messages': [{'type': 'text', 'text': msg}]}).encode()
            req    = urllib.request.Request(
                'https://api.line.me/v2/bot/message/push',
                data=body,
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}
            )
            urllib.request.urlopen(req, timeout=10)
            log('  LINE通知送信完了')
        except Exception as e:
            log(f'  LINE通知エラー: {e}')


# ── メイン処理 ────────────────────────────────────────────
def main():
    log(f'{"="*50}')
    log(f'META広告 自動改善 実行: {today}')
    if DRY_RUN:
        log('【DRY RUNモード: 実際の変更は行いません】')
    log(f'{"="*50}\n')

    if not TOKEN:
        die('META_ACCESS_TOKEN が未設定')

    # ── 1. パフォーマンスデータ取得 ──────────────────────
    log('1. パフォーマンスデータ取得中...')
    ads_data = meta_get(
        f'{TARGET_ADSET_ID}/ads',
        fields='name,status,insights{impressions,clicks,spend,actions}',
        date_preset='last_7d'
    )

    ads = []
    for ad in ads_data.get('data', []):
        ins = ad.get('insights', {}).get('data', [{}])[0] if ad.get('insights') else {}
        spend  = float(ins.get('spend', 0))
        leads  = sum(int(a['value']) for a in ins.get('actions', [])
                     if a['action_type'] in ('lead', 'onsite_conversion.lead_grouped'))
        impressions = int(ins.get('impressions', 0))
        cpr    = spend / leads if leads > 0 else float('inf')

        # BANNERS配列からコピーを取得
        message  = ''
        headline = ''
        try:
            from meta_ad_swap import BANNERS
            idx = int(ad['name'].split('-')[-1]) - 1
            if 0 <= idx < len(BANNERS):
                message  = BANNERS[idx]['message']
                headline = BANNERS[idx]['headline']
        except Exception:
            pass

        ads.append({
            'id': ad['id'], 'name': ad['name'], 'status': ad['status'],
            'spend': spend, 'leads': leads, 'impressions': impressions,
            'cpr': cpr, 'message': message, 'headline': headline,
        })

    if not ads:
        log('広告データなし。終了。')
        return

    # ── 2. 分析・判断 ─────────────────────────────────────
    log('\n2. 分析結果:')
    log(f"  {'広告名':<20} {'リード':>6} {'CPR':>8} {'消化':>8} {'判断'}")
    log('  ' + '-' * 55)

    judged = [a for a in ads if a['spend'] >= MIN_SPEND_TO_JUDGE]
    total_spend  = sum(a['spend'] for a in ads)
    total_leads  = sum(a['leads'] for a in ads)
    avg_cpr = total_spend / total_leads if total_leads > 0 else 0

    to_pause = []
    winners  = []

    for a in ads:
        if a['spend'] < MIN_SPEND_TO_JUDGE:
            verdict = '⚪ データ不足'
        elif a['leads'] == 0:
            verdict = '🔴 停止候補（リード0）'
            to_pause.append(a)
        elif a['cpr'] > PAUSE_IF_CPR_OVER:
            verdict = f'🔴 停止候補（CPR高）'
            to_pause.append(a)
        elif a['leads'] >= MIN_LEADS_FOR_WIN and (avg_cpr == 0 or a['cpr'] <= avg_cpr * 0.9):
            verdict = '🟢 勝ち広告'
            winners.append(a)
        else:
            verdict = '🟡 様子見'

        cpr_str = f'¥{a["cpr"]:.0f}' if a['cpr'] != float('inf') else '-'
        log(f"  {a['name']:<20} {a['leads']:>6} {cpr_str:>8} ¥{a['spend']:>6.0f}  {verdict}")

    log(f'\n  合計: ¥{total_spend:.0f} / {total_leads}件リード / 平均CPR ¥{avg_cpr:.0f}')

    # ── 3. 低パフォーマンス広告を停止 ───────────────────
    paused_names = []
    if to_pause:
        log(f'\n3. 低パフォーマンス広告を停止: {len(to_pause)}本')
        for a in to_pause:
            log(f'   → {a["name"]} を PAUSED に')
            if not DRY_RUN:
                meta_post(a['id'], status='PAUSED')
                paused_names.append(a['name'])
    else:
        log('\n3. 停止対象なし')

    # ── 4. 勝ち広告ベースで新コピー生成・投入 ──────────
    new_ad_names = []
    if winners:
        log(f'\n4. 勝ち広告({len(winners)}本)ベースで新バリエーション生成中...')
        new_banners = generate_copy_variations(winners)

        if new_banners:
            # 既存バナー画像の中で最も成果が良いものを使いまわす
            best = min(winners, key=lambda a: a['cpr'])
            idx  = 0
            try:
                idx = int(best['name'].split('-')[-1]) - 1
            except Exception:
                idx = 0
            from meta_ad_swap import BANNERS
            banner_file = BANNERS[min(idx, len(BANNERS)-1)]['file']
            img_path = os.path.join(BANNER_DIR, banner_file)

            if os.path.exists(img_path):
                log(f'   使用画像: {banner_file}')
                if not DRY_RUN:
                    image_hash = upload_image(img_path)
                    for nb in new_banners:
                        ad_id = create_ad(TARGET_ADSET_ID, nb, image_hash)
                        log(f'   ✓ 新広告作成(PAUSED): {nb["name_tag"]}  id={ad_id}')
                        new_ad_names.append(nb['name_tag'])
                else:
                    for nb in new_banners:
                        log(f'   [DRY] 新広告を作成予定: {nb["name_tag"]}')
                        log(f'         見出し: {nb["headline"]}')
                        log(f'         本文: {nb["message"][:60]}...')
            else:
                log(f'   画像ファイルが見つかりません: {img_path}')
        else:
            log('   新コピー生成なし')
    else:
        log('\n4. 勝ち広告なし（データ蓄積待ち）→ 新広告作成スキップ')

    # ── 5. ログ保存 & LINE通知 ──────────────────────────
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(log_lines))
    log(f'\nログ保存: {LOG_FILE}')

    # LINE通知メッセージ作成
    line_msg = (
        f'📊 魂ナビ META広告 自動改善レポート {today}\n'
        f'合計: ¥{total_spend:.0f} / {total_leads}件 / CPR ¥{avg_cpr:.0f}\n'
    )
    if paused_names:
        line_msg += f'🔴 停止: {", ".join(paused_names)}\n'
    if new_ad_names:
        line_msg += f'🆕 新広告(PAUSED): {", ".join(new_ad_names)}\n→ 広告マネージャーでプレビュー後にpublishしてください'
    if not paused_names and not new_ad_names:
        line_msg += '✅ 変更なし（データ蓄積中）'

    log('\n--- LINE通知 ---')
    log(line_msg)
    if not DRY_RUN:
        send_line(line_msg)

    log('\n完了!')


if __name__ == '__main__':
    main()
