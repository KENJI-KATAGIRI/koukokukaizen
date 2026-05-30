#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
魂のナビ診断 — Meta(Facebook/Instagram)広告 差し替えツール

依存ゼロ（Python標準ライブラリのみ）。Meta Marketing API を直接叩く。

安全設計：
  - 新広告は必ず PAUSED（停止状態）で作成する。いきなり配信・課金されない。
  - 旧広告の停止は別コマンド(pause)。明示的に指定したものだけ止める。
  - list / show は読み取りのみ。

使い方:
  python3 meta_ad_swap.py list                 # 全キャンペーン→広告セット→広告を表示
  python3 meta_ad_swap.py adsets <campaign_id> # 指定キャンペーンの広告セット一覧
  python3 meta_ad_swap.py ads <adset_id>       # 指定広告セットの広告一覧＋クリエイティブ
  python3 meta_ad_swap.py clone-adset <src_adset_id>  # 既存広告セットを複製し32-45・広め(Adv+)に書換え(PAUSED)
  python3 meta_ad_swap.py create <adset_id>    # 新バナー5本を PAUSED で投入
  python3 meta_ad_swap.py publish <ad_id...>   # 指定広告を配信開始(ACTIVE)
  python3 meta_ad_swap.py pause <ad_id...>     # 指定広告を停止(PAUSED)

設定は同じフォルダの .env を読む（META_ACCESS_TOKEN / META_AD_ACCOUNT_ID / META_PAGE_ID / META_LINK_URL / META_API_VERSION）。
"""
import os
import sys
import json
import base64
import urllib.request
import urllib.parse
import urllib.error

# ── .env 読み込み（簡易） ────────────────────────────────
def load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env()

API_VERSION = os.environ.get("META_API_VERSION", "v25.0")
TOKEN       = os.environ.get("META_ACCESS_TOKEN", "")
AD_ACCOUNT  = os.environ.get("META_AD_ACCOUNT_ID", "")   # act_xxxxxxxxx
PAGE_ID     = os.environ.get("META_PAGE_ID", "")
IG_USER_ID  = os.environ.get("META_INSTAGRAM_USER_ID", "")
LINK_URL    = os.environ.get("META_LINK_URL", "https://tamashiinavi.com/navi")
BASE        = f"https://graph.facebook.com/{API_VERSION}"

HERE = os.path.dirname(os.path.abspath(__file__))
BANNER_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "docs", "ad_banners"))

# ── 5本のバナー定義（docs/meta_ad_banner_spec.md と一致） ──
BANNERS = [
    {
        "file": "banner1.png",
        "name_tag": "01_共感_やりたいこと",
        "message": ("転職サイトを開いて、何も応募せず閉じる。変えたいのか、逃げたいのか、自分でもわからない。\n"
                    "それ、能力の問題じゃありません。\"何を基準に選ぶか\"が、いつの間にか外側に寄っただけ。\n"
                    "8問・約1分の無料診断で、いまの自分の「選び方のクセ」を言葉にできます。営業連絡なし。"),
        "headline": "1分でわかる、いまの自分の「選び方」",
        "description": "無料・8問・スマホ完結",
    },
    {
        "file": "banner2.png",
        "name_tag": "02_数字_2人に1人",
        "message": ("頑張れていないわけじゃない。むしろ頑張り続けた結果、判断の基準が\"自分の外\"に寄りすぎただけ。\n"
                    "8問の無料診断で、いまの選び方の傾向を可視化。次の一歩の入口が見えます。約1分／営業連絡なし。"),
        "headline": "その違和感、性格ではなく「基準」の問題",
        "description": "厚労省データ × 無料診断",
    },
    {
        "file": "banner3.png",
        "name_tag": "03_自己投影_チェックリスト",
        "message": ("当てはまった数だけ、あなたの\"魂のナビ\"は動き始めています。\n"
                    "これは性格占いではなく、いまの「選び方の傾向」を整理する実用的な現在地確認。\n"
                    "8問・約1分で、いまの受信状態をチェックできます。"),
        "headline": "当てはまるほど、ナビは動き始めている",
        "description": "無料・約1分・スマホ完結",
    },
    {
        "file": "banner4.png",
        "name_tag": "04_リフレーム_逃げじゃない",
        "message": ("変えたいのに動けない。それは意志が弱いからではありません。\n"
                    "いま\"心のナビ\"が強いのか、\"魂のナビ\"が動き始めているのか——8問・約1分の無料診断で見えてきます。"),
        "headline": "動けないのは、弱さじゃない",
        "description": "無料の現在地診断（約1分）",
    },
    {
        "file": "banner5.png",
        "name_tag": "05_静かな問い_たぶん",
        "message": ("順調なはずなのに、ずっと消えない小さな引っかかり。その正体に、名前をつけにいきませんか。\n"
                    "8問・約1分の無料診断。性格占いではなく、いまの自分の状態を言葉にするための短い確認です。"),
        "headline": "その「たぶん」に、名前をつける",
        "description": "無料・8問・約1分",
    },
]

CTA = {"type": "SEE_DETAILS", "value": {"link": LINK_URL}}


# ── HTTP ヘルパ ──────────────────────────────────────────
def _req(method, path, params=None, data=None):
    if not TOKEN:
        die("META_ACCESS_TOKEN が未設定です（.env を確認）")
    url = f"{BASE}/{path}"
    params = dict(params or {})
    params["access_token"] = TOKEN
    if method == "GET":
        url = url + "?" + urllib.parse.urlencode(params)
        body = None
    else:
        merged = dict(params)
        if data:
            merged.update(data)
        body = urllib.parse.urlencode(merged).encode("utf-8")
    rq = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(rq) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        die(f"API エラー {e.code}:\n{detail}")


def get(path, **params):
    return _req("GET", path, params=params)

def post(path, **data):
    return _req("POST", path, data=data)

def die(msg):
    print("\n[ERROR] " + msg, file=sys.stderr)
    sys.exit(1)

def need_account():
    if not AD_ACCOUNT:
        die("META_AD_ACCOUNT_ID が未設定です（例 act_918899401183375）")


# ── コマンド: list ───────────────────────────────────────
def cmd_list():
    need_account()
    print(f"# 広告アカウント: {AD_ACCOUNT}\n")
    camps = get(f"{AD_ACCOUNT}/campaigns",
                fields="name,status,effective_status,objective", limit=100).get("data", [])
    if not camps:
        print("（キャンペーンなし）")
        return
    for c in camps:
        print(f"■ キャンペーン: {c['name']}  [{c.get('effective_status')}]  id={c['id']}")
        sets = get(f"{c['id']}/adsets",
                   fields="name,status,effective_status,daily_budget", limit=100).get("data", [])
        for s in sets:
            budget = s.get("daily_budget")
            budget = f"  日予算¥{int(budget)//100}" if budget else ""
            print(f"   └ 広告セット: {s['name']}  [{s.get('effective_status')}]{budget}  id={s['id']}")
            ads = get(f"{s['id']}/ads",
                      fields="name,status,effective_status", limit=100).get("data", [])
            for a in ads:
                print(f"        └ 広告: {a['name']}  [{a.get('effective_status')}]  id={a['id']}")
        print()


def cmd_adsets(campaign_id):
    sets = get(f"{campaign_id}/adsets",
               fields="name,status,effective_status,daily_budget,optimization_goal", limit=100).get("data", [])
    for s in sets:
        print(json.dumps(s, ensure_ascii=False, indent=2))


def cmd_ads(adset_id):
    ads = get(f"{adset_id}/ads",
              fields="name,status,effective_status,creative{id,name,thumbnail_url,object_story_spec}",
              limit=100).get("data", [])
    for a in ads:
        print(json.dumps(a, ensure_ascii=False, indent=2))


# ── コマンド: clone-adset（既存を複製しターゲット書換え） ─
# 新ターゲットの方針: 年齢32-45 / 全性別 / 興味関心は外す(広め) / Advantage+オーディエンスON。
# 地域(geo_locations)・配信面・計測設定は元の広告セットから引き継ぐ。
NEW_AGE_MIN = 32
NEW_AGE_MAX = 45
NEW_ADSET_NAME = "32-45_キャリア迷子_広め(Adv+)"

def cmd_clone_adset(src_adset_id):
    need_account()
    src = get(src_adset_id,
              fields=("name,campaign_id,optimization_goal,billing_event,bid_strategy,bid_amount,"
                      "daily_budget,lifetime_budget,promoted_object,attribution_spec,destination_type,"
                      "pacing_type,start_time,end_time,targeting"))
    print(f"# 複製元: {src.get('name')}  (campaign {src.get('campaign_id')})")

    # ターゲティングを「広め」に再構成：地域・配信面は引き継ぎ、興味関心(flexible_spec等)は除去
    src_t = src.get("targeting", {}) or {}
    # 配信面は固定せず Advantage+配置（自動）に任せる＝広め配信。地域・言語のみ引き継ぐ。
    keep_keys = ["geo_locations", "excluded_geo_locations", "locales"]
    new_t = {k: src_t[k] for k in keep_keys if k in src_t}
    new_t["age_min"] = NEW_AGE_MIN
    new_t["age_max"] = NEW_AGE_MAX
    # 性別は指定しない＝全性別。興味関心は外し(広め)、配置は自動。
    # Advantage+オーディエンスは下限年齢25超を固定できないためOFF（32-45を厳密に狙う）。
    new_t["targeting_automation"] = {"advantage_audience": 0}

    params = {
        "name": NEW_ADSET_NAME,
        "campaign_id": src.get("campaign_id"),
        "status": "PAUSED",
        "optimization_goal": src.get("optimization_goal"),
        "billing_event": src.get("billing_event"),
        "targeting": json.dumps(new_t, ensure_ascii=False),
    }
    # 任意項目は存在する場合のみ引き継ぐ
    for k in ["bid_strategy", "destination_type"]:
        if src.get(k):
            params[k] = src[k]
    if src.get("bid_amount"):
        params["bid_amount"] = src["bid_amount"]
    # 予算: 広告セット側にあれば引き継ぐ。無ければキャンペーン予算(CBO)とみなし省略。
    if src.get("daily_budget"):
        params["daily_budget"] = src["daily_budget"]
    elif src.get("lifetime_budget"):
        params["lifetime_budget"] = src["lifetime_budget"]
    if src.get("promoted_object"):
        params["promoted_object"] = json.dumps(src["promoted_object"], ensure_ascii=False)
    if src.get("attribution_spec"):
        params["attribution_spec"] = json.dumps(src["attribution_spec"], ensure_ascii=False)
    if src.get("end_time"):
        params["end_time"] = src["end_time"]

    print("# 新ターゲティング:")
    print(json.dumps(new_t, ensure_ascii=False, indent=2))
    res = post(f"{AD_ACCOUNT}/adsets", **params)
    new_id = res.get("id")
    print(f"\n✓ 新広告セット作成(PAUSED) id={new_id}")
    print("\n続いて5本のバナーを投入:")
    print(f"  python3 meta_ad_swap.py create {new_id}")
    return new_id


# ── 画像アップロード → image_hash ────────────────────────
def upload_image(filepath):
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    res = post(f"{AD_ACCOUNT}/adimages", bytes=b64)
    images = res.get("images", {})
    if not images:
        die(f"画像アップロード失敗: {filepath}\n{json.dumps(res, ensure_ascii=False)}")
    first = next(iter(images.values()))
    return first["hash"]


# ── コマンド: create（PAUSEDで投入） ─────────────────────
def cmd_create(adset_id):
    need_account()
    if not PAGE_ID:
        die("META_PAGE_ID が未設定です（例 1163236556869089）")
    print(f"# 投入先 広告セット: {adset_id}")
    print(f"# リンク先: {LINK_URL}\n")
    created = []
    for b in BANNERS:
        path = os.path.join(BANNER_DIR, b["file"])
        if not os.path.exists(path):
            die(f"画像が見つかりません: {path}")
        print(f"→ {b['file']} アップロード中...")
        image_hash = upload_image(path)

        story = {
            "page_id": PAGE_ID,
            "link_data": {
                "image_hash": image_hash,
                "link": LINK_URL,
                "message": b["message"],
                "name": b["headline"],
                "description": b["description"],
                "call_to_action": CTA,
            },
        }
        if IG_USER_ID:
            story["instagram_user_id"] = IG_USER_ID
        cr = post(f"{AD_ACCOUNT}/adcreatives",
                  name=f"魂ナビ_{b['name_tag']}",
                  object_story_spec=json.dumps(story, ensure_ascii=False))
        creative_id = cr["id"]

        ad = post(f"{AD_ACCOUNT}/ads",
                  name=f"魂ナビ_{b['name_tag']}",
                  adset_id=adset_id,
                  creative=json.dumps({"creative_id": creative_id}),
                  status="PAUSED")
        ad_id = ad["id"]
        created.append((b["name_tag"], ad_id))
        print(f"   ✓ 広告作成(PAUSED) id={ad_id}  creative={creative_id}")

    print("\n=== 作成完了（すべて PAUSED） ===")
    for tag, ad_id in created:
        print(f"  {ad_id}  {tag}")
    print("\n広告マネージャでプレビュー確認 → 良ければ:")
    print("  python3 meta_ad_swap.py publish " + " ".join(a for _, a in created))


def cmd_publish(ad_ids):
    for ad_id in ad_ids:
        post(ad_id, status="ACTIVE")
        print(f"✓ 配信開始 ACTIVE  id={ad_id}")

def cmd_pause(ad_ids):
    for ad_id in ad_ids:
        post(ad_id, status="PAUSED")
        print(f"✓ 停止 PAUSED  id={ad_id}")


# ── エントリ ─────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "list":
        cmd_list()
    elif cmd == "adsets" and args:
        cmd_adsets(args[0])
    elif cmd == "ads" and args:
        cmd_ads(args[0])
    elif cmd == "clone-adset" and args:
        cmd_clone_adset(args[0])
    elif cmd == "create" and args:
        cmd_create(args[0])
    elif cmd == "publish" and args:
        cmd_publish(args)
    elif cmd == "pause" and args:
        cmd_pause(args)
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
