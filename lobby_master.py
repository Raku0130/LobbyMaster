import os
import json
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv
import discord
from discord import app_commands


CONFIG_PATH = "config.json"
MAP_AUTO_CLOSE_VOTERS = 10  # ★ 10人投票で自動締切


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {
            "admin_role_ids": [],        # 追加で運営権限を持つロールID
            "result_channel_id": None,   # MVP結果投稿先チャンネルID（運営限定推奨）
            "maps": []                   # マップ一覧
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def is_admin_like(inter: discord.Interaction, cfg: dict) -> bool:
    """デフォルト：管理者 / 追加：admin_role_ids のいずれかを持っていればOK"""
    if not inter.guild or not isinstance(inter.user, discord.Member):
        return False
    if inter.user.guild_permissions.administrator:
        return True
    allowed: Set[int] = set(cfg.get("admin_role_ids", []))
    return any(role.id in allowed for role in inter.user.roles)


def require_admin_like(cfg_getter):
    def predicate(inter: discord.Interaction) -> bool:
        cfg = cfg_getter()
        return is_admin_like(inter, cfg)
    return app_commands.check(predicate)


def eligible_members_in_channel(channel: discord.abc.GuildChannel, guild: discord.Guild) -> List[discord.Member]:
    """
    "このチャンネルのメンバー" を
    - bot除外
    - view_channel権限がある
    として guild.members から抽出
    """
    members: List[discord.Member] = []
    for m in guild.members:
        if m.bot:
            continue
        perms = channel.permissions_for(m)
        if perms.view_channel:
            members.append(m)
    return members


@dataclass
class VoteSession:
    guild_id: int
    channel_id: int
    message_id: int
    kind: str  # "mvp" or "map"
    votes: Dict[int, List[int]] = field(default_factory=dict)  # voter_id -> picks
    mvp_candidates: Set[int] = field(default_factory=set)      # MVP: candidate user ids
    mvp_candidates_info: Dict[int, str] = field(default_factory=dict)  # MVP: user_id -> display_name
    maps_snapshot: List[str] = field(default_factory=list)     # MAP: snapshot of map list
    ended: bool = False


class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True  # チャンネル候補者抽出に必要
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)
        self.cfg = load_config()
        self.active_sessions: Dict[Tuple[int, str], VoteSession] = {}  # key=(guild_id, kind)

    async def setup_hook(self):
        await self.tree.sync()

    async def end_session(self, session: VoteSession, requested_by_text: Optional[str]):
        # 二重実行ガード
        if session.ended:
            return
        session.ended = True  # ★ まずTrueにして race を抑える

        guild = self.get_guild(session.guild_id)
        if not guild:
            self.active_sessions.pop((session.guild_id, session.kind), None)
            return

        start_ch = guild.get_channel(session.channel_id)

        # 投票メッセージ更新（公開側に「結果は運営のみ」など）
        try:
            if isinstance(start_ch, discord.abc.Messageable):
                msg = await start_ch.fetch_message(session.message_id)
                if session.kind == "mvp":
                    await msg.edit(content="✅ MVP投票は締め切りました。", view=None)
                else:
                    await msg.edit(content="✅ MAP投票は締め切りました。", view=None)
        except Exception:
            pass

        # 結果投稿先チャンネル決定
        if session.kind == "mvp":
            # MVP結果は result_channel のみ
            result_channel_id = self.cfg.get("result_channel_id")
            if not result_channel_id:
                self.active_sessions.pop((session.guild_id, session.kind), None)
                return
            result_ch = guild.get_channel(int(result_channel_id))
        else:
            # MAP結果は開始チャンネルに表示
            result_ch = start_ch

        if not isinstance(result_ch, discord.abc.Messageable):
            self.active_sessions.pop((session.guild_id, session.kind), None)
            return

        # 結果作成 & 投稿
        if session.kind == "mvp":
            counts: Dict[int, int] = {}
            for _, picks in session.votes.items():
                for pid in picks:
                    counts[pid] = counts.get(pid, 0) + 1

            # 運営チャンネルへ詳細結果を投稿
            lines = ["**MVP投票 結果（運営のみ）**"]

            if not counts:
                lines.append("投票がありませんでした。")
            else:
                sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
                for uid, c in sorted_items:
                    member = guild.get_member(uid)
                    name = member.mention if member else f"<@{uid}>"
                    lines.append(f"- {name}: **{c}**")

            await result_ch.send("\n".join(lines))

            # 投票チャンネルへMVP発表を投稿
            if isinstance(start_ch, discord.abc.Messageable):
                if not counts:
                    await start_ch.send("🏆 **MVP投票結果**\n投票がありませんでした。")
                else:
                    max_votes = max(counts.values())
                    winners = [uid for uid, c in counts.items() if c == max_votes]
                    winner_mentions = []
                    for uid in winners:
                        member = guild.get_member(uid)
                        winner_mentions.append((member.mention if member else f"<@{uid}>") + "さん")
                    
                    if len(winners) == 1:
                        await start_ch.send(f"🏆 **MVP発表**\nMVPは {winner_mentions[0]} です！おめでとうございます！🎉")
                    else:
                        winners_text = "、".join(winner_mentions)
                        await start_ch.send(f"🏆 **MVP発表**\nMVPは {winners_text} です！（同票）おめでとうございます！🎉")

        elif session.kind == "map":
            counts: Dict[int, int] = {}
            for _, picks in session.votes.items():
                idx = picks[0]
                counts[idx] = counts.get(idx, 0) + 1

            lines = ["**MAP投票 結果**"]

            if not counts:
                lines.append("投票がありませんでした。")
            else:
                max_votes = max(counts.values())
                winners = [idx for idx, c in counts.items() if c == max_votes]

                # 全結果
                for idx, c in sorted(counts.items(), key=lambda x: x[1], reverse=True):
                    name = session.maps_snapshot[idx]
                    lines.append(f"- {name}: **{c}**")

                # 勝者
                if len(winners) == 1:
                    lines.append(f"\n✅ **決定:** {session.maps_snapshot[winners[0]]}")
                else:
                    # 同票の場合はランダムで1つ選ぶ
                    chosen_idx = random.choice(winners)
                    lines.append(f"\n✅ **決定(抽選):** {session.maps_snapshot[chosen_idx]}")

            await result_ch.send("\n".join(lines))

        self.active_sessions.pop((session.guild_id, session.kind), None)


bot = MyBot()


# -------------------------
# UI: MVP投票
# -------------------------

class MVPVoteView(discord.ui.View):
    def __init__(self, session: VoteSession):
        super().__init__(timeout=None)  # タイムアウトなし（手動締め切りのみ）
        self.session = session

    @discord.ui.button(label="投票する（最大2名）", style=discord.ButtonStyle.primary)
    async def vote_button(self, inter: discord.Interaction, button: discord.ui.Button):
        if self.session.ended:
            await inter.response.send_message("この投票はすでに締め切られています。", ephemeral=True)
            return
        view = MVPSelectView(self.session)
        await inter.response.send_message("MVP候補を最大2名選んでください。", view=view, ephemeral=True)


class MVPSelect(discord.ui.Select):
    def __init__(self, session: VoteSession):
        self.session = session
        # 候補者からオプションを生成（最大25人）
        options = [
            discord.SelectOption(label=name, value=str(uid))
            for uid, name in list(session.mvp_candidates_info.items())[:25]
        ]
        max_vals = min(2, len(options))  # 候補者が1人の場合は1、それ以外は2
        super().__init__(placeholder="最大2名選択", min_values=1, max_values=max_vals, options=options)

    async def callback(self, inter: discord.Interaction):
        if self.session.ended:
            await inter.response.send_message("この投票はすでに締め切られています。", ephemeral=True)
            return

        chosen_ids = [int(v) for v in self.values]
        self.session.votes[inter.user.id] = chosen_ids
        await inter.response.send_message("投票を受け付けました（上書き可）。", ephemeral=True)


class MVPSelectView(discord.ui.View):
    def __init__(self, session: VoteSession):
        super().__init__(timeout=60.0)
        self.add_item(MVPSelect(session))


# -------------------------
# UI: MAP投票（10人で自動締切）
# -------------------------

class MapVoteView(discord.ui.View):
    def __init__(self, session: VoteSession, timeout: Optional[float] = 120.0):
        super().__init__(timeout=timeout)
        self.session = session
        self.add_item(MapSelect(session))

    async def on_timeout(self):
        if not self.session.ended:
            await bot.end_session(self.session, requested_by_text="自動締切（タイムアウト）")


class MapSelect(discord.ui.Select):
    def __init__(self, session: VoteSession):
        self.session = session
        options = [discord.SelectOption(label=name, value=str(i)) for i, name in enumerate(session.maps_snapshot)]
        super().__init__(placeholder="1マップ選択（1票）", min_values=1, max_values=1, options=options)

    async def callback(self, inter: discord.Interaction):
        if self.session.ended:
            await inter.response.send_message("この投票はすでに締め切られています。", ephemeral=True)
            return

        idx = int(self.values[0])
        self.session.votes[inter.user.id] = [idx]

        # まず投票受付
        await inter.response.send_message("投票を受け付けました（上書き可）。", ephemeral=True)

        # ★ 10人投票で自動締切（ユニーク投票者数）
        if (not self.session.ended) and len(self.session.votes) >= MAP_AUTO_CLOSE_VOTERS:
            await bot.end_session(self.session, requested_by_text=f"自動締切（{MAP_AUTO_CLOSE_VOTERS}人投票到達）")


# -------------------------
# 設定系（運営のみ）
# -------------------------

@bot.tree.command(name="result_channel_set", description="MVP結果を投稿するチャンネルを設定（運営のみ）")
@require_admin_like(lambda: bot.cfg)
@app_commands.describe(channel="MVP結果投稿先（運営だけが見えるチャンネル推奨）")
async def result_channel_set(inter: discord.Interaction, channel: discord.TextChannel):
    bot.cfg["result_channel_id"] = channel.id
    save_config(bot.cfg)
    await inter.response.send_message(f"MVP結果チャンネルを {channel.mention} に設定しました。", ephemeral=True)


@bot.tree.command(name="admin_role_add", description="運営コマンド実行権限のロールを追加（運営のみ）")
@require_admin_like(lambda: bot.cfg)
@app_commands.describe(role="追加するロール")
async def admin_role_add(inter: discord.Interaction, role: discord.Role):
    ids = set(bot.cfg.get("admin_role_ids", []))
    ids.add(role.id)
    bot.cfg["admin_role_ids"] = sorted(list(ids))
    save_config(bot.cfg)
    await inter.response.send_message(f"運営ロールに {role.mention} を追加しました。", ephemeral=True)


@bot.tree.command(name="admin_role_remove", description="運営コマンド実行権限のロールを削除（運営のみ）")
@require_admin_like(lambda: bot.cfg)
@app_commands.describe(role="削除するロール")
async def admin_role_remove(inter: discord.Interaction, role: discord.Role):
    ids = set(bot.cfg.get("admin_role_ids", []))
    ids.discard(role.id)
    bot.cfg["admin_role_ids"] = sorted(list(ids))
    save_config(bot.cfg)
    await inter.response.send_message(f"運営ロールから {role.mention} を削除しました。", ephemeral=True)


@bot.tree.command(name="admin_role_list", description="運営コマンド実行権限のロール一覧（運営のみ）")
@require_admin_like(lambda: bot.cfg)
async def admin_role_list(inter: discord.Interaction):
    ids = bot.cfg.get("admin_role_ids", [])
    if not ids:
        await inter.response.send_message("追加の運営ロールは未設定です。", ephemeral=True)
        return
    roles = [inter.guild.get_role(rid) for rid in ids if inter.guild]
    text = "\n".join(f"- {r.mention}" for r in roles if r)
    await inter.response.send_message(f"運営ロール一覧:\n{text}", ephemeral=True)


# -------------------------
# マップ管理（運営のみ）
# -------------------------

@bot.tree.command(name="maps_add", description="マップを追加（運営のみ）")
@require_admin_like(lambda: bot.cfg)
@app_commands.describe(name="追加するマップ名")
async def maps_add(inter: discord.Interaction, name: str):
    maps = bot.cfg.get("maps", [])
    if name in maps:
        await inter.response.send_message("既に存在します。", ephemeral=True)
        return
    maps.append(name)
    bot.cfg["maps"] = maps
    save_config(bot.cfg)
    await inter.response.send_message(f"マップを追加しました: **{name}**", ephemeral=True)


@bot.tree.command(name="maps_remove", description="マップを削除（運営のみ）")
@require_admin_like(lambda: bot.cfg)
@app_commands.describe(name="削除するマップ名")
async def maps_remove(inter: discord.Interaction, name: str):
    maps = bot.cfg.get("maps", [])
    if name not in maps:
        await inter.response.send_message("そのマップは登録されていません。", ephemeral=True)
        return
    maps.remove(name)
    bot.cfg["maps"] = maps
    save_config(bot.cfg)
    await inter.response.send_message(f"マップを削除しました: **{name}**", ephemeral=True)


@bot.tree.command(name="maps_list", description="マップ一覧")
async def maps_list(inter: discord.Interaction):
    maps = bot.cfg.get("maps", [])
    if not maps:
        await inter.response.send_message("マップが未登録です。/maps_add で追加してください。", ephemeral=True)
        return
    await inter.response.send_message("登録マップ:\n" + "\n".join(f"- {m}" for m in maps), ephemeral=True)


@bot.tree.command(name="map_random", description="マップをランダムで1つ表示")
async def map_random(inter: discord.Interaction):
    maps = bot.cfg.get("maps", [])
    if not maps:
        await inter.response.send_message("マップが未登録です（運営が /maps_add で追加してください）。", ephemeral=True)
        return
    picked = random.choice(maps)
    await inter.response.send_message(f"🎲 **Random MAP:** {picked}")


# -------------------------
# 投票開始（運営のみ）
# -------------------------

@bot.tree.command(name="mvp_start", description="MVP投票を開始（最大2名投票）（運営のみ）")
@require_admin_like(lambda: bot.cfg)
async def mvp_start(inter: discord.Interaction):
    if not inter.guild or not inter.channel:
        await inter.response.send_message("サーバー内のチャンネルで実行してください。", ephemeral=True)
        return

    key = (inter.guild.id, "mvp")
    if key in bot.active_sessions and not bot.active_sessions[key].ended:
        await inter.response.send_message("すでに進行中のMVP投票があります。", ephemeral=True)
        return

    candidates = eligible_members_in_channel(inter.channel, inter.guild)
    cand_ids = {m.id for m in candidates}
    cand_info = {m.id: m.display_name for m in candidates}
    if len(cand_ids) < 2:
        await inter.response.send_message("候補者が少なすぎます。", ephemeral=True)
        return

    session = VoteSession(
        guild_id=inter.guild.id,
        channel_id=inter.channel.id,
        message_id=0,
        kind="mvp",
        mvp_candidates=cand_ids,
        mvp_candidates_info=cand_info,
    )
    view = MVPVoteView(session=session)

    await inter.response.send_message(
        "🏆 **MVP投票を開始しました！**\n"
        "「投票する」ボタンから最大2名を選んで投票してください。\n"
        "※運営が `/mvp_end` で締め切るまで投票可能です。",
        view=view
    )
    msg = await inter.original_response()
    session.message_id = msg.id
    bot.active_sessions[key] = session


@bot.tree.command(name="map_vote_start", description="MAP投票を開始（1人1票、10人で自動締切）（運営のみ）")
@require_admin_like(lambda: bot.cfg)
@app_commands.describe(duration_sec="自動締切までの秒数（省略可、デフォルト120秒）")
async def map_vote_start(inter: discord.Interaction, duration_sec: Optional[int] = 120):
    if not inter.guild or not inter.channel:
        await inter.response.send_message("サーバー内のチャンネルで実行してください。", ephemeral=True)
        return

    maps = bot.cfg.get("maps", [])
    if not maps:
        await inter.response.send_message("マップが未登録です（運営が /maps_add で追加してください）。", ephemeral=True)
        return

    key = (inter.guild.id, "map")
    if key in bot.active_sessions and not bot.active_sessions[key].ended:
        await inter.response.send_message("すでに進行中のMAP投票があります。", ephemeral=True)
        return

    session = VoteSession(
        guild_id=inter.guild.id,
        channel_id=inter.channel.id,
        message_id=0,
        kind="map",
        maps_snapshot=list(maps),
    )
    view = MapVoteView(session=session, timeout=float(duration_sec or 120))

    await inter.response.send_message(
        f"🗺️ **MAP投票を開始しました！**\n"
        f"下のメニューから1マップ選んで投票してください。\n"
        f"※投票者が **{MAP_AUTO_CLOSE_VOTERS}人** に到達すると自動で締め切ります。",
        view=view
    )
    msg = await inter.original_response()
    session.message_id = msg.id
    bot.active_sessions[key] = session


# -------------------------
# 投票締め切り（運営のみ） ※分離
# -------------------------

@bot.tree.command(name="mvp_end", description="進行中のMVP投票を締め切り（運営のみ）")
@require_admin_like(lambda: bot.cfg)
async def mvp_end(inter: discord.Interaction):
    if not inter.guild:
        await inter.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

    key = (inter.guild.id, "mvp")
    session = bot.active_sessions.get(key)
    if not session or session.ended:
        await inter.response.send_message("進行中のMVP投票はありません。", ephemeral=True)
        return

    await inter.response.defer(ephemeral=True)
    await bot.end_session(session, requested_by_text=f"{inter.user.mention}（手動）")
    await inter.followup.send("締め切りました。MVP結果は結果チャンネルへ投稿しました。", ephemeral=True)


@bot.tree.command(name="map_end", description="進行中のMAP投票を締め切り（運営のみ）")
@require_admin_like(lambda: bot.cfg)
async def map_end(inter: discord.Interaction):
    if not inter.guild:
        await inter.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return

    key = (inter.guild.id, "map")
    session = bot.active_sessions.get(key)
    if not session or session.ended:
        await inter.response.send_message("進行中のMAP投票はありません。", ephemeral=True)
        return

    await inter.response.defer(ephemeral=True)
    await bot.end_session(session, requested_by_text=f"{inter.user.mention}（手動）")
    await inter.followup.send("締め切りました。MAP結果は開始チャンネルに表示しました。", ephemeral=True)


# -------------------------
# エラー処理
# -------------------------

@bot.tree.error
async def on_app_command_error(inter: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        if inter.response.is_done():
            await inter.followup.send("このコマンドを実行する権限がありません。", ephemeral=True)
        else:
            await inter.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        return
    raise error


if __name__ == "__main__":
    # .envファイルから環境変数を読み込む
    load_dotenv()
    
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError(".envファイルまたは環境変数に DISCORD_BOT_TOKEN を設定してください。")
    bot.run(token)
