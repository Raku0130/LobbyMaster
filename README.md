# LobbyMaster

Discord用のMVP投票・MAP投票Botです。

## 機能

### MVP投票
- `/mvp_start` - MVP投票を開始（運営のみ）
- `/mvp_end` - MVP投票を締め切り（運営のみ）
- 最大2名まで投票可能
- 結果は運営チャンネルに詳細、投票チャンネルにMVP発表

### MAP投票
- `/map_vote_start` - MAP投票を開始（運営のみ）
- `/map_end` - MAP投票を締め切り（運営のみ）
- 10人投票で自動締切
- 同票の場合はランダムで決定

### マップ管理
- `/maps_add <name>` - マップを追加（運営のみ）
- `/maps_remove <name>` - マップを削除（運営のみ）
- `/maps_list` - マップ一覧を表示
- `/map_random` - ランダムでマップを1つ表示

### 設定
- `/result_channel_set <channel>` - MVP結果投稿先を設定（運営のみ）
- `/admin_role_add <role>` - 運営ロールを追加（運営のみ）
- `/admin_role_remove <role>` - 運営ロールを削除（運営のみ）
- `/admin_role_list` - 運営ロール一覧（運営のみ）

## セットアップ

### 1. Discord Developer Portalでの設定

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリケーションを作成
2. **Bot** セクションでBotを作成し、トークンをコピー
3. **Privileged Gateway Intents** で以下を有効化：
   - SERVER MEMBERS INTENT
4. **OAuth2 > URL Generator** で以下を選択：
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Use Slash Commands`, `Read Message History`
5. 生成されたURLでBotをサーバーに招待

### 2. 環境変数の設定

```bash
cp .env.example .env
# .env を編集して DISCORD_BOT_TOKEN を設定
```

## 起動方法

### Docker（推奨）

```bash
# ビルド＆起動
docker compose up -d --build

# ログ確認
docker compose logs -f

# 停止
docker compose down

# 再起動
docker compose restart
```

### ローカル（Poetry）

```bash
# 依存関係インストール
poetry install

# 起動
poetry run python lobby_master.py
```

## ファイル構成

```
LobbyMaster/
├── lobby_master.py    # メインコード
├── config.json        # 設定ファイル（自動生成）
├── .env               # 環境変数（トークン）
├── .env.example       # 環境変数テンプレート
├── pyproject.toml     # Poetry設定
├── requirements.txt   # pip用依存関係
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## 注意事項

- Botを再起動すると進行中の投票は失われます
- MVP投票はタイムアウトなし（手動締め切りのみ）
- MAP投票は10人投票または指定秒数で自動締切
- MVP候補は最大25人まで表示（Discord仕様）
