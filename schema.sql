-- =====================================================================
--  祭り・フェス情報コレクター  /  Supabase スキーマ
--  Supabase ダッシュボード → SQL Editor に貼り付けて実行してください。
-- =====================================================================

-- 1) イベントテーブル ---------------------------------------------------
create table if not exists public.events (
  id          text primary key,           -- 例: '2026-owara-kazenobon'（重複防止の一意キー）
  title       text not null,              -- イベント名
  start_date  date,                        -- 開始日
  end_date    date,                        -- 終了日（単日なら start_date と同じ）
  prefecture  text,                        -- 都道府県（絞り込み用）
  city        text,                        -- 市町村
  region      text,                        -- 地方（北海道/東北/関東 …）
  category    text,                        -- 種類（祭り/盆踊り/グルメ/音楽フェス …）
  description text,                        -- 内容・見どころ
  source_url  text,                        -- 出典（公式URL）
  lat         double precision,            -- 緯度（地図表示用・任意）
  lng         double precision,            -- 経度（地図表示用・任意）
  updated_at  timestamptz default now()    -- 情報取得日時
);

-- 2) 絞り込みを速くするためのインデックス --------------------------------
create index if not exists idx_events_start_date on public.events (start_date);
create index if not exists idx_events_prefecture on public.events (prefecture);
create index if not exists idx_events_category   on public.events (category);

-- 3) 行レベルセキュリティ（RLS）----------------------------------------
--    公開サイトからは「読み取りのみ」を許可します。
--    書き込み（スクレイパーからの保存）は service_role キーで行い、
--    service_role は RLS をバイパスするため、下の read ポリシーだけで安全です。
alter table public.events enable row level security;

drop policy if exists "public read events" on public.events;
create policy "public read events"
  on public.events
  for select
  to anon, authenticated
  using (true);

-- （書き込みポリシーはあえて作りません＝anon キーでは insert/update できません）
