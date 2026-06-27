#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
META広告 自動改善スクリプト（マルチキャンペーン対応）

対象キャンペーン:
  - 魂ナビ診断（32-45_キャリア迷子_広め）
  - BNI×NiceMeet（BNI_カスタムオーディエンス）

実行するたびに以下を行う（キャンペーンごと）:
  1. 全広告のパフォーマンスを取得・分析
  2. 低パフォーマンス広告を自動停止（¥500以上消化・リード0）
  3. 勝ち広告のコピーをベースにClaude APIで新バリエーション生成
  4. 新広告をPAUSEDで自動投入
  5. LINE通知でレポート送信

安全設計:
  - 新広告は必ずPAUSEDで作成（いきなり課金されない）
  - 広告の削除は行わない（停止のみ）
  - 最低消化額に達していない広告は判断しない

使い方:
  python3 meta_ad_auto_improve.py           # 全キャンペーン実行
  python3 meta_ad_auto_improve.py --dry-run # 確認モード（変更なし）
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

TOKEN         = os.environ.get('META_ACCESS_TOKEN', '')
AD_ACCOUNT    = os.environ.get('META_AD_ACCOUNT_ID', '')
PAGE_ID       = os.environ.get('META_PAGE_ID', '')
IG_USER_ID    = os.environ.get('META_INSTAGRAM_USER_ID', '')
API_VER       = os.environ.get('META_API_VERSION', 'v25.0')
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
LINE_TOKEN    = os.environ.get('LINE_NOTIFY_TOKEN', '')
BASE          = f'https://graph.facebook.com/{API_VER}'

# 判断基準
MIN_SPEND_TO_JUDGE = 500    # ¥500以上消化した広告のみ判断
PAUSE_IF_CPR_OVER  = 800    # CPR ¥800超 → 停止候補
MIN_LEADS_FOR_WIN  = 2      # 勝ち広告の最低リード数

DRY_RUN = '--dry-run' in sys.argv

HERE    = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(HERE, 'improve_logs')
os.makedirs(LOG_DIR, exist_ok=True)
today   = datetime.date.today().isoformat()

# ── BNIバナー定義 ─────────────────────────────────────────
BNI_BANNERS = [
    {
        "file": "bni_banner1.png",
        "name_tag": "01_全自動",
        "message": ("1to1のたびに、予約調整して、通話して、メモ取って、文字起こしして、転記して…もう手作業はやめませんか。\n"
                    "NiceMeetなら通話が終わると、AIが文字起こし・要約・GAINS記録まで自動。\n"
                    "月1,980円・30日間無料お試し。"),
        "headline": "予約・通話・議事録、ぜんぶ自動。",
        "description": "30日無料・いつでも解約OK",
    },
    {
        "file": "bni_banner2.png",
        "name_tag": "02_GAINS記録",
        "message": ("「あの人のGAINS、何だっけ…」週例会の前、毎回そう思っていませんか。\n"
                    "話した内容を覚えていないと、的確な紹介はできません。\n"
                    "AIが1to1を記録し、GAINSを自動整理。月1,980円・30日無料。"),
        "headline": "その1to1、ちゃんと残ってますか？",
        "description": "BNI専用・30日無料",
    },
    {
        "file": "bni_banner3.png",
        "name_tag": "03_ツール統合",
        "message": ("予約調整・通話・文字起こし・メモ管理。バラバラに揃えると月5,000円超え、しかも手作業の連携で疲弊します。\n"
                    "NiceMeetはぜんぶ入って月1,980円。予約からAI議事録まで一体型。30日無料。"),
        "headline": "ツールがバラバラだと、結局やらなくなる。",
        "description": "月1,980円・30日無料",
    },
    {
        "file": "bni_banner4.png",
        "name_tag": "04_言った言わない",
        "message": ("オンライン面談の予約から議事録まで、AIが自動でまとめます。\n"
                    "通話が終わると文字起こし・要約が手元に届く。\n"
                    "記録の手間から解放されて、面談そのものに集中できます。月1,980円・30日無料。"),
        "headline": "面談の「言った言わない」をなくす",
        "description": "AI議事録・30日無料",
    },
    {
        "file": "bni_banner5.png",
        "name_tag": "05_シンプル訴求",
        "message": ("AIが文字起こし・要約・GAINS保存まで自動。予約も通話も、これ一つ。\n"
                    "月1,980円で全部入り。30日間無料・カード不要・いつでも解約OK。\n"
                    "まずは無料で試してみてください。"),
        "headline": "その1to1、記録してる？",
        "description": "30日無料・カード不要",
    },
]

# ── キャンペーン設定 ──────────────────────────────────────
def _get_tamashi_banners():
    try:
        from meta_ad_swap import BANNERS
        return BANNERS
    except Exception:
        return []

CAMPAIGNS = [
    {
        "name": "魂ナビ診断",
        "adset_id": "120243807308920485",
        "link_url": "https://tamashiinavi.com/navi",
        "banner_dir": os.path.join(HERE, "ad_banners"),
        "banners": None,  # 実行時にmeta_ad_swapから取得
        "prompt_product": "「魂のナビ診断」という8問の無料診断LP（https://tamashiinavi.com/navi）",
        "prompt_target": "32〜45歳、キャリアに迷いや違和感を感じているビジネスパーソン（男女）",
        "prompt_goal": "リード獲得（無料診断への誘導）",
        "prompt_ng": "効果保証・体験談の断言・「必ず」「絶対」などの過剰表現",
    },
    {
        "name": "BNI×NiceMeet",
        "adset_id": "120245411657240485",
        "link_url": "https://meet.gaiaarts.org/bni.html",
        "banner_dir": os.path.join(HERE, "bni_banners"),
        "banners": BNI_BANNERS,
        "prompt_product": ("「NiceMeet」BNI会員向けオンライン1on1ツール（https://meet.gaiaarts.org/bni.html）\n"
                           "月額¥1,980・30日無料・予約〜通話〜AI文字起こし・GAINS自動記録まで一体型"),
        "prompt_target": "BNI会員・経営者・士業・コンサルタント（30〜55歳）",
        "prompt_goal": "LPクリック・無料トライアル登録への誘導",
        "prompt_ng": "効果保証・誇大表現・BNI公式を名乗る表現",
    },
]


# ── バナー番号パーサ ─────────────────────────────────────────
def parse_banner_idx(ad_name):
    """広告名からバナーのインデックス(0始まり)を取得。
    '1-4' → 3, 'BNI_02_GAINS記録' → 1, '魂ナビ_06_...' → 5"""
    nums = __import__('re').findall(r'\d+', ad_name)
    return int(nums[-1]) - 1 if nums else -1

# ── META API ─────────────────────────────────────────────
def meta_get(path, **params):
    params['access_token'] = TOKEN
    url = f'{BASE}/{path}?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f'[ERROR] API GET {e.code}: {e.read().decode()}')
        return {}

def meta_post(path, **data):
    data['access_token'] = TOKEN
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(f'{BASE}/{path}', data=body, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f'[ERROR] API POST {e.code}: {e.read().decode()}')
        return {}


# ── Claude API でコピー生成 ───────────────────────────────
def generate_copy_variations(winning_ads: list, camp: dict) -> list:
    if not ANTHROPIC_KEY:
        print('  ANTHROPIC_API_KEY 未設定 → コピー生成スキップ')
        return []
    if not winning_ads:
        return []

    winners_text = '\n'.join([
        f'【{a["name"]}】CPR ¥{a["cpr"]:.0f} / {a["leads"]}件\n'
        f'メインテキスト: {a["message"]}\n見出し: {a["headline"]}'
        for a in winning_ads
    ])

    # 次の番号を既存広告名から自動検出
    existing_nums = []
    for a in winning_ads:
        parts = a['name'].replace('魂ナビ_', '').replace('BNI_', '').split('_')
        try:
            existing_nums.append(int(parts[0]))
        except Exception:
            pass
    next_num = max(existing_nums, default=5) + 1

    prompt = f"""あなたはMETA広告のコピーライターです。
以下は{camp['prompt_product']}の
META広告で成果が出ているクリエイティブです。

{winners_text}

ターゲット: {camp['prompt_target']}
目標: {camp['prompt_goal']}
禁止: {camp['prompt_ng']}

上記の「刺さっている角度・言葉の質感」を活かしながら、
**まだ試していない新しい切り口**で2パターンのテキストを作成してください。

各パターンを以下のJSON形式で返してください（他の説明は不要）:
[
  {{
    "name_tag": "{next_num:02d}_[テーマ名（日本語10文字以内）]",
    "message": "メインテキスト（150文字以内、改行\\nで表現）",
    "headline": "見出し（20文字以内）",
    "description": "説明文（15文字以内）"
  }},
  {{
    "name_tag": "{next_num+1:02d}_[テーマ名（日本語10文字以内）]",
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
            start = text.find('[')
            end   = text.rfind(']') + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
    except Exception as e:
        print(f'  Claude API エラー: {e}')
    return []


# ── 画像アップロード ──────────────────────────────────────
def upload_image(filepath):
    with open(filepath, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    res = meta_post(f'{AD_ACCOUNT}/adimages', bytes=b64)
    images = res.get('images', {})
    if not images:
        print(f'[ERROR] 画像アップロード失敗: {filepath}')
        return None
    return next(iter(images.values()))['hash']


# ── 新広告を作成（PAUSED） ────────────────────────────────
def create_ad(adset_id: str, camp: dict, banner: dict, image_hash: str) -> str:
    story = {
        'page_id': PAGE_ID,
        'link_data': {
            'image_hash': image_hash,
            'link': camp['link_url'],
            'message': banner['message'],
            'name': banner['headline'],
            'description': banner['description'],
            'call_to_action': {'type': 'SEE_DETAILS', 'value': {'link': camp['link_url']}},
        },
    }
    if IG_USER_ID:
        story['instagram_user_id'] = IG_USER_ID

    prefix = '魂ナビ' if '魂ナビ' in camp['name'] else 'BNI'
    cr = meta_post(f'{AD_ACCOUNT}/adcreatives',
                   name=f'{prefix}_{banner["name_tag"]}',
                   object_story_spec=json.dumps(story, ensure_ascii=False))
    ad = meta_post(f'{AD_ACCOUNT}/ads',
                   name=f'{prefix}_{banner["name_tag"]}',
                   adset_id=adset_id,
                   creative=json.dumps({'creative_id': cr['id']}),
                   status='PAUSED')
    return ad.get('id', '')


# ── LINE通知 ──────────────────────────────────────────────
def send_line(msg: str):
    if LINE_TOKEN:
        try:
            body = urllib.parse.urlencode({'message': msg}).encode()
            req  = urllib.request.Request(
                'https://notify-api.line.me/api/notify',
                data=body,
                headers={'Authorization': f'Bearer {LINE_TOKEN}'}
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f'  LINE通知エラー: {e}')


# ── 1キャンペーンの改善処理 ──────────────────────────────
def run_campaign(camp: dict) -> dict:
    """1つのキャンペーン設定に対して改善処理を実行。結果dictを返す。"""
    name     = camp['name']
    adset_id = camp['adset_id']
    banners  = camp['banners'] or _get_tamashi_banners()

    print(f'\n{"="*55}')
    print(f'  {name}')
    print(f'{"="*55}')

    # 1. パフォーマンスデータ取得
    print('1. パフォーマンスデータ取得中...')
    ads_data = meta_get(
        f'{adset_id}/ads',
        fields='name,status,insights{impressions,clicks,spend,actions}',
        date_preset='last_7d'
    )

    ads = []
    for ad in ads_data.get('data', []):
        ins    = ad.get('insights', {}).get('data', [{}])[0] if ad.get('insights') else {}
        spend  = float(ins.get('spend', 0))
        leads  = sum(int(a['value']) for a in ins.get('actions', [])
                     if a['action_type'] in ('lead', 'onsite_conversion.lead_grouped',
                                             'link_click', 'offsite_conversion.fb_pixel_lead'))
        cpr    = spend / leads if leads > 0 else float('inf')

        # バナーからコピーを取得（名前から番号を解析）
        message = headline = ''
        idx = parse_banner_idx(ad['name'])
        if 0 <= idx < len(banners):
            message  = banners[idx]['message']
            headline = banners[idx]['headline']

        ads.append({
            'id': ad['id'], 'name': ad['name'], 'status': ad['status'],
            'spend': spend, 'leads': leads, 'cpr': cpr,
            'message': message, 'headline': headline,
        })

    if not ads:
        print('  広告データなし。スキップ。')
        return {'name': name, 'total_spend': 0, 'total_leads': 0, 'avg_cpr': 0,
                'paused': [], 'created': []}

    # 2. 分析・判断
    print('\n2. 分析結果:')
    print(f"  {'広告名':<25} {'リード':>6} {'CPR':>8} {'消化':>8}  判断")
    print('  ' + '-' * 60)

    total_spend = sum(a['spend'] for a in ads)
    total_leads = sum(a['leads'] for a in ads)
    avg_cpr     = total_spend / total_leads if total_leads > 0 else 0

    win_candidates = sorted(
        [a for a in ads
         if a['spend'] >= MIN_SPEND_TO_JUDGE
         and a['leads'] >= MIN_LEADS_FOR_WIN
         and a['cpr'] < PAUSE_IF_CPR_OVER],
        key=lambda a: a['cpr']
    )
    winner_ids = {a['id'] for a in win_candidates[:2]}

    to_pause = []
    winners  = []
    for a in ads:
        if a['spend'] < MIN_SPEND_TO_JUDGE:
            verdict = '⚪ データ不足'
        elif a['leads'] == 0:
            verdict = '🔴 停止候補（リード0）'
            to_pause.append(a)
        elif a['cpr'] > PAUSE_IF_CPR_OVER:
            verdict = '🔴 停止候補（CPR高）'
            to_pause.append(a)
        elif a['id'] in winner_ids:
            verdict = '🟢 勝ち広告'
            winners.append(a)
        else:
            verdict = '🟡 様子見'

        cpr_str = f'¥{a["cpr"]:.0f}' if a['cpr'] != float('inf') else '-'
        print(f"  {a['name']:<25} {a['leads']:>6} {cpr_str:>8} ¥{a['spend']:>6.0f}  {verdict}")

    print(f'\n  合計: ¥{total_spend:.0f} / {total_leads}件 / 平均CPR ¥{avg_cpr:.0f}')

    # 3. 低パフォーマンス広告を停止
    paused_names = []
    if to_pause:
        print(f'\n3. 停止: {len(to_pause)}本')
        for a in to_pause:
            print(f'   → {a["name"]}')
            if not DRY_RUN:
                meta_post(a['id'], status='PAUSED')
                paused_names.append(a['name'])
    else:
        print('\n3. 停止対象なし')

    # 4. 新コピー生成・投入
    new_ad_names = []
    if winners:
        print(f'\n4. 勝ち広告({len(winners)}本)ベースで新バリエーション生成中...')
        new_banners = generate_copy_variations(winners, camp)

        if new_banners:
            best     = min(winners, key=lambda a: a['cpr'])
            img_file = None
            idx = parse_banner_idx(best['name'])
            if 0 <= idx < len(banners):
                img_file = os.path.join(camp['banner_dir'], banners[idx]['file'])

            if img_file and os.path.exists(img_file):
                print(f'   使用画像: {os.path.basename(img_file)}')
                if not DRY_RUN:
                    image_hash = upload_image(img_file)
                    if image_hash:
                        for nb in new_banners:
                            ad_id = create_ad(adset_id, camp, nb, image_hash)
                            print(f'   ✓ 新広告作成(PAUSED): {nb["name_tag"]}  id={ad_id}')
                            new_ad_names.append(nb['name_tag'])
                else:
                    for nb in new_banners:
                        print(f'   [DRY] 予定: {nb["name_tag"]} / {nb["headline"]}')
                        print(f'         {nb["message"][:60]}...')
            else:
                print(f'   [WARN] 画像ファイルが見つかりません: {img_file}')
        else:
            print('   新コピー生成なし')
    else:
        print('\n4. 勝ち広告なし（データ蓄積待ち）→ 新広告作成スキップ')

    return {
        'name': name,
        'total_spend': total_spend,
        'total_leads': total_leads,
        'avg_cpr': avg_cpr,
        'paused': paused_names,
        'created': new_ad_names,
    }


# ── メイン ───────────────────────────────────────────────
def main():
    print(f'{"="*55}')
    print(f'META広告 自動改善 実行: {today}')
    if DRY_RUN:
        print('【DRY RUNモード: 実際の変更は行いません】')
    print(f'{"="*55}')

    if not TOKEN:
        print('[ERROR] META_ACCESS_TOKEN が未設定')
        sys.exit(1)

    results = []
    for camp in CAMPAIGNS:
        result = run_campaign(camp)
        results.append(result)

    # ログ保存
    log_file = os.path.join(LOG_DIR, f'improve_{today}.log')
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write(f'META広告 自動改善レポート {today}\n\n')
        for r in results:
            f.write(f'■ {r["name"]}\n')
            f.write(f'  ¥{r["total_spend"]:.0f} / {r["total_leads"]}件 / CPR ¥{r["avg_cpr"]:.0f}\n')
            if r['paused']:  f.write(f'  停止: {", ".join(r["paused"])}\n')
            if r['created']: f.write(f'  新広告: {", ".join(r["created"])}\n')
            f.write('\n')
    print(f'\nログ保存: {log_file}')

    # LINE通知
    line_msg = f'📊 META広告 自動改善レポート {today}\n'
    for r in results:
        line_msg += f'\n■ {r["name"]}\n'
        line_msg += f'  ¥{r["total_spend"]:.0f} / {r["total_leads"]}件 / CPR ¥{r["avg_cpr"]:.0f}\n'
        if r['paused']:  line_msg += f'  🔴停止: {", ".join(r["paused"])}\n'
        if r['created']: line_msg += f'  🆕新広告(PAUSED): {", ".join(r["created"])}\n'
        if not r['paused'] and not r['created']:
            line_msg += '  ✅変更なし\n'

    print('\n--- LINE通知 ---')
    print(line_msg)
    if not DRY_RUN:
        send_line(line_msg)

    print('\n完了!')


if __name__ == '__main__':
    main()
