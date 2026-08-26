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
import csv
import io
import re
import json
import hashlib
import datetime as dt
from urllib.parse import urlparse
from urllib import robotparser

import requests

# ─────────────────────────────────────────────────────────────────────
#  1. 収集した情報の「型」
#     絞り込みたい軸（prefecture / category / start_date）は必ず埋めること。
# ─────────────────────────────────────────────────────────────────────
def make_event(id, title, start_date, end_date, prefecture, city, region,
               category, description, source_url, lat=None, lng=None,
               genre="その他"):
    return {
        "id": id,
        "title": title,
        "start_date": start_date,          # "YYYY-MM-DD"
        "end_date": end_date or start_date,
        "prefecture": prefecture,
        "city": city,
        "region": region,
        "genre": genre,                    # 大分類（祭り・伝統行事／花火／音楽・フェス …）
        "category": category,              # 小分類（花火大会／盆踊り／曳山祭り …）
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
               "https://www.city.toyama.lg.jp/", 36.5665, 137.1350, genre="祭り・伝統行事"),
    make_event("2026-gujo-odori-osame", "郡上おどり（おどり納め）",
               "2026-09-05", "2026-09-05", "岐阜県", "郡上市", "中部",
               "盆踊り",
               "日本三大盆踊りのひとつ。全31夜の締めくくり「おどり納め」。観客も輪に加わって"
               "「かわさき」など全10曲を踊る。ユネスコ無形文化遺産「風流踊」。",
               "https://www.gujohachiman.com/kanko/", 35.7486, 136.9640, genre="祭り・伝統行事"),
    make_event("2026-tokachi-marche", "とかちマルシェ",
               "2026-09-04", "2026-09-06", "北海道", "帯広市", "北海道",
               "グルメ",
               "十勝最大級の「食と音楽」の祭典。十勝産食材の料理・スイーツが130店以上並び、"
               "多くが500円以下。ステージ演奏も。入場無料（飲食は別途）。",
               "https://www.city.obihiro.hokkaido.jp/", 42.9180, 143.1960, genre="グルメ・物産"),
    make_event("2026-slow-live-ikegami", "Slow LIVE ’26 in 池上本門寺",
               "2026-09-04", "2026-09-06", "東京都", "大田区", "関東",
               "音楽フェス",
               "「大人のミニフェス」をテーマにした野外ライブ3日間。アコースティック編成中心。"
               "音楽と食をゆったり楽しむ都市型フェス。全席指定の有料公演。",
               "https://www.red-hot.ne.jp/slow/", 35.5810, 139.7030, genre="音楽・フェス"),
    make_event("2026-aguchi-hassaku", "開口神社 八朔祭",
               "2026-09-05", "2026-09-06", "大阪府", "堺市", "関西",
               "秋祭り",
               "堺の古社・開口神社の祭礼。豪華な装飾のふとん太鼓の担ぎ出しが見どころ。"
               "境内周辺には多くの露店が並ぶ。",
               "https://matcha-jp.com/jp/20105", 34.5730, 135.4720, genre="祭り・伝統行事"),
    make_event("2026-natsumatsuri-asakura", "夏まつりあさくら",
               "2026-09-05", "2026-09-05", "福岡県", "朝倉市", "九州",
               "花火大会",
               "あさくらの夏の風物詩。約1,000発の花火が上がり、フィナーレは市内唯一の"
               "一尺玉10連発。約100の露店が並ぶ。花火は20:00〜20:30頃。",
               "https://www.city.asakura.lg.jp/", 33.4160, 130.6650, genre="花火"),
    make_event("2026-kakunodate-yama", "角館祭りのやま行事",
               "2026-09-07", "2026-09-09", "秋田県", "仙北市", "東北",
               "曳山祭り",
               "約400年の歴史を持つ神明社・薬師堂の祭礼。国指定重要無形民俗文化財／"
               "ユネスコ無形文化遺産。曳山同士が激突する「やまぶっつけ」がクライマックス。",
               "https://www.city.semboku.akita.jp/", 39.5970, 140.5620, genre="祭り・伝統行事"),

    # --- 向こう10日間（2026/8/26〜9/6）に追加した全国の行事 ---
    make_event("2026-yoshida-himatsuri", "吉田の火祭り・すすき祭り",
               "2026-08-26", "2026-08-27", "山梨県", "富士吉田市", "甲信越",
               "火祭り",
               "北口本宮冨士浅間神社と諏訪神社の祭礼で、日本三奇祭のひとつ。26日の夜、"
               "上吉田の本町通り約2kmに高さ3mの大松明100本以上が一斉に点火され、"
               "町全体が炎に包まれる。27日は神輿に続いてすすきの玉串を持ち高天原を廻る。",
               "https://www.city.fujiyoshida.yamanashi.jp/", 35.4869, 138.7899, genre="祭り・伝統行事"),
    make_event("2026-sweet-love-shower", "SWEET LOVE SHOWER 2026",
               "2026-08-28", "2026-08-30", "山梨県", "山中湖村", "甲信越",
               "音楽フェス",
               "スペースシャワー主催、夏の終わりの定番として親しまれる山中湖畔の野外音楽フェス。"
               "山中湖交流プラザ きらら特設会場で3日間開催。96組前後のアーティストが出演する有料公演。",
               "https://2026.sweetloveshower.com/", 35.4166, 138.8797, genre="音楽・フェス"),
    make_event("2026-omagari-hanabi", "全国花火競技大会「大曲の花火」",
               "2026-08-29", "2026-08-29", "秋田県", "大仙市", "東北",
               "花火大会",
               "日本三大花火大会のひとつで、内閣総理大臣賞を目指し全国の花火師が技を競う競技大会。"
               "全国的にも希少な昼花火（17:10〜）と、創造花火を含む夜花火（19:00〜21:30）が見どころ。"
               "雄物川河畔の「大曲の花火」公園で開催、例年60万人以上が訪れる。",
               "https://www.omagari-hanabi.com/", 39.4529, 140.4757, genre="花火"),
    make_event("2026-koenji-awaodori", "東京高円寺阿波おどり",
               "2026-08-29", "2026-08-30", "東京都", "杉並区", "関東",
               "阿波おどり",
               "1957年に始まった関東最大級の阿波おどり。高円寺駅周辺の商店街と高南通りの8演舞場で、"
               "地元連に加え徳島の有名連も参加し、約1万人の踊り手と約100万人の観客でにぎわう。"
               "両日17:00〜20:00頃。",
               "https://koenji-awaodori.com/", 35.7057, 139.6497, genre="祭り・伝統行事"),
    make_event("2026-asakusa-samba", "浅草サンバカーニバル",
               "2026-08-29", "2026-08-29", "東京都", "台東区", "関東",
               "パレード",
               "下町・浅草を舞台にした国内最大級のサンバの祭典。企業や本場ブラジルのダンサーも参加する"
               "リーグ制のパレードコンテストで、13:00〜18:00頃まで華やかな衣装と演奏が繰り広げられる。",
               "https://www.asakusa-samba.org/", 35.7119, 139.7967, genre="祭り・伝統行事"),
    make_event("2026-zento-eisa", "沖縄全島エイサーまつり",
               "2026-09-04", "2026-09-06", "沖縄県", "沖縄市", "沖縄",
               "エイサー",
               "沖縄本島各地から選抜されたエイサー団体が集う、旧盆明けの週末恒例の一大行事。"
               "初日(4日)は胡屋十字路周辺を練り歩く「道じゅねー」、5〜6日はコザ運動公園陸上競技場で"
               "本祭。太鼓を打ち鳴らす勇壮で華やかな演舞が魅力。",
               "https://www.zentoeisa.com/", 26.3341, 127.8057, genre="祭り・伝統行事"),
    make_event("2026-otou-natsumatsuri", "道の駅おおとう桜街道 夏祭り（大任町盆踊り花火大会）",
               "2026-08-29", "2026-08-29", "福岡県", "大任町", "九州",
               "盆踊り・花火",
               "筑豊・大任町の夏の風物詩。盆踊りやステージ、露店でにぎわい、フィナーレは"
               "20:00〜20:30頃に打ち上げ花火が夜空を彩る。第50回を数える地域密着の夏祭り。",
               "https://www.town.oto.lg.jp/", 33.6486, 130.8558, genre="花火"),

    # --- 都道府県ガイドから検証して追加（第1バッチ：秋以降の大型行事） ---
    make_event("2026-takayama-aki", "秋の高山祭（八幡祭）",
               "2026-10-09", "2026-10-10", "岐阜県", "高山市", "中部",
               "曳山祭り",
               "櫻山八幡宮の例大祭。ユネスコ無形文化遺産「高山祭の屋台行事」で、日本三大美祭のひとつ。"
               "飛騨の匠による豪華絢爛な屋台の曳き廻し、からくり奉納、9日夜の宵祭が見どころ。",
               "https://www.kankou-gifu.jp/event/detail_1074.html", 36.1480, 137.2590,
               genre="祭り・伝統行事"),
    make_event("2026-kawagoe-matsuri", "川越まつり",
               "2026-10-17", "2026-10-18", "埼玉県", "川越市", "関東",
               "山車行事",
               "小江戸・川越の総鎮守 氷川神社の例大祭と神幸祭、絢爛豪華な山車行事からなる川越最大の祭り。"
               "山車同士が向き合う「曳っかわせ」が最大の見どころ。ユネスコ無形文化遺産。",
               "https://kawagoematsuri.jp/", 35.9251, 139.4870, genre="祭り・伝統行事"),
    make_event("2026-chichibu-yomatsuri", "秩父夜祭",
               "2026-12-02", "2026-12-03", "埼玉県", "秩父市", "関東",
               "曳山祭り",
               "秩父神社の例祭で、京都祇園祭・飛騨高山祭と並ぶ日本三大曳山祭のひとつ。ユネスコ無形文化遺産。"
               "12/2が宵宮、12/3が大祭で、夜には提灯を灯した笠鉾・屋台の曳き回しと約4,000発の冬花火が競演する。",
               "https://www.chichibu-matsuri.jp/", 35.9990, 139.0860, genre="祭り・伝統行事"),

    # --- 第2バッチ（千葉・岐阜・埼玉の重点検証） ---
    make_event("2026-ohara-hadaka", "大原はだか祭り",
               "2026-09-23", "2026-09-24", "千葉県", "いすみ市", "関東",
               "神輿祭り",
               "例年9月23・24日に行われる関東随一の裸祭り。大原地区など18社の神輿が集結し、"
               "大原海水浴場で神輿を海に担ぎ込む「汐ふみ」、夕闇の「大別れ式」が最大の見どころ。",
               "https://www.city.isumi.lg.jp/", 35.2503, 140.3880, genre="祭り・伝統行事"),
    make_event("2026-gifu-nobunaga", "ぎふ信長まつり（岐阜市産業・農業祭）",
               "2026-11-07", "2026-11-08", "岐阜県", "岐阜市", "中部",
               "武者行列",
               "岐阜のまちづくりに貢献した織田信長公を称える、岐阜の秋を代表するまつり。"
               "8日の「信長公騎馬武者行列」が目玉で、中心市街地一帯でダンスステージや農業まつりも開催。",
               "https://gifunomatsuri.jp/nobunaga/", 35.4090, 136.7560, genre="祭り・伝統行事"),
    make_event("2026-seki-hamono", "関の刃物まつり",
               "2026-10-10", "2026-10-11", "岐阜県", "関市", "中部",
               "産業・物産まつり",
               "700年余の伝統を持つ刃物のまち・関市の一大イベント。本町通りの「刃物大廉売市」に約40社が出店し、"
               "火花散る古式日本刀鍛錬の実演、居合斬り、アウトドアナイフショーなどが催される。"
               "毎年スポーツの日の前の土日開催（2026年は10/10・11）。",
               "https://seki-hamono.jp/", 35.4960, 136.9170, genre="グルメ・物産"),
]

# 熱海海上花火大会（2026年 秋〜冬の各回・熱海市公式より）— 各日を1件ずつ登録
_ATAMI_HANABI_DATES = ["2026-09-13","2026-10-12","2026-10-25","2026-11-08","2026-11-23","2026-12-06","2026-12-25"]
for _d in _ATAMI_HANABI_DATES:
    SEED_EVENTS.append(make_event(
        f"2026-atami-hanabi-{_d}", "熱海海上花火大会",
        _d, _d, "静岡県", "熱海市", "中部",
        "花火大会",
        "1952年から続く熱海の名物。三方を山に囲まれた熱海湾の「すり鉢」地形が花火の音を反響させ、"
        "フィナーレの「大空中ナイアガラ」が湾を埋め尽くす。20:20〜20:40頃。",
        "https://www.city.atami.lg.jp/event/1009037/1014753.html", 35.0960, 139.0770,
        genre="花火"))


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


# ─────────────────────────────────────────────────────────────────────
#  3-b. 全国 市区町村単位の自動収集（王道）
#       デジタル庁「自治体標準オープンデータセット」の “イベント一覧” CSV を読む。
#       多くの市区町村が共通フォーマット（データ項目定義書A）で公開しているため、
#       1つのパーサーで全国の市区町村CSVを処理できる。CC BY 等のライセンスで利用可。
#
#       使い方：各自治体オープンデータのCSV直リンクを CSV_SOURCES に足すだけ。
#       CSVのURLは各都道府県/市区町村のオープンデータカタログや
#       BODIKオープンデータモニター等から取得できる。
# ─────────────────────────────────────────────────────────────────────

# 標準フォーマットの想定列名 → こちらの項目 への対応（表記ゆれも許容）
_ODS_COLMAP = {
    "title":      ["イベント名", "名称", "行事名"],
    "start_date": ["開始日", "開催日", "開始年月日", "日付"],
    "end_date":   ["終了日", "終了年月日"],
    "prefecture": ["都道府県名", "都道府県"],
    "city":       ["市区町村名", "市町村名", "市区町村"],
    "place":      ["開催場所", "場所", "会場"],
    "address":    ["住所", "所在地"],
    "lat":        ["緯度"],
    "lng":        ["経度"],
    "description":["説明", "概要", "内容", "備考"],
    "url":        ["関連URL", "URL", "詳細URL", "ホームページ"],
}


def _pick(row, keys):
    """行(dict)から、候補キーのうち最初に見つかった非空の値を返す。"""
    for k in keys:
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
    return ""


def _norm_date(s):
    """'2026-09-05' '2026/9/5' '2026年9月5日' などを 'YYYY-MM-DD' に正規化。"""
    if not s:
        return None
    s = s.strip()
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", s)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def _rows_from_resource(url):
    """CSV / XLSX のリソースURLを読み込み、[{列名: 値}, ...] の行リストにして返す。"""
    headers = {"User-Agent": "matsuri-collector/1.0 (+contact@example.com)"}
    raw = requests.get(url, headers=headers, timeout=30).content
    low = url.lower()

    # XLSX（新しいExcel形式）
    if low.endswith(".xlsx"):
        try:
            import openpyxl
        except ImportError:
            print(f"[skip] openpyxl 未導入のため XLSX を読めません: {url}")
            return []
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        header = [str(c).strip() if c is not None else "" for c in rows[0]]
        out = []
        for r in rows[1:]:
            out.append({header[i]: r[i] for i in range(min(len(header), len(r)))})
        return out

    # XLS（旧Excel形式）
    if low.endswith(".xls"):
        try:
            import xlrd
        except ImportError:
            print(f"[skip] xlrd 未導入のため XLS を読めません: {url}")
            return []
        try:
            book = xlrd.open_workbook(file_contents=raw)
            sh = book.sheet_by_index(0)
        except Exception as e:
            print(f"[skip] XLS を開けません（{e}）: {url}")
            return []
        if sh.nrows == 0:
            return []
        header = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
        out = []
        for r in range(1, sh.nrows):
            out.append({header[c]: sh.cell_value(r, c) for c in range(sh.ncols)})
        return out

    # CSV（自治体は Shift_JIS が多いので UTF-8 と両対応）
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        print(f"[error] 文字コード判定に失敗: {url}")
        return []
    return list(csv.DictReader(io.StringIO(text)))


def parse_standard_ods_events(url, prefecture=None, city=None,
                              default_region="", default_category="イベント"):
    """自治体標準オープンデータセット『イベント一覧』(CSV/XLSX)を events に変換。"""
    if not robots_allows(url):
        print(f"[skip] robots.txt により取得不可: {url}")
        return []

    events = []
    for row in _rows_from_resource(url):
        row = { (str(k) if k is not None else "").strip(): v for k, v in row.items() }
        start = _norm_date(_pick(row, _ODS_COLMAP["start_date"]))
        if not start:
            continue  # 日付が取れない行は捨てる
        end = _norm_date(_pick(row, _ODS_COLMAP["end_date"])) or start
        title = _pick(row, _ODS_COLMAP["title"])
        if not title:
            continue
        pref = prefecture or _pick(row, _ODS_COLMAP["prefecture"])
        cty  = city or _pick(row, _ODS_COLMAP["city"])
        place = _pick(row, _ODS_COLMAP["place"]) or _pick(row, _ODS_COLMAP["address"])
        desc = _pick(row, _ODS_COLMAP["description"])
        if place and place not in desc:
            desc = (place + "／" + desc).strip("／")
        src = _pick(row, _ODS_COLMAP["url"]) or url

        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        lat = _f(_pick(row, _ODS_COLMAP["lat"]))
        lng = _f(_pick(row, _ODS_COLMAP["lng"]))

        h = hashlib.md5(f"{pref}{cty}{title}{start}".encode("utf-8")).hexdigest()[:10]
        events.append(make_event(
            id=f"ods-{h}", title=title, start_date=start, end_date=end,
            prefecture=pref, city=cty, region=default_region,
            category=default_category, description=desc, source_url=src,
            lat=lat, lng=lng, genre="その他",
        ))
    return events


# 都道府県コード（全国地方公共団体コードの上2桁）→ 都道府県名
_PREF_CODES = {
    "01":"北海道","02":"青森県","03":"岩手県","04":"宮城県","05":"秋田県","06":"山形県",
    "07":"福島県","08":"茨城県","09":"栃木県","10":"群馬県","11":"埼玉県","12":"千葉県",
    "13":"東京都","14":"神奈川県","15":"新潟県","16":"富山県","17":"石川県","18":"福井県",
    "19":"山梨県","20":"長野県","21":"岐阜県","22":"静岡県","23":"愛知県","24":"三重県",
    "25":"滋賀県","26":"京都府","27":"大阪府","28":"兵庫県","29":"奈良県","30":"和歌山県",
    "31":"鳥取県","32":"島根県","33":"岡山県","34":"広島県","35":"山口県","36":"徳島県",
    "37":"香川県","38":"愛媛県","39":"高知県","40":"福岡県","41":"佐賀県","42":"長崎県",
    "43":"熊本県","44":"大分県","45":"宮崎県","46":"鹿児島県","47":"沖縄県",
}


def discover_bodik_event_datasets(pref_prefixes, max_pages=6):
    """
    BODIK の CKAN API で『イベント一覧』データセットを検索し、
    指定した都道府県コード（上2桁）に属する市区町村のCSV/XLSXリンクを集める。
    戻り値: [(resource_url, 都道府県名, 市区町村名), ...]
    """
    api = "https://data.bodik.jp/api/3/action/package_search"
    headers = {"User-Agent": "matsuri-collector/1.0 (+contact@example.com)"}
    found = []
    for page in range(max_pages):
        params = {"q": "イベント一覧", "rows": 100, "start": page * 100}
        try:
            r = requests.get(api, params=params, headers=headers, timeout=30)
            data = r.json()
        except Exception as e:
            print(f"[error] BODIK検索: {e}")
            break
        results = data.get("result", {}).get("results", [])
        if not results:
            break
        for ds in results:
            org = ds.get("organization") or {}
            code = str(org.get("name", ""))          # 例: "402028"（大牟田市）
            if code[:2] not in pref_prefixes:
                continue
            # タイトルに「イベント」を含むデータセットのみ（誤検出を減らす）
            if "イベント" not in (ds.get("title", "") + ds.get("name", "")):
                continue
            pref = _PREF_CODES.get(code[:2])
            city = org.get("title")                  # 例: "大牟田市"
            for res in ds.get("resources", []):
                fmt = str(res.get("format", "")).upper()
                if fmt in ("CSV", "XLSX", "XLS"):
                    found.append((res.get("url"), pref, city))
    return found


# 収集対象の市区町村CSVを直接指定したい場合はここに追加（自動発見と併用可）。
#   例）("https://＜自治体＞/event.csv", "福岡県", "○○市")
CSV_SOURCES = [
]

# BODIK 自動発見の対象都道府県コード（上2桁）を、実行した曜日で切り替える。
#   月:九州沖縄 / 火:中国四国 / 水:近畿 / 木:中部北陸 / 金:関東 / 土:東北 / 日:北海道
# こうすると1日あたりの巡回量が減り、1週間で全国を一巡する。
_WEEKDAY_REGIONS = {
    0: ["40","41","42","43","44","45","46","47"],            # 月 九州・沖縄
    1: ["31","32","33","34","35","36","37","38","39"],       # 火 中国・四国
    2: ["25","26","27","28","29","30"],                      # 水 近畿
    3: ["15","16","17","18","19","20","21","22","23","24"],  # 木 中部・北陸
    4: ["08","09","10","11","12","13","14"],                 # 金 関東
    5: ["02","03","04","05","06","07"],                      # 土 東北
    6: ["01"],                                               # 日 北海道
}

# その日に巡回する都道府県コード（実行日の曜日で決まる）
BODIK_PREF_PREFIXES = _WEEKDAY_REGIONS[dt.date.today().weekday()]

# オープンデータから取り込む対象の日付範囲（今日〜N日先）。過去や遠い先は捨てる。
ODS_WINDOW_DAYS = 45


def collect_from_open_data():
    """自動発見(BODIK) ＋ 手動指定(CSV_SOURCES) のイベントを取り込み、期間で絞る。"""
    today = dt.date.today()
    horizon = today + dt.timedelta(days=ODS_WINDOW_DAYS)

    sources = list(CSV_SOURCES)
    if BODIK_PREF_PREFIXES:
        discovered = discover_bodik_event_datasets(BODIK_PREF_PREFIXES)
        print(f"[bodik] イベント一覧データセットを {len(discovered)} 件発見")
        sources.extend(discovered)

    out = []
    for entry in sources:
        url = entry[0]
        pref = entry[1] if len(entry) > 1 else None
        city = entry[2] if len(entry) > 2 else None
        if not url:
            continue
        try:
            got = parse_standard_ods_events(url, pref, city)
            kept = []
            for e in got:
                try:
                    s = dt.date.fromisoformat(e["start_date"])
                    en = dt.date.fromisoformat(e["end_date"])
                except ValueError:
                    continue
                if en >= today and s <= horizon:
                    kept.append(e)
            if got:
                print(f"[ods] {city or ''} {url.split('/')[-1]}: 取得{len(got)} → 期間内{len(kept)}")
            out.extend(kept)
        except Exception as e:
            print(f"[error] ODS {url}: {e}")
    return out


def collect():
    """シード ＋ 各サイトのパーサー ＋ オープンデータCSV の結果をまとめて返す。"""
    events = list(SEED_EVENTS)
    for source in SOURCES:
        try:
            got = source()
            print(f"[ok] {source.__name__}: {len(got)}件")
            events.extend(got)
        except Exception as e:
            print(f"[error] {source.__name__}: {e}")
    events.extend(collect_from_open_data())
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
