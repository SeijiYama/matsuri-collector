#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
祭り・フェス情報コレクター
--------------------------------------------------------------------
1) collect() でイベント情報を集める（下の SEED_EVENTS ＋ 追加した各サイトのパーサー）
2) Supabase の events テーブルへ upsert（id で重複を上書き）

GitHub Actions の cron から毎日呼ばれる想定。
必要な環境変数（GitHub の Secrets に登録）:
    SUPABASE_URL          例: https://xxxx.supabase.co
    SUPABASE_SERVICE_KEY  service_role キー（絶対に公開しない）
"""

import os
import sys
import json
import datetime as dt
from urllib.parse import urlparse
from urllib import robotparser

import requests

# ─────────────────────────────────────────────────────────────────────
#  1. 収集した情報の「型」
#     絞り込みたい軸（prefecture / category / start_date）は必ず埋めること。
# ─────────────────────────────────────────────────────────────────────
def make_event(id, title, start_date, end_date, prefecture, city, region,
               category, description, source_url, lat=None, lng=None):
    return {
        "id": id,
        "title": title,
        "start_date": start_date,          # "YYYY-MM-DD"
        "end_date": end_date or start_date,
        "prefecture": prefecture,
        "city": city,
        "region": region,
        "category": category,
        "description": description,
        "source_url": source_url,
        "lat": lat,
        "lng": lng,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────
#  2. シードデータ（動作確認用の初期データ）
#     まずはこれだけで DB → 検索UI まで通しで動きます。
#     実運用ではここを減らし、下のパーサーで自動収集に置き換えていく。
# ─────────────────────────────────────────────────────────────────────
SEED_EVENTS = [
    make_event("2026-owara-kazenobon", "越中八尾 おわら風の盆",
               "2026-09-01", "2026-09-03", "富山県", "富山市", "北陸",
               "民謡行事",
               "300年余の歴史を持つ叙情的な民謡行事。数千のぼんぼりが灯る八尾の坂の町を、"
               "編み笠に揃いの浴衣姿の踊り手が三味線・胡弓・太鼓に合わせて流し歩く。",
               "https://www.city.toyama.lg.jp/", 36.5665, 137.1350),
    make_event("2026-gujo-odori-osame", "郡上おどり（おどり納め）",
               "2026-09-05", "2026-09-05", "岐阜県", "郡上市", "中部",
               "盆踊り",
               "日本三大盆踊りのひとつ。全31夜の締めくくり「おどり納め」。観客も輪に加わって"
               "「かわさき」など全10曲を踊る。ユネスコ無形文化遺産「風流踊」。",
               "https://www.gujohachiman.com/kanko/", 35.7486, 136.9640),
    make_event("2026-tokachi-marche", "とかちマルシェ",
               "2026-09-04", "2026-09-06", "北海道", "帯広市", "北海道",
               "グルメ",
               "十勝最大級の「食と音楽」の祭典。十勝産食材の料理・スイーツが130店以上並び、"
               "多くが500円以下。ステージ演奏も。入場無料（飲食は別途）。",
               "https://www.city.obihiro.hokkaido.jp/", 42.9180, 143.1960),
    make_event("2026-slow-live-ikegami", "Slow LIVE ’26 in 池上本門寺",
               "2026-09-04", "2026-09-06", "東京都", "大田区", "関東",
               "音楽フェス",
               "「大人のミニフェス」をテーマにした野外ライブ3日間。アコースティック編成中心。"
               "音楽と食をゆったり楽しむ都市型フェス。全席指定の有料公演。",
               "https://www.red-hot.ne.jp/slow/", 35.5810, 139.7030),
    make_event("2026-aguchi-hassaku", "開口神社 八朔祭",
               "2026-09-05", "2026-09-06", "大阪府", "堺市", "関西",
               "秋祭り",
               "堺の古社・開口神社の祭礼。豪華な装飾のふとん太鼓の担ぎ出しが見どころ。"
               "境内周辺には多くの露店が並ぶ。",
               "https://matcha-jp.com/jp/20105", 34.5730, 135.4720),
    make_event("2026-natsumatsuri-asakura", "夏まつりあさくら",
               "2026-09-05", "2026-09-05", "福岡県", "朝倉市", "九州",
               "花火大会",
               "あさくらの夏の風物詩。約1,000発の花火が上がり、フィナーレは市内唯一の"
               "一尺玉10連発。約100の露店が並ぶ。花火は20:00〜20:30頃。",
               "https://www.city.asakura.lg.jp/", 33.4160, 130.6650),
    make_event("2026-kakunodate-yama", "角館祭りのやま行事",
               "2026-09-07", "2026-09-09", "秋田県", "仙北市", "東北",
               "曳山祭り",
               "約400年の歴史を持つ神明社・薬師堂の祭礼。国指定重要無形民俗文化財／"
               "ユネスコ無形文化遺産。曳山同士が激突する「やまぶっつけ」がクライマックス。",
               "https://www.city.semboku.akita.jp/", 39.5970, 140.5620),
]


# ─────────────────────────────────────────────────────────────────────
#  3. スクレイパーを追加する場所
#     ・公式API / RSS / 自治体オープンデータがあればそちらを最優先（無料・安全）
#     ・スクレイピングする場合は robots.txt と利用規約を必ず尊重する
#     ・1サイト＝1関数。失敗しても全体が止まらないよう try/except で囲む
#
#  下は BeautifulSoup を使う「型」の例です。実際のサイトに合わせて
#  URL と CSS セレクタを書き換え、SOURCES に登録すると自動収集されます。
# ─────────────────────────────────────────────────────────────────────
def robots_allows(url: str, user_agent: str = "*") -> bool:
    """robots.txt が対象URLの取得を許可しているか確認する。"""
    try:
        parts = urlparse(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception:
        # robots.txt が無い/読めない場合は保守的に許可扱い。心配ならここを False に。
        return True


def example_site_parser():
    """
    実サイト用パーサーのテンプレート。
    使うときは from bs4 import BeautifulSoup を有効化し、
    セレクタを対象サイトに合わせて調整して SOURCES に登録する。
    """
    from bs4 import BeautifulSoup  # requirements.txt に beautifulsoup4

    url = "https://example.com/events"        # ← 対象ページ
    if not robots_allows(url):
        print(f"[skip] robots.txt により取得不可: {url}")
        return []

    headers = {"User-Agent": "matsuri-collector/1.0 (+contact@example.com)"}
    html = requests.get(url, headers=headers, timeout=20).text
    soup = BeautifulSoup(html, "html.parser")

    events = []
    for card in soup.select(".event-card"):       # ← 各イベントの要素
        title = card.select_one(".title").get_text(strip=True)
        date  = card.select_one(".date").get_text(strip=True)  # "2026-09-05" に整形する
        place = card.select_one(".place").get_text(strip=True)
        events.append(make_event(
            id=f"example-{title}",
            title=title, start_date=date, end_date=date,
            prefecture="（都道府県を抽出）", city=place, region="",
            category="祭り", description="", source_url=url,
        ))
    return events


# ここに実装済みパーサーを追加していく（例: SOURCES = [example_site_parser]）
SOURCES = []


def collect():
    """シード ＋ 各サイトのパーサーの結果をまとめて返す。"""
    events = list(SEED_EVENTS)
    for source in SOURCES:
        try:
            got = source()
            print(f"[ok] {source.__name__}: {len(got)}件")
            events.extend(got)
        except Exception as e:
            print(f"[error] {source.__name__}: {e}")
    # id で重複排除（後勝ち）
    dedup = {e["id"]: e for e in events}
    return list(dedup.values())


# ─────────────────────────────────────────────────────────────────────
#  4. Supabase へ upsert 保存
# ─────────────────────────────────────────────────────────────────────
def save_to_supabase(events):
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY が未設定です。保存をスキップします。")
        print(f"（収集できた件数: {len(events)}）")
        return False

    endpoint = f"{url}/rest/v1/events?on_conflict=id"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # merge-duplicates ＝ 同じ id があれば上書き（＝ upsert）
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    res = requests.post(endpoint, headers=headers, data=json.dumps(events), timeout=30)
    if res.status_code in (200, 201, 204):
        print(f"保存成功: {len(events)}件を upsert しました。")
        return True
    print(f"保存失敗: HTTP {res.status_code} {res.text}")
    return False


def main():
    events = collect()
    print(f"収集合計: {len(events)}件")
    ok = save_to_supabase(events)
    sys.exit(0 if ok or not os.environ.get("SUPABASE_URL") else 1)


if __name__ == "__main__":
    main()
