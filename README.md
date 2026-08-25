# 祭り・フェス情報コレクター（スターター一式）

全国の祭り・フェス情報を **毎日自動で収集 → データベースに保存 → 絞り込み検索** する、
サーバー不要・無料枠で完結する構成のスターターです。

```
収集   GitHub Actions（cron・毎日1回）→ scraper.py
保存   Supabase（PostgreSQL・無料枠）
表示   web/index.html（都道府県・種類・期間・キーワードで絞り込み検索）
```

## ファイル構成

| ファイル | 役割 |
|---|---|
| `schema.sql` | Supabase のテーブル定義・インデックス・公開設定（RLS） |
| `scraper.py` | 情報を集めて Supabase へ upsert（重複は id で上書き） |
| `requirements.txt` | Python の依存ライブラリ |
| `.github/workflows/scrape.yml` | 毎日 cron で scraper.py を実行 |
| `web/index.html` | 絞り込み検索の画面（1ファイル完結） |

---

## セットアップ手順

### 1. Supabase を用意する
1. [supabase.com](https://supabase.com) でプロジェクトを作成（無料）。
2. 左メニュー **SQL Editor** を開き、`schema.sql` の中身を貼り付けて **Run**。
3. **Project Settings → API** で次の3つを控える。
   - `Project URL`
   - `anon public` キー（公開してよいキー）
   - `service_role` キー（**絶対に公開しない** 書き込み用）

### 2. GitHub リポジトリを作る
1. このフォルダ一式を GitHub にプッシュ。
2. **Settings → Secrets and variables → Actions** で2つ登録。
   - `SUPABASE_URL` … Project URL
   - `SUPABASE_SERVICE_KEY` … service_role キー
3. **Actions** タブで `collect-events` を有効化。
   まずは **Run workflow**（手動実行）で動作確認 → シードの7件が入ります。
   以降は毎日 07:00（JST）に自動実行されます。

### 3. 収集対象を増やす（自動収集の本体）
`scraper.py` の `SOURCES` に、各サイト用のパーサー関数を追加します。
- **公式API・RSS・自治体オープンデータがあれば最優先**（無料で安全）。
- スクレイピングする場合は各サイトの **利用規約と robots.txt を必ず確認**。
  `robots_allows()` ヘルパーで取得可否をチェックできます。
- 1サイト＝1関数。`example_site_parser()` がテンプレートです。
  `title / start_date（YYYY-MM-DD）/ prefecture / category` は絞り込みに使うので必ず埋めます。

### 4. 検索画面を公開する
1. `web/index.html` を開き、先頭の設定を書き換える。
   ```js
   const SUPABASE_URL = 'https://xxxx.supabase.co';
   const SUPABASE_ANON_KEY = 'ここに anon キー';
   ```
   ※ ここに入れるのは **anon キー**。service_role は絶対に貼らないこと。
2. **Cloudflare Pages** か **GitHub Pages** に `web/` を公開（どちらも無料）。
   - GitHub Pages: リポジトリ Settings → Pages → 公開ブランチ/フォルダを指定。
   - Cloudflare Pages: リポジトリを連携し、出力フォルダに `web` を指定。

未設定のままでもデモデータで画面を確認できます。

---

## セキュリティの考え方
- **書き込み**（scraper.py）は GitHub Secrets に入れた **service_role** キーで実行。
  service_role は RLS をバイパスするので保存できます。
- **公開サイト**（index.html）は **anon** キー＋ RLS の「読み取りのみ」ポリシーで、
  閲覧者は読むことしかできません（改ざん・削除は不可）。

## 費用の目安（すべて無料枠内）
- GitHub Actions … 毎日1回の軽い実行。無料枠で十分。
- Supabase … 無料枠 DB 500MB。※1週間アクセスが無いと一時停止するが、毎日 cron が書き込むため回避される。
- Cloudflare Pages / GitHub Pages … 静的ホスティングは無料。

規模が大きくなったり商用化する場合のみ、有料プランを検討してください。

## 注意
- スクレイピングは対象サイトの利用規約・robots.txt を尊重してください。
- 掲載イベントの日付・内容は変更されることがあります。詳細は各公式情報で確認を。
