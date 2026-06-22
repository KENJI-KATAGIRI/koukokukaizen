#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BNI × NiceMeet Meta広告キャンペーン作成スクリプト
- 新規キャンペーン（魂ナビとは完全分離）
- カスタムオーディエンス（BNI名刺リスト191件）へのターゲティング
- 全広告 PAUSED で作成（確認してから手動でON）
"""

import os, sys, json, base64, urllib.request, urllib.parse

# ── .env 読み込み ─────────────────────────────────────────
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, '.env')) as f:
    for line in f:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k] = v

TOKEN      = os.environ['META_ACCESS_TOKEN']
AD_ACCOUNT = os.environ['META_AD_ACCOUNT_ID']
PAGE_ID    = os.environ['META_PAGE_ID']
IG_USER_ID = os.environ.get('META_INSTAGRAM_USER_ID', '')
V          = 'v25.0'
LP_URL     = 'https://meet.gaiaarts.org/bni.html'
BANNER_DIR = os.path.join(here, 'bni_banners')

DRY_RUN = '--dry-run' in sys.argv

def meta_post(path, **data):
    data['access_token'] = TOKEN
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        f'https://graph.facebook.com/{V}/{path}',
        data=body, method='POST'
    )
    with urllib.request.urlopen(req) as r:
        res = json.loads(r.read())
    if 'error' in res:
        raise RuntimeError(f"API Error: {json.dumps(res['error'], ensure_ascii=False)}")
    return res

# ── バナー定義 ────────────────────────────────────────────
BANNERS = [
    {
        "file": "bni_banner1.png",
        "tag": "BNI_01_全自動",
        "headline": "予約・通話・議事録、ぜんぶ自動。",
        "message": "1to1のたびに、予約調整して、通話して、メモ取って、文字起こしして、転記して…もう手作業はやめませんか。NiceMeetなら通話が終わると、AIが文字起こし・要約・記録まで全部やっておきます。月1,980円・30日間無料・カード不要。",
        "description": "予約＋通話＋AI議事録が全部入り",
    },
    {
        "file": "bni_banner2.png",
        "tag": "BNI_02_GAINS記録",
        "headline": "その1to1、ちゃんと残ってますか？",
        "message": "「あの人のGAINS、何だっけ…」週例会の前、毎回そう思っていませんか。話した内容を覚えていないと、的確な紹介はできません。AIが1to1を記録し、GAINSを自動で残します。次の例会前に、サッと見返すだけ。",
        "description": "月1,980円・30日間無料・カード不要",
    },
    {
        "file": "bni_banner3.png",
        "tag": "BNI_03_ツール統合",
        "headline": "ツールがバラバラだと、結局やらなくなる。",
        "message": "予約調整・通話・文字起こし・メモ管理。バラバラに揃えると月5,000円超え、しかも手作業の連携で疲弊します。NiceMeetはぜんぶ入って月1,980円。予約から議事録・GAINS保存まで全自動。",
        "description": "予約・通話・AI議事録がこれ1つ",
    },
    {
        "file": "bni_banner4.png",
        "tag": "BNI_04_言った言わない",
        "headline": "面談の「言った言わない」をなくす",
        "message": "オンライン面談の予約から議事録まで、AIが自動でまとめます。通話が終わると文字起こし・要約が手元に届く。記録の手間から解放されて、面談そのものに集中できます。月1,980円・30日間無料。",
        "description": "予約＋通話＋AI議事録が全部入り",
    },
    {
        "file": "bni_banner5.png",
        "tag": "BNI_05_シンプル訴求",
        "headline": "その1to1、記録してる？",
        "message": "AIが文字起こし・要約・GAINS保存まで自動。予約も通話も、これ一つ。月1,980円で全部入り。30日間無料・カード不要・いつでも解約OK。まずは無料で試してみてください。",
        "description": "月1,980円で全自動",
    },
]

# ── カスタムオーディエンス（BNI名刺191件リスト） ──────────
CUSTOM_AUDIENCE_ID = '120245406889740485'  # BNI_custom_audience_email.csv (191件)

TARGETING = {
    'custom_audiences': [{'id': CUSTOM_AUDIENCE_ID}],
    'geo_locations': {'countries': ['JP']},
    # 年齢・興味関心の絞り込みなし（191件に AND 条件を重ねると配信先がほぼゼロになるため）
}

# ── メイン処理 ────────────────────────────────────────────
if DRY_RUN:
    print("=== DRY RUN モード（実際の変更なし）===")

print("\n[1/3] キャンペーン作成...")
if not DRY_RUN:
    camp = meta_post(
        f'{AD_ACCOUNT}/campaigns',
        name='BNI×NiceMeet_2026',
        objective='OUTCOME_TRAFFIC',
        status='PAUSED',
        special_ad_categories=json.dumps([]),
    )
    camp_id = camp['id']
    print(f"  キャンペーン作成OK: {camp_id}")
else:
    camp_id = 'DRY_CAMP_ID'
    print(f"  [DRY] キャンペーン: BNI×NiceMeet_2026 (PAUSED)")

print("\n[2/3] アドセット作成...")
if not DRY_RUN:
    adset = meta_post(
        f'{AD_ACCOUNT}/adsets',
        name='BNI_カスタムオーディエンス_191件',
        campaign_id=camp_id,
        daily_budget=500,
        billing_event='IMPRESSIONS',
        optimization_goal='LINK_CLICKS',
        destination_type='WEBSITE',
        targeting=json.dumps(TARGETING, ensure_ascii=False),
        status='PAUSED',
    )
    adset_id = adset['id']
    print(f"  アドセット作成OK: {adset_id}")
    print(f"  ターゲット: カスタムオーディエンス({CUSTOM_AUDIENCE_ID}) / 日本")
    print(f"  予算: ¥500/日")
else:
    adset_id = 'DRY_ADSET_ID'
    print(f"  [DRY] アドセット: BNI_カスタムオーディエンス_191件")
    print(f"  [DRY] ターゲット: カスタムオーディエンスID={CUSTOM_AUDIENCE_ID} / 日本")
    print(f"  [DRY] 予算: ¥500/日")

print("\n[3/3] 広告 × 5本 作成...")
created_ads = []

for i, banner in enumerate(BANNERS, 1):
    filepath = os.path.join(BANNER_DIR, banner['file'])
    if not os.path.exists(filepath):
        print(f"  [{i}] ファイル見つからず: {filepath}")
        continue

    if DRY_RUN:
        print(f"  [DRY] {banner['tag']}:")
        print(f"        見出し   : {banner['headline']}")
        print(f"        本文     : {banner['message'][:40]}...")
        print(f"        説明文   : {banner['description']}")
        print(f"        LP       : {LP_URL}")
        print(f"        バナー   : {filepath} ✅")
        continue

    # 画像アップロード
    with open(filepath, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    img_res = meta_post(f'{AD_ACCOUNT}/adimages', bytes=b64)
    img_hash = next(iter(img_res.get('images', {}).values()))['hash']

    # クリエイティブ作成
    story = {
        'page_id': PAGE_ID,
        'link_data': {
            'image_hash': img_hash,
            'link': LP_URL,
            'message': banner['message'],
            'name': banner['headline'],
            'description': banner['description'],
            'call_to_action': {'type': 'LEARN_MORE', 'value': {'link': LP_URL}},
        },
    }
    if IG_USER_ID:
        story['instagram_user_id'] = IG_USER_ID

    cr = meta_post(
        f'{AD_ACCOUNT}/adcreatives',
        name=banner['tag'],
        object_story_spec=json.dumps(story, ensure_ascii=False),
    )

    # 広告作成（PAUSED）
    ad = meta_post(
        f'{AD_ACCOUNT}/ads',
        name=banner['tag'],
        adset_id=adset_id,
        creative=json.dumps({'creative_id': cr['id']}),
        status='PAUSED',
    )
    print(f"  [{i}] {banner['tag']}: ad_id={ad['id']} ✅")
    created_ads.append(ad['id'])

print("\n" + "="*50)
if DRY_RUN:
    print("DRY RUN 完了。内容を確認後、--dry-run を外して本番実行してください。")
else:
    print(f"完了！ キャンペーン: {camp_id}")
    print(f"アドセット: {adset_id}")
    print(f"広告 {len(created_ads)}本 作成（全て PAUSED）")
    print()
    print("次のステップ:")
    print("  1. Meta広告マネージャーで各広告のプレビューを確認")
    print("  2. 問題なければキャンペーンを ACTIVE に変更")
    print(f"  https://www.facebook.com/adsmanager/manage/campaigns")
