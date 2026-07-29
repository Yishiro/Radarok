import asyncio
import io
import logging
import math
import os
import random
import re
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "radarok.db"))
RANK_ASSET_DIR = BASE_DIR / "assets" / "ranks"
PRESERVED_SETUP_CHANNEL_IDS = {
    1531432945888526376,
    1531939680004739132,
}
BOT_UPDATE_CHANNEL_ID = 1531939680004739132
BOT_UPDATE_VERSION = "2026.07.29-clear-messages"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


ChannelKind = Literal["text", "voice", "stage"]


def stylize_channel_name(name: str) -> str:
    """Met la première lettre du nom en capitale mathématique grasse."""
    bold_capitals = {
        chr(ord("a") + index): chr(0x1D400 + index)
        for index in range(26)
    }
    bold_capitals.update(
        {
            chr(ord("A") + index): chr(0x1D400 + index)
            for index in range(26)
        }
    )
    start = name.find("・") + 1 if "・" in name else 0
    characters = list(name)
    for index in range(start, len(characters)):
        character = characters[index]
        if character.isalpha():
            characters[index] = bold_capitals.get(character, character.upper())
            break
    return "".join(characters)


def decorate_category_name(name: str) -> str:
    if (
        name.startswith("○")
        and name.endswith("➤")
        or name.startswith("『")
    ):
        return name
    return f"○─────{name}─────➤"


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    kind: ChannelKind = "text"
    user_limit: int = 0
    read_only: bool = False
    write_roles: tuple[str, ...] = ()
    member_connect: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", stylize_channel_name(self.name))


@dataclass(frozen=True)
class CategorySpec:
    name: str
    channels: tuple[ChannelSpec, ...]
    staff_only: bool = False
    verification_only: bool = False
    staff_voice: bool = False
    stats_only: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", decorate_category_name(self.name))


@dataclass(frozen=True)
class RoleSpec:
    name: str
    colour: int
    permissions: discord.Permissions = discord.Permissions.none()
    hoist: bool = False


# Les rôles sont déclarés du plus élevé au moins élevé.
ROLE_SPECS = (
    RoleSpec(
        "👑・Radarok",
        0xF1C40F,
        discord.Permissions(administrator=True),
        True,
    ),
    RoleSpec(
        "⚙️・Responsable",
        0xE67E22,
        discord.Permissions(
            manage_guild=True,
            manage_channels=True,
            manage_roles=True,
            manage_messages=True,
            kick_members=True,
            ban_members=True,
            moderate_members=True,
            view_audit_log=True,
        ),
        True,
    ),
    RoleSpec(
        "🛡️・Administrateur",
        0xE74C3C,
        discord.Permissions(
            manage_channels=True,
            manage_roles=True,
            manage_messages=True,
            kick_members=True,
            ban_members=True,
            moderate_members=True,
            view_audit_log=True,
        ),
        True,
    ),
    RoleSpec(
        "🔨・Modérateur",
        0x3498DB,
        discord.Permissions(
            manage_messages=True,
            kick_members=True,
            moderate_members=True,
            view_audit_log=True,
        ),
        True,
    ),
    RoleSpec(
        "🧪・Modérateur en test",
        0x5DADE2,
        discord.Permissions(manage_messages=True, moderate_members=True),
        True,
    ),
    RoleSpec("🎨・Graphiste", 0x9B59B6, hoist=True),
    RoleSpec("🤝・Partenaire", 0x1ABC9C, hoist=True),
    RoleSpec("⭐・VIP", 0xF39C12, hoist=True),
    RoleSpec("💎・Booster", 0xEB459E, hoist=True),
    RoleSpec("🥉・Recruteur", 0xCD7F32, hoist=True),
    RoleSpec("🥈・Ambassadeur", 0xBDC3C7, hoist=True),
    RoleSpec("🥇・Influenceur", 0xF1C40F, hoist=True),
    RoleSpec("💎・Maître recruteur", 0x9B59B6, hoist=True),
    RoleSpec("🎥・Créateur de contenu", 0xE91E63, hoist=True),
    RoleSpec("🏆・Gagnant Giveaway", 0xF4D03F, hoist=True),
    RoleSpec("👑・Capitaine d'équipage", 0xD4AF37, hoist=True),
    RoleSpec("🥇・Champion événement", 0xF1C40F, hoist=True),
    RoleSpec("🥈・Finaliste événement", 0xBDC3C7, hoist=True),
    RoleSpec("🥉・Troisième événement", 0xCD7F32, hoist=True),
    RoleSpec("✅・Membre", 0x2ECC71),
    RoleSpec("🔒・Non vérifié", 0x7F8C8D),
    RoleSpec("🤖・Bots", 0x95A5A6),
    RoleSpec("🔴・Vidéos YouTube", 0xFF0000),
    RoleSpec("🟣・Lives Twitch", 0x9146FF),
    RoleSpec("🎉・Giveaways", 0xF1C40F),
    RoleSpec("📢・Annonces", 0xE67E22),
    RoleSpec("🤝・Partenariats", 0x1ABC9C),
    RoleSpec("📰・Actualités Blox Fruits", 0x3498DB),
    RoleSpec("⚔️・PvP", 0xC0392B),
    RoleSpec("🏰・Raids", 0x8E44AD),
    RoleSpec("🌊・Sea Events", 0x2980B9),
    RoleSpec("🐉・V4", 0x8E44AD),
    RoleSpec("🔄・Trades", 0x16A085),
    RoleSpec("🆘・Helper", 0x27AE60, hoist=True),
    RoleSpec("👤・Human", 0xD5D8DC),
    RoleSpec("🐇・Rabbit", 0xF5B7B1),
    RoleSpec("🦈・Shark", 0x3498DB),
    RoleSpec("😇・Angel", 0xF7DC6F),
    RoleSpec("🧟・Ghoul", 0x7D3C98),
    RoleSpec("🤖・Cyborg", 0x707B7C),
    RoleSpec("🐉・Draco", 0xC0392B),
    RoleSpec("💫・Légende", 0xF1C40F),
    RoleSpec("🥇・Vétéran", 0xE67E22),
    RoleSpec("🥈・Actif", 0xBDC3C7),
    RoleSpec("🥉・Habitué", 0xCD7F32),
    RoleSpec("🌱・Nouveau", 0x82E0AA),
)


UNCATEGORIZED_CHANNELS: tuple[ChannelSpec, ...] = ()

SERVER_STRUCTURE = (
    CategorySpec(
        "『◉』 ╰⁺°✧・⚙(Vocales Staff)⚙・✧°⁺╮",
        (
            ChannelSpec("╰、🏆・𝐑adarok", "voice"),
            ChannelSpec("╰、🏆・𝐀lex", "voice"),
            ChannelSpec("━━━━━・✦・━━━━━", "voice"),
            ChannelSpec("╰、⚜️・𝐒taff 1", "voice"),
            ChannelSpec("╰、⚜️・𝐒taff 2", "voice"),
            ChannelSpec("╰、⚜️・𝐒taff 3", "voice"),
            ChannelSpec("╰、⚜️・𝐒taff 4", "voice"),
            ChannelSpec("╰、⚜️・𝐒taff 5", "voice"),
            ChannelSpec("╰、⚜️・𝐓est Vocal", "voice"),
            ChannelSpec(
                "╰、⚜️・𝐀ttente de move",
                "voice",
                member_connect=True,
            ),
        ),
        staff_voice=True,
    ),
    CategorySpec(
        "📊・SERVEUR STAT",
        (
            ChannelSpec("👥・Membres : 0", "voice"),
            ChannelSpec("✅・Humains : 0", "voice"),
            ChannelSpec("🤖・Bots : 0", "voice"),
            ChannelSpec("💎・Boosts : 0", "voice"),
        ),
        stats_only=True,
    ),
    CategorySpec(
        "🔐・VÉRIFICATION",
        (
            ChannelSpec("📜・règlement", read_only=True),
            ChannelSpec("👋・bienvenue", read_only=True),
            ChannelSpec("✅・vérification", read_only=True),
        ),
        verification_only=True,
    ),
    CategorySpec(
        "📌・ACCUEIL",
        (
            ChannelSpec("📢・annonces", read_only=True),
            ChannelSpec("🎭・choix-des-rôles", read_only=True),
            ChannelSpec("❓・faq", read_only=True),
            ChannelSpec("📰・changelog-serveur", read_only=True),
            ChannelSpec("💎・merci-boosts", read_only=True),
        ),
    ),
    CategorySpec(
        "🌐・RÉSEAUX",
        (
            ChannelSpec("🔴・youtube", read_only=True),
            ChannelSpec("🟣・twitch", read_only=True),
            ChannelSpec("🎵・tiktok", read_only=True),
            ChannelSpec("📱・réseaux", read_only=True),
            ChannelSpec("🔔・notifications", read_only=True),
        ),
    ),
    CategorySpec(
        "💬・COMMUNAUTÉ",
        (
            ChannelSpec("💬・discussion"),
            ChannelSpec("😂・memes"),
            ChannelSpec("📷・médias"),
            ChannelSpec("💡・suggestions"),
            ChannelSpec("📊・sondages", read_only=True),
            ChannelSpec("🏆・level", read_only=True),
            ChannelSpec("🤖・commandes-bots"),
            ChannelSpec("🎉・giveaways", read_only=True),
        ),
    ),
    CategorySpec(
        "🎪・ÉVÉNEMENT",
        (
            ChannelSpec("🎪・annonces-événement", read_only=True),
            ChannelSpec("🥇・événement", "stage"),
            ChannelSpec("🥈・événement", "stage"),
            ChannelSpec("🥉・événement", "stage"),
        ),
    ),
    CategorySpec(
        "🎨・PARTAGE",
        (
            ChannelSpec("🧠・idées"),
            ChannelSpec("🎬・vidéos"),
            ChannelSpec("🎥・clips-communauté"),
            ChannelSpec("🖌️・créations"),
        ),
    ),
    CategorySpec(
        "🤝・PARTENARIAT",
        (
            ChannelSpec("🤝・partenaire", read_only=True),
            ChannelSpec(
                "🗣️・chat-partenaire",
                read_only=True,
                write_roles=("🤝・Partenaire",),
            ),
        ),
    ),
    CategorySpec(
        "🍈・BLOX FRUITS",
        (
            ChannelSpec("👀・discussion-blox-fruit"),
            ChannelSpec("⚔️・pvp"),
            ChannelSpec("🏰・raids-et-donjons"),
            ChannelSpec("🌊・sea-events-et-boss"),
            ChannelSpec("🤝・trades"),
            ChannelSpec("📢・marché-trades", read_only=True),
            ChannelSpec("🆘・entraide-blox-fruit"),
            ChannelSpec("📰・actualités-et-stocks", read_only=True),
        ),
    ),
    CategorySpec(
        "🏴‍☠️・ÉQUIPAGES",
        (
            ChannelSpec("📋・présentation-des-équipages", read_only=True),
            ChannelSpec("📢・recrutement-équipage", read_only=True),
            ChannelSpec("📄・cv-joueurs", read_only=True),
        ),
    ),
    CategorySpec("🤝・TRADES PRIVÉS", (), staff_only=True),
    CategorySpec("🔒・ÉQUIPAGES PRIVÉS", (), staff_only=True),
    CategorySpec(
        "🎟️・SUPPORT",
        (
            ChannelSpec("📜・règlement-tickets", read_only=True),
            ChannelSpec("🎫・ouvrir-un-ticket", read_only=True),
            ChannelSpec("🤝・partenariats", read_only=True),
            ChannelSpec("🛡️・signalements", read_only=True),
        ),
    ),
    CategorySpec(
        "📝・RECRUTEMENT",
        (
            ChannelSpec("📋・informations-recrutement", read_only=True),
            ChannelSpec("📝・postuler", read_only=True),
        ),
    ),
    CategorySpec("🎫・TICKETS OUVERTS", (), staff_only=True),
    CategorySpec("⬆️・TICKETS REMONTÉS", (), staff_only=True),
    CategorySpec(
        "🔊・VOCAUX",
        (
            ChannelSpec("🔊・Général", "voice"),
            ChannelSpec("🎮・Blox Fruits", "voice"),
            ChannelSpec("⚔️・PvP", "voice", 10),
            ChannelSpec("🏰・Raids", "voice", 6),
            ChannelSpec("🌊・Sea Events", "voice", 12),
            ChannelSpec("😴・AFK", "voice"),
        ),
    ),
    CategorySpec(
        "⚓・CRÉE TON ÉQUIPAGE",
        (ChannelSpec("➕・Créer un vocal", "voice"),),
    ),
    CategorySpec(
        "🔒・ÉQUIPE",
        (
            ChannelSpec("💬・discussion-staff"),
            ChannelSpec("📋・organisation"),
            ChannelSpec("🏆・classement-helpers", read_only=True),
            ChannelSpec("📨・tickets-staff"),
            ChannelSpec("🔊・Vocal staff", "voice"),
        ),
        staff_only=True,
    ),
    CategorySpec(
        "🛡️・JOURNAUX",
        (
            ChannelSpec("📥・arrivées-départs"),
            ChannelSpec("🔊・logs-vocaux"),
            ChannelSpec("🗑️・messages-supprimés"),
            ChannelSpec("✏️・messages-modifiés"),
            ChannelSpec("⚖️・sanctions"),
            ChannelSpec("🧾・logs-discord"),
            ChannelSpec("📁・transcripts-tickets"),
        ),
        staff_only=True,
    ),
)

NOTIFICATION_ROLES = (
    "🔴・Vidéos YouTube",
    "🟣・Lives Twitch",
    "🎉・Giveaways",
    "📢・Annonces",
    "🤝・Partenariats",
    "📰・Actualités Blox Fruits",
)
ACTIVITY_ROLES = (
    "⚔️・PvP",
    "🏰・Raids",
    "🌊・Sea Events",
    "🐉・V4",
    "🔄・Trades",
)
RACE_ROLES = (
    "👤・Human",
    "🐇・Rabbit",
    "🦈・Shark",
    "😇・Angel",
    "🧟・Ghoul",
    "🤖・Cyborg",
    "🐉・Draco",
)

MEMBER_ROLE_NAME = "✅・Membre"
UNVERIFIED_ROLE_NAME = "🔒・Non vérifié"
BOT_ROLE_NAME = "🤖・Bots"
WELCOME_CHANNEL_NAME = stylize_channel_name("👋・bienvenue")
VERIFICATION_CHANNEL_NAME = stylize_channel_name("✅・vérification")
RULES_CHANNEL_NAME = stylize_channel_name("📜・règlement")
ROLE_SELECTION_CHANNEL_NAME = stylize_channel_name("🎭・choix-des-rôles")
FAQ_CHANNEL_NAME = stylize_channel_name("❓・faq")
CHANGELOG_CHANNEL_NAME = stylize_channel_name("📰・changelog-serveur")
SUGGESTIONS_CHANNEL_NAME = stylize_channel_name("💡・suggestions")
TRADE_CHANNEL_NAME = stylize_channel_name("🤝・trades")
PLAYER_CV_CHANNEL_NAME = stylize_channel_name("📄・cv-joueurs")
CREW_PRESENTATION_CHANNEL_NAME = stylize_channel_name(
    "📋・présentation-des-équipages"
)
CREW_RECRUITMENT_CHANNEL_NAME = stylize_channel_name("📢・recrutement-équipage")
CLIPS_CHANNEL_NAME = stylize_channel_name("🎥・clips-communauté")
BOOST_THANKS_CHANNEL_NAME = stylize_channel_name("💎・merci-boosts")
EVENT_ANNOUNCEMENT_CHANNEL_NAME = stylize_channel_name("🎪・annonces-événement")
TRADE_MARKET_CHANNEL_NAME = stylize_channel_name("📢・marché-trades")
PRIVATE_TRADE_CATEGORY_NAME = decorate_category_name("🤝・TRADES PRIVÉS")
CREW_CATEGORY_NAME = decorate_category_name("🔒・ÉQUIPAGES PRIVÉS")
CAPTAIN_ROLE_NAME = "👑・Capitaine d'équipage"
JOIN_LEAVE_LOG_CHANNEL_NAME = stylize_channel_name("📥・arrivées-départs")
VOICE_LOG_CHANNEL_NAME = stylize_channel_name("🔊・logs-vocaux")
DELETED_MESSAGE_LOG_CHANNEL_NAME = stylize_channel_name("🗑️・messages-supprimés")
EDITED_MESSAGE_LOG_CHANNEL_NAME = stylize_channel_name("✏️・messages-modifiés")
SANCTION_LOG_CHANNEL_NAME = stylize_channel_name("⚖️・sanctions")
DISCORD_AUDIT_LOG_CHANNEL_NAME = stylize_channel_name("🧾・logs-discord")
JOURNALS_CATEGORY_NAME = decorate_category_name("🛡️・JOURNAUX")
COMMANDS_CHANNEL_NAME = stylize_channel_name("🤖・commandes-bots")
TEMP_VOICE_CATEGORY_NAME = decorate_category_name("⚓・CRÉE TON ÉQUIPAGE")
TEMP_VOICE_TRIGGER_NAME = stylize_channel_name("➕・Créer un vocal")
TEMP_VOICE_PREFIX = "🎙️・𝐄quipage de "
TICKET_PANEL_CHANNEL_NAME = stylize_channel_name("🎫・ouvrir-un-ticket")
TICKET_RULES_CHANNEL_NAME = stylize_channel_name("📜・règlement-tickets")
RECRUITMENT_INFO_CHANNEL_NAME = stylize_channel_name("📋・informations-recrutement")
RECRUITMENT_PANEL_CHANNEL_NAME = stylize_channel_name("📝・postuler")
TICKET_CATEGORY_NAME = decorate_category_name("🎫・TICKETS OUVERTS")
ESCALATED_TICKET_CATEGORY_NAME = decorate_category_name("⬆️・TICKETS REMONTÉS")
TICKET_LOG_CHANNEL_NAME = stylize_channel_name("📨・tickets-staff")
TICKET_TRANSCRIPT_CHANNEL_NAME = stylize_channel_name("📁・transcripts-tickets")
HELPER_LEADERBOARD_CHANNEL_NAME = stylize_channel_name("🏆・classement-helpers")
HELPER_ROLE_NAME = "🆘・Helper"
SUPERIOR_STAFF_ROLE_NAME = "🔱・Staff supérieur"
SUPERIOR_SOURCE_ROLE_NAMES = (
    "👑・Radarok",
    "⚙️・Responsable",
    "🛡️・Administrateur",
)
STAFF_VOICE_CATEGORY_NAME = decorate_category_name(
    "『◉』 ╰⁺°✧・⚙(Vocales Staff)⚙・✧°⁺╮"
)
SERVER_STATS_CATEGORY_NAME = decorate_category_name("📊・SERVEUR STAT")
STAFF_ROLE_NAMES = (
    "👑・Radarok",
    "⚙️・Responsable",
    "🛡️・Administrateur",
    "🔨・Modérateur",
    "🧪・Modérateur en test",
    SUPERIOR_STAFF_ROLE_NAME,
)
MESSAGE_XP_COOLDOWN = 60
MESSAGE_XP_MIN = 15
MESSAGE_XP_MAX = 25
VOICE_XP_PER_MINUTE = 5
CREW_CREATION_LEVEL = 10
LEVEL_ROLE_THRESHOLDS = (
    (35, "💫・Légende"),
    (20, "🥇・Vétéran"),
    (10, "🥈・Actif"),
    (5, "🥉・Habitué"),
    (1, "🌱・Nouveau"),
)
RANK_CARD_TIERS = (
    (35, "Légende", "legende.png", (175, 92, 255)),
    (20, "Vétéran", "veteran.png", (255, 190, 55)),
    (10, "Actif", "actif.png", (72, 193, 255)),
    (5, "Habitué", "habitue.png", (214, 130, 62)),
    (0, "Nouveau", "nouveau.png", (92, 220, 126)),
)
INVITE_ROLE_TIERS = (
    (20, "💎・Maître recruteur", 2.0),
    (15, "🥇・Influenceur", 1.5),
    (10, "🥈・Ambassadeur", 1.0),
    (5, "🥉・Recruteur", 0.5),
)
SPAM_MESSAGE_LIMIT = 6
SPAM_WINDOW_SECONDS = 8
SPAM_TIMEOUT_MINUTES = 5
MASS_MENTION_LIMIT = 5
MASS_MENTION_TIMEOUT_MINUTES = 10
URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
SUSPICIOUS_DOMAIN_MARKERS = (
    "discord-gift",
    "discordnitro",
    "discord-app",
    "steamcommunlty",
    "steampowered-offer",
    "roblox-gift",
    "robux-generator",
    "free-robux",
)
URL_SHORTENERS = {
    "bit.ly",
    "tinyurl.com",
    "cutt.ly",
    "t.co",
    "is.gd",
    "rb.gy",
}
SOCIAL_BUMP_MESSAGES = {
    stylize_channel_name("🔴・youtube"): (
        "🔴 **YouTube Radarok**\n"
        "Pense à consulter les dernières vidéos, à t'abonner et à activer la cloche !"
    ),
    stylize_channel_name("🟣・twitch"): (
        "🟣 **Twitch Radarok**\n"
        "Suis la chaîne pour ne manquer aucun live et rejoindre l'équipage en direct !"
    ),
    stylize_channel_name("🎵・tiktok"): (
        "🎵 **TikTok Radarok**\n"
        "Découvre les nouveaux extraits et pense à suivre le compte pour soutenir Radarok !"
    ),
    stylize_channel_name("📱・réseaux"): (
        "📱 **Réseaux de Radarok**\n"
        "Retrouve ici toutes les actualités et les plateformes officielles de Radarok."
    ),
}
SOCIAL_BUMP_HOURS = (9, 15, 21)
PARIS_TIMEZONE = ZoneInfo("Europe/Paris")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
database: sqlite3.Connection | None = None
message_timestamps: defaultdict[
    tuple[int, int], deque[float]
] = defaultdict(deque)
invite_cache: dict[int, dict[str, int]] = {}
voice_join_times: dict[tuple[int, int], float] = {}


def initialize_database() -> None:
    global database
    database = sqlite3.connect(DATABASE_PATH)
    database.execute("PRAGMA journal_mode=WAL")
    database.execute("PRAGMA synchronous=NORMAL")
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS member_stats (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message_xp INTEGER NOT NULL DEFAULT 0,
            voice_xp INTEGER NOT NULL DEFAULT 0,
            bonus_xp INTEGER NOT NULL DEFAULT 0,
            voice_seconds INTEGER NOT NULL DEFAULT 0,
            total_messages INTEGER NOT NULL DEFAULT 0,
            last_message_xp INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """
    )
    columns = {
        row[1] for row in database.execute("PRAGMA table_info(member_stats)")
    }
    if "bonus_xp" not in columns:
        database.execute(
            "ALTER TABLE member_stats ADD COLUMN bonus_xp INTEGER NOT NULL DEFAULT 0"
        )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            ticket_type TEXT NOT NULL,
            channel_id INTEGER NOT NULL UNIQUE,
            claimed_by INTEGER,
            status TEXT NOT NULL DEFAULT 'open',
            created_at INTEGER NOT NULL
        )
        """
    )
    database.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_open_tickets
        ON tickets (guild_id, user_id, ticket_type, status)
        """
    )
    ticket_columns = {
        row[1] for row in database.execute("PRAGMA table_info(tickets)")
    }
    if "escalated" not in ticket_columns:
        database.execute(
            "ALTER TABLE tickets ADD COLUMN escalated INTEGER NOT NULL DEFAULT 0"
        )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS helper_stats (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            resolved_tickets INTEGER NOT NULL DEFAULT 0,
            points INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS invite_stats (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            invite_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS giveaways (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            winners_count INTEGER NOT NULL DEFAULT 1,
            ends_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at INTEGER NOT NULL
        )
        """
    )
    giveaway_columns = {
        row[1] for row in database.execute("PRAGMA table_info(giveaways)")
    }
    if "reminded_24h" not in giveaway_columns:
        database.execute(
            "ALTER TABLE giveaways ADD COLUMN reminded_24h INTEGER NOT NULL DEFAULT 0"
        )
    if "reminded_1h" not in giveaway_columns:
        database.execute(
            "ALTER TABLE giveaways ADD COLUMN reminded_1h INTEGER NOT NULL DEFAULT 0"
        )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS giveaway_entries (
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at INTEGER NOT NULL,
            PRIMARY KEY (message_id, user_id),
            FOREIGN KEY (message_id) REFERENCES giveaways(message_id)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS social_bumps (
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            last_slot TEXT NOT NULL,
            message_id INTEGER,
            PRIMARY KEY (guild_id, channel_id)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS event_reminders (
            guild_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            reminder_kind TEXT NOT NULL,
            sent_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, event_id, reminder_kind)
        )
        """
    )
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS crews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            text_channel_id INTEGER NOT NULL,
            voice_channel_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            UNIQUE (guild_id, owner_id)
        );
        CREATE TABLE IF NOT EXISTS crew_members (
            crew_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS trade_posts (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            offered TEXT NOT NULL,
            wanted TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trade_deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            post_message_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trade_reviews (
            deal_id INTEGER NOT NULL,
            reviewer_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            stars INTEGER NOT NULL,
            comment TEXT,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (deal_id, reviewer_id)
        );
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            removed_by INTEGER,
            removed_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS sanctions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS community_events (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            starts_at INTEGER NOT NULL,
            capacity INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled',
            reminded_24h INTEGER NOT NULL DEFAULT 0,
            reminded_30m INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS community_event_entries (
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at INTEGER NOT NULL,
            PRIMARY KEY (message_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS player_cvs (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            roblox_name TEXT NOT NULL,
            level TEXT NOT NULL,
            sea TEXT NOT NULL,
            profile TEXT NOT NULL,
            availability TEXT NOT NULL,
            looking_for TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS crew_recruitments (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            crew_id INTEGER NOT NULL,
            captain_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            requirements TEXT NOT NULL,
            sought_profiles TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS crew_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            recruitment_message_id INTEGER NOT NULL,
            crew_id INTEGER NOT NULL,
            captain_id INTEGER NOT NULL,
            applicant_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'open',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bot_update_posts (
            guild_id INTEGER NOT NULL,
            version TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            posted_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, version)
        );
        CREATE TABLE IF NOT EXISTS audit_log_state (
            guild_id INTEGER PRIMARY KEY,
            last_entry_id INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS moderation_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            removed_by INTEGER,
            removed_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            staff_id INTEGER,
            staff_response TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS suggestion_votes (
            suggestion_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            vote INTEGER NOT NULL,
            voted_at INTEGER NOT NULL,
            PRIMARY KEY (suggestion_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS crew_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            crew_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target_id INTEGER,
            created_at INTEGER NOT NULL
        );
        """
    )
    crew_columns = {
        row[1] for row in database.execute("PRAGMA table_info(crews)")
    }
    if "presentation_message_id" not in crew_columns:
        database.execute(
            "ALTER TABLE crews ADD COLUMN presentation_message_id INTEGER"
        )
    if "vice_captain_id" not in crew_columns:
        database.execute(
            "ALTER TABLE crews ADD COLUMN vice_captain_id INTEGER"
        )
    if "max_members" not in crew_columns:
        database.execute(
            "ALTER TABLE crews ADD COLUMN max_members INTEGER NOT NULL DEFAULT 20"
        )
    ticket_columns = {
        row[1] for row in database.execute("PRAGMA table_info(tickets)")
    }
    for column_name in ("claimed_at", "closed_by", "closed_at"):
        if column_name not in ticket_columns:
            database.execute(f"ALTER TABLE tickets ADD COLUMN {column_name} INTEGER")
    sanction_columns = {
        row[1] for row in database.execute("PRAGMA table_info(sanctions)")
    }
    for column_name in ("cancelled_by", "cancelled_at"):
        if column_name not in sanction_columns:
            database.execute(
                f"ALTER TABLE sanctions ADD COLUMN {column_name} INTEGER"
            )
    database.commit()


def require_database() -> sqlite3.Connection:
    if database is None:
        raise RuntimeError("La base de données n'est pas initialisée")
    return database


def calculate_level(total_xp: int) -> int:
    return math.isqrt(max(total_xp, 0) // 100)


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours} h {minutes:02d} min"


def load_card_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    filenames = (
        ("DejaVuSans-Bold.ttf", "arialbd.ttf")
        if bold
        else ("DejaVuSans.ttf", "arial.ttf")
    )
    candidates = [
        *(RANK_ASSET_DIR / filename for filename in filenames),
        *(Path("C:/Windows/Fonts") / filename for filename in filenames),
        *(Path("/usr/share/fonts/truetype/dejavu") / filename for filename in filenames),
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    for filename in filenames:
        try:
            return ImageFont.truetype(filename, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def get_rank_tier(level: int) -> tuple[str, Path, tuple[int, int, int]]:
    for required_level, name, filename, colour in RANK_CARD_TIERS:
        if level >= required_level:
            return name, RANK_ASSET_DIR / filename, colour
    raise RuntimeError("Aucun rang ne correspond au niveau")


def generate_level_card(
    *,
    username: str,
    level: int,
    total_xp: int,
    progress: int,
    required: int,
    total_messages: int,
    voice_seconds: int,
    leaderboard_position: int,
) -> io.BytesIO:
    width, height = 1100, 430
    card = Image.new("RGBA", (width, height), (8, 16, 32, 255))
    draw = ImageDraw.Draw(card)
    rank_name, emblem_path, accent = get_rank_tier(level)

    for y in range(height):
        ratio = y / max(height - 1, 1)
        colour = (
            int(8 + accent[0] * 0.07 * ratio),
            int(16 + accent[1] * 0.08 * ratio),
            int(32 + accent[2] * 0.12 * ratio),
            255,
        )
        draw.line((0, y, width, y), fill=colour)

    draw.rounded_rectangle(
        (14, 14, width - 14, height - 14),
        radius=34,
        outline=(*accent, 210),
        width=3,
    )
    draw.ellipse((35, 55, 355, 375), fill=(*accent, 25))

    emblem = Image.open(emblem_path).convert("RGBA")
    emblem.thumbnail((300, 300), Image.Resampling.LANCZOS)
    emblem_x = 195 - emblem.width // 2
    emblem_y = height // 2 - emblem.height // 2
    card.alpha_composite(emblem, (emblem_x, emblem_y))

    title_font = load_card_font(42, bold=True)
    rank_font = load_card_font(25, bold=True)
    stat_font = load_card_font(23, bold=True)
    small_font = load_card_font(19)
    username_display = username[:24]

    draw.text((390, 48), username_display, font=title_font, fill=(245, 248, 255))
    draw.text(
        (392, 101),
        f"{rank_name.upper()}  •  NIVEAU {level}",
        font=rank_font,
        fill=accent,
    )

    bar_left, bar_top, bar_right, bar_bottom = 392, 158, 1035, 190
    draw.rounded_rectangle(
        (bar_left, bar_top, bar_right, bar_bottom),
        radius=16,
        fill=(26, 38, 58),
    )
    ratio = min(max(progress / required if required else 1, 0), 1)
    filled_right = bar_left + int((bar_right - bar_left) * ratio)
    if filled_right > bar_left:
        draw.rounded_rectangle(
            (bar_left, bar_top, filled_right, bar_bottom),
            radius=16,
            fill=accent,
        )
    draw.text(
        (392, 201),
        f"{progress:,} / {required:,} XP vers le prochain niveau",
        font=small_font,
        fill=(185, 198, 218),
    )

    stats = (
        (392, 265, "XP TOTAL", f"{total_xp:,}"),
        (620, 265, "MESSAGES", f"{total_messages:,}"),
        (840, 265, "TEMPS VOCAL", format_duration(voice_seconds)),
        (392, 346, "CLASSEMENT", f"#{leaderboard_position}"),
    )
    for x, y, label, value in stats:
        draw.text((x, y), label, font=small_font, fill=(145, 160, 184))
        draw.text((x, y + 27), value, font=stat_font, fill=(245, 248, 255))

    output = io.BytesIO()
    card.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


def get_member_stats(
    guild_id: int, user_id: int
) -> tuple[int, int, int, int, int]:
    row = require_database().execute(
        """
        SELECT message_xp, voice_xp, bonus_xp, voice_seconds, total_messages
        FROM member_stats
        WHERE guild_id = ? AND user_id = ?
        """,
        (guild_id, user_id),
    ).fetchone()
    return tuple(row) if row is not None else (0, 0, 0, 0, 0)


def award_message_xp(guild_id: int, user_id: int) -> bool:
    now = int(time.time())
    xp = random.randint(MESSAGE_XP_MIN, MESSAGE_XP_MAX)
    connection = require_database()
    previous = connection.execute(
        """
        SELECT last_message_xp
        FROM member_stats
        WHERE guild_id = ? AND user_id = ?
        """,
        (guild_id, user_id),
    ).fetchone()
    awarded = (
        previous is None
        or previous[0] <= now - MESSAGE_XP_COOLDOWN
    )
    connection.execute(
        """
        INSERT INTO member_stats (
            guild_id, user_id, message_xp, total_messages, last_message_xp
        )
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            total_messages = total_messages + 1,
            message_xp = message_xp + CASE
                WHEN last_message_xp <= ? THEN excluded.message_xp
                ELSE 0
            END,
            last_message_xp = CASE
                WHEN last_message_xp <= ? THEN excluded.last_message_xp
                ELSE last_message_xp
            END
        """,
        (
            guild_id,
            user_id,
            xp,
            now,
            now - MESSAGE_XP_COOLDOWN,
            now - MESSAGE_XP_COOLDOWN,
        ),
    )
    connection.commit()
    return awarded


def award_voice_xp_batch(entries: list[tuple[int, int]]) -> None:
    if not entries:
        return
    connection = require_database()
    connection.executemany(
        """
        INSERT INTO member_stats (
            guild_id, user_id, voice_xp, voice_seconds
        )
        VALUES (?, ?, ?, 60)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            voice_xp = voice_xp + excluded.voice_xp,
            voice_seconds = voice_seconds + 60
        """,
        [
            (guild_id, user_id, VOICE_XP_PER_MINUTE)
            for guild_id, user_id in entries
        ],
    )
    connection.commit()


async def update_level_role(member: discord.Member) -> None:
    message_xp, voice_xp, bonus_xp, _, _ = get_member_stats(
        member.guild.id, member.id
    )
    level = calculate_level(message_xp + voice_xp + bonus_xp)
    progression_names = {role_name for _, role_name in LEVEL_ROLE_THRESHOLDS}
    target_name = next(
        (
            role_name
            for required_level, role_name in LEVEL_ROLE_THRESHOLDS
            if level >= required_level
        ),
        None,
    )
    current_progression = [
        role for role in member.roles if role.name in progression_names
    ]
    target_role = (
        discord.utils.get(member.guild.roles, name=target_name)
        if target_name is not None
        else None
    )
    roles_to_remove = [
        role for role in current_progression if role != target_role
    ]
    try:
        if roles_to_remove:
            await member.remove_roles(
                *roles_to_remove, reason=f"Progression automatique niveau {level}"
            )
        if target_role is not None and target_role not in member.roles:
            await member.add_roles(
                target_role, reason=f"Progression automatique niveau {level}"
            )
    except discord.Forbidden:
        logging.warning(
            "Impossible de mettre à jour le rôle de niveau de %s", member
        )


def contains_suspicious_link(content: str) -> bool:
    for raw_url in URL_PATTERN.findall(content):
        try:
            parsed = urlparse(raw_url)
            hostname = (parsed.hostname or "").lower().removeprefix("www.")
        except ValueError:
            return True
        if (
            not hostname
            or hostname in URL_SHORTENERS
            or "@" in parsed.netloc
            or any(part.startswith("xn--") for part in hostname.split("."))
            or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", hostname)
            or any(marker in raw_url.lower() for marker in SUSPICIOUS_DOMAIN_MARKERS)
        ):
            return True
    return False


async def punish_message(
    message: discord.Message,
    *,
    reason: str,
    timeout_minutes: int,
) -> None:
    try:
        await message.delete()
    except discord.HTTPException:
        pass
    if isinstance(message.author, discord.Member):
        try:
            await message.author.timeout(
                timedelta(minutes=timeout_minutes),
                reason=reason,
            )
            if message.guild is not None:
                await send_sanction_log(
                    message.guild,
                    action=f"Timeout automatique de {timeout_minutes} min",
                    target=message.author,
                    moderator=None,
                    reason=reason,
                )
        except discord.HTTPException:
            logging.warning("Impossible de timeout %s", message.author)
    try:
        await message.channel.send(
            f"⚠️ {message.author.mention} : {reason}.",
            delete_after=10,
        )
    except discord.HTTPException:
        pass


async def moderate_message(message: discord.Message) -> bool:
    if (
        message.guild is None
        or not isinstance(message.author, discord.Member)
        or is_ticket_staff(message.author)
    ):
        return False

    raw_lower = message.content.lower()
    mention_count = len({member.id for member in message.mentions}) + len(
        {role.id for role in message.role_mentions}
    )
    if (
        "@everyone" in raw_lower
        or "@here" in raw_lower
        or mention_count >= MASS_MENTION_LIMIT
    ):
        await punish_message(
            message,
            reason="mentions massives interdites",
            timeout_minutes=MASS_MENTION_TIMEOUT_MINUTES,
        )
        return True

    if contains_suspicious_link(message.content):
        await punish_message(
            message,
            reason="lien potentiellement frauduleux détecté",
            timeout_minutes=30,
        )
        return True

    key = (message.guild.id, message.author.id)
    now = time.monotonic()
    timestamps = message_timestamps[key]
    timestamps.append(now)
    while timestamps and timestamps[0] < now - SPAM_WINDOW_SECONDS:
        timestamps.popleft()
    if len(timestamps) >= SPAM_MESSAGE_LIMIT:
        timestamps.clear()
        await punish_message(
            message,
            reason="spam détecté",
            timeout_minutes=SPAM_TIMEOUT_MINUTES,
        )
        return True
    return False


class SelfRoleSelect(discord.ui.Select):
    def __init__(
        self,
        *,
        role_names: tuple[str, ...],
        placeholder: str,
        custom_id: str,
        max_values: int,
    ) -> None:
        self.role_names = role_names
        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=max_values,
            options=[
                discord.SelectOption(label=role_name, value=role_name)
                for role_name in role_names
            ],
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Ce menu fonctionne uniquement dans le serveur.", ephemeral=True
            )
            return

        group_roles = [
            role
            for role_name in self.role_names
            if (role := discord.utils.get(interaction.guild.roles, name=role_name))
            is not None
        ]
        selected_roles = [role for role in group_roles if role.name in self.values]
        roles_to_remove = [
            role
            for role in group_roles
            if role in interaction.user.roles and role not in selected_roles
        ]
        roles_to_add = [
            role for role in selected_roles if role not in interaction.user.roles
        ]

        try:
            if roles_to_remove:
                await interaction.user.remove_roles(
                    *roles_to_remove, reason="Choix de rôles par le membre"
                )
            if roles_to_add:
                await interaction.user.add_roles(
                    *roles_to_add, reason="Choix de rôles par le membre"
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Je ne peux pas attribuer ces rôles. Place mon rôle au-dessus des "
                "rôles communautaires.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Tes rôles ont bien été mis à jour.", ephemeral=True
        )


class VerificationView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Je valide le règlement",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="radarok:verification:accept",
    )
    async def verify(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if interaction.guild is None or not isinstance(
            interaction.user, discord.Member
        ):
            await interaction.response.send_message(
                "Cette vérification fonctionne uniquement dans le serveur.",
                ephemeral=True,
            )
            return
        member_role = discord.utils.get(
            interaction.guild.roles, name=MEMBER_ROLE_NAME
        )
        unverified_role = discord.utils.get(
            interaction.guild.roles, name=UNVERIFIED_ROLE_NAME
        )
        if member_role is None or unverified_role is None:
            await interaction.response.send_message(
                "Les rôles de vérification sont absents. Contacte un administrateur.",
                ephemeral=True,
            )
            return
        if member_role in interaction.user.roles:
            await interaction.response.send_message(
                "Tu es déjà vérifié.", ephemeral=True
            )
            return
        try:
            await interaction.user.add_roles(
                member_role, reason="Règlement accepté via le panel"
            )
            if unverified_role in interaction.user.roles:
                await interaction.user.remove_roles(
                    unverified_role, reason="Vérification terminée"
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Je ne peux pas modifier tes rôles. Place mon rôle au-dessus des "
                "rôles de vérification.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "✅ Vérification réussie ! Tu as maintenant accès à la communauté.",
            ephemeral=True,
        )


class RoleSelectionView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            SelfRoleSelect(
                role_names=NOTIFICATION_ROLES,
                placeholder="Choisis tes notifications",
                custom_id="radarok:roles:notifications",
                max_values=len(NOTIFICATION_ROLES),
            )
        )
        self.add_item(
            SelfRoleSelect(
                role_names=ACTIVITY_ROLES,
                placeholder="Choisis tes activités Blox Fruits",
                custom_id="radarok:roles:activities",
                max_values=len(ACTIVITY_ROLES),
            )
        )
        self.add_item(
            SelfRoleSelect(
                role_names=RACE_ROLES,
                placeholder="Choisis ta race Blox Fruits",
                custom_id="radarok:roles:race",
                max_values=1,
            )
        )


def is_ticket_staff(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(
        role.name in STAFF_ROLE_NAMES for role in member.roles
    )


def is_helper(member: discord.Member) -> bool:
    return any(role.name == HELPER_ROLE_NAME for role in member.roles)


async def update_helper_leaderboard(guild: discord.Guild) -> None:
    channel = discord.utils.get(
        guild.text_channels, name=HELPER_LEADERBOARD_CHANNEL_NAME
    )
    if channel is None:
        return
    rows = require_database().execute(
        """
        SELECT user_id, points, resolved_tickets
        FROM helper_stats WHERE guild_id = ?
        ORDER BY points DESC, resolved_tickets DESC LIMIT 15
        """,
        (guild.id,),
    ).fetchall()
    lines = []
    for position, (user_id, points, resolved) in enumerate(rows, start=1):
        member = guild.get_member(user_id)
        label = member.mention if member is not None else f"<@{user_id}>"
        lines.append(
            f"`#{position}` {label} — **{points} point(s)** • {resolved} ticket(s)"
        )
    embed = discord.Embed(
        title="🏆 Classement des helpers",
        description="\n".join(lines) if lines else "Aucun ticket résolu pour le moment.",
        colour=discord.Colour.gold(),
    )
    try:
        await channel.purge(limit=10, check=lambda message: message.author == bot.user)
        await channel.send(embed=embed)
    except discord.HTTPException:
        logging.exception("Impossible de mettre à jour le classement des helpers")


async def create_ticket(
    interaction: discord.Interaction,
    ticket_type: str,
    subject: str,
    details: str,
) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    guild = interaction.guild
    connection = require_database()
    existing = connection.execute(
        """
        SELECT channel_id FROM tickets
        WHERE guild_id = ? AND user_id = ? AND ticket_type = ? AND status = 'open'
        """,
        (guild.id, interaction.user.id, ticket_type),
    ).fetchone()
    if existing is not None:
        existing_channel = guild.get_channel(existing[0])
        if existing_channel is not None:
            await interaction.response.send_message(
                f"Tu as déjà un ticket de ce type : {existing_channel.mention}",
                ephemeral=True,
            )
            return
        connection.execute(
            "UPDATE tickets SET status = 'closed' WHERE channel_id = ?",
            (existing[0],),
        )
        connection.commit()

    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
    if category is None:
        await interaction.response.send_message(
            "La catégorie des tickets est absente. Contacte un administrateur.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    overwrites = dict(category.overwrites)
    overwrites[interaction.user] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
    )
    helper_role = discord.utils.get(guild.roles, name=HELPER_ROLE_NAME)
    if helper_role is not None:
        overwrites[helper_role] = discord.PermissionOverwrite(
            view_channel=ticket_type in {"assistance", "signalement"},
            send_messages=ticket_type in {"assistance", "signalement"},
            read_message_history=ticket_type in {"assistance", "signalement"},
            attach_files=ticket_type in {"assistance", "signalement"},
        )
    safe_user = "".join(
        character for character in interaction.user.name.lower()
        if character.isalnum() or character == "-"
    )[:30] or str(interaction.user.id)
    channel = await guild.create_text_channel(
        stylize_channel_name(f"🎫・{ticket_type}-{safe_user}"),
        category=category,
        overwrites=overwrites,
        reason=f"Ticket {ticket_type} ouvert par {interaction.user}",
    )
    cursor = connection.execute(
        """
        INSERT INTO tickets (
            guild_id, user_id, ticket_type, channel_id, created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            guild.id,
            interaction.user.id,
            ticket_type,
            channel.id,
            int(time.time()),
        ),
    )
    connection.commit()

    embed = discord.Embed(
        title=f"🎫 Ticket #{cursor.lastrowid} • {ticket_type.title()}",
        description=(
            f"Ticket ouvert par {interaction.user.mention}.\n"
            "Un membre de l'équipe prendra bientôt la demande en charge."
        ),
        colour=discord.Colour.orange(),
    )
    embed.add_field(name="Sujet", value=subject[:1024], inline=False)
    embed.add_field(name="Détails", value=details[:1024], inline=False)
    embed.set_footer(text="Utilisez les boutons ci-dessous pour gérer le ticket")
    await channel.send(
        content=interaction.user.mention,
        embed=embed,
        view=TicketControlView(),
    )
    await interaction.followup.send(
        f"Ton ticket a été créé : {channel.mention}", ephemeral=True
    )


class TicketModal(discord.ui.Modal):
    def __init__(self, ticket_type: str, title: str) -> None:
        super().__init__(title=title, timeout=300)
        self.ticket_type = ticket_type
        self.subject = discord.ui.TextInput(
            label="Sujet de la demande",
            placeholder="Résume ta demande en quelques mots",
            max_length=100,
        )
        self.details = discord.ui.TextInput(
            label="Explique ta demande",
            placeholder="Donne toutes les informations utiles au staff",
            style=discord.TextStyle.paragraph,
            min_length=10,
            max_length=1000,
        )
        self.add_item(self.subject)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await create_ticket(
            interaction,
            self.ticket_type,
            str(self.subject),
            str(self.details),
        )


class TicketPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Assistance",
        emoji="🆘",
        style=discord.ButtonStyle.primary,
        custom_id="radarok:ticket:assistance",
    )
    async def assistance(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(
            TicketModal("assistance", "🆘 Demande d'assistance")
        )

    @discord.ui.button(
        label="Partenariat",
        emoji="🤝",
        style=discord.ButtonStyle.secondary,
        custom_id="radarok:ticket:partenariat",
    )
    async def partnership(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(
            TicketModal("partenariat", "🤝 Demande de partenariat")
        )

    @discord.ui.button(
        label="Signalement",
        emoji="🛡️",
        style=discord.ButtonStyle.danger,
        custom_id="radarok:ticket:signalement",
    )
    async def report(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(
            TicketModal("signalement", "🛡️ Signaler un problème")
        )


class RecruitmentModal(discord.ui.Modal):
    def __init__(self) -> None:
        super().__init__(title="📝 Candidature au staff", timeout=600)
        self.age = discord.ui.TextInput(
            label="Ton âge",
            placeholder="Indique ton âge réel",
            max_length=3,
        )
        self.availability = discord.ui.TextInput(
            label="Tes disponibilités",
            placeholder="Exemple : semaine 18h-22h, week-end...",
            max_length=150,
        )
        self.experience = discord.ui.TextInput(
            label="Ton expérience",
            placeholder="Modération, Discord, communautés...",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=250,
        )
        self.motivation = discord.ui.TextInput(
            label="Pourquoi rejoindre l'équipe ?",
            placeholder="Présente tes motivations et ce que tu peux apporter",
            style=discord.TextStyle.paragraph,
            min_length=30,
            max_length=500,
        )
        self.add_item(self.age)
        self.add_item(self.availability)
        self.add_item(self.experience)
        self.add_item(self.motivation)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        subject = f"Candidature staff • {self.age} ans"
        details = (
            f"**Âge :** {self.age}\n"
            f"**Disponibilités :** {self.availability}\n"
            f"**Expérience :** {self.experience or 'Aucune indiquée'}\n\n"
            f"**Motivation :**\n{self.motivation}"
        )
        await create_ticket(interaction, "recrutement", subject, details)


class RecruitmentPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Déposer ma candidature",
        emoji="📝",
        style=discord.ButtonStyle.success,
        custom_id="radarok:recruitment:apply",
    )
    async def apply(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(RecruitmentModal())


async def close_ticket(
    interaction: discord.Interaction, channel: discord.TextChannel
) -> None:
    connection = require_database()
    row = connection.execute(
        """
        SELECT id, user_id, ticket_type, claimed_by, escalated FROM tickets
        WHERE channel_id = ? AND status = 'open'
        """,
        (channel.id,),
    ).fetchone()
    if row is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "Ce salon n'est pas un ticket actif.", ephemeral=True
        )
        return
    ticket_id, opener_id, ticket_type, claimed_by, escalated = row
    helper_can_close = (
        is_helper(interaction.user)
        and claimed_by == interaction.user.id
        and not escalated
    )
    if (
        interaction.user.id == opener_id
        and claimed_by is not None
        and not is_ticket_staff(interaction.user)
    ):
        await interaction.response.send_message(
            "Ce ticket est pris en charge. Seul le helper assigné ou le staff "
            "supérieur peut maintenant le clôturer.",
            ephemeral=True,
        )
        return
    if (
        interaction.user.id != opener_id
        and not is_ticket_staff(interaction.user)
        and not helper_can_close
    ):
        await interaction.response.send_message(
            "Seul l'auteur du ticket ou le staff peut le fermer.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "Le ticket va être fermé et archivé.", ephemeral=True
    )
    transcript_lines = [
        f"Ticket #{ticket_id} — {ticket_type}",
        f"Serveur : {channel.guild.name} ({channel.guild.id})",
        f"Salon : {channel.name} ({channel.id})",
        "",
    ]
    async for message in channel.history(limit=None, oldest_first=True):
        content = message.clean_content or "[message sans texte]"
        attachments = " ".join(attachment.url for attachment in message.attachments)
        transcript_lines.append(
            f"[{message.created_at.isoformat()}] {message.author} ({message.author.id}): "
            f"{content} {attachments}".rstrip()
        )

    transcript_directory = Path("transcripts")
    transcript_directory.mkdir(exist_ok=True)
    transcript_path = transcript_directory / f"ticket-{ticket_id}.txt"
    transcript_path.write_text("\n".join(transcript_lines), encoding="utf-8")

    log_channel = discord.utils.get(
        channel.guild.text_channels, name=TICKET_TRANSCRIPT_CHANNEL_NAME
    )
    if log_channel is not None:
        embed = discord.Embed(
            title=f"📁 Ticket #{ticket_id} fermé",
            description=(
                f"Type : **{ticket_type}**\n"
                f"Auteur : <@{opener_id}>\n"
                f"Fermé par : {interaction.user.mention}"
            ),
            colour=discord.Colour.red(),
        )
        await log_channel.send(
            embed=embed,
            file=discord.File(transcript_path),
        )

    if (
        claimed_by is not None
        and not escalated
        and ticket_type in {"assistance", "signalement"}
    ):
        assigned_helper = channel.guild.get_member(claimed_by)
        if assigned_helper is None or not is_helper(assigned_helper):
            assigned_helper = None
    else:
        assigned_helper = None
    if assigned_helper is not None:
        connection.execute(
            """
            INSERT INTO helper_stats (guild_id, user_id, resolved_tickets, points)
            VALUES (?, ?, 1, 1)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                resolved_tickets = resolved_tickets + 1,
                points = points + 1
            """,
            (channel.guild.id, assigned_helper.id),
        )

    connection.execute(
        """
        UPDATE tickets
        SET status = 'closed', closed_by = ?, closed_at = ?
        WHERE channel_id = ?
        """,
        (interaction.user.id, int(time.time()), channel.id),
    )
    connection.commit()
    await update_helper_leaderboard(channel.guild)
    await channel.delete(reason=f"Ticket #{ticket_id} fermé par {interaction.user}")


class TicketCloseConfirmationView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if isinstance(interaction.channel, discord.TextChannel):
            await close_ticket(interaction, interaction.channel)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            content="Fermeture annulée.", view=None
        )


class TicketControlView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Prendre en charge",
        emoji="🙋",
        style=discord.ButtonStyle.primary,
        custom_id="radarok:ticket:claim",
    )
    async def claim(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if (
            not isinstance(interaction.user, discord.Member)
            or (
                not is_ticket_staff(interaction.user)
                and not is_helper(interaction.user)
            )
            or not isinstance(interaction.channel, discord.TextChannel)
        ):
            await interaction.response.send_message(
                "Cette action est réservée au staff.", ephemeral=True
            )
            return
        connection = require_database()
        row = connection.execute(
            """
            SELECT id, user_id, claimed_by, ticket_type, escalated FROM tickets
            WHERE channel_id = ? AND status = 'open'
            """,
            (interaction.channel.id,),
        ).fetchone()
        if row is None:
            await interaction.response.send_message(
                "Ce ticket n'est plus actif.", ephemeral=True
            )
            return
        ticket_id, opener_id, claimed_by, ticket_type, escalated = row
        if claimed_by is not None and claimed_by != interaction.user.id:
            await interaction.response.send_message(
                f"Ce ticket est déjà pris en charge par <@{claimed_by}>.",
                ephemeral=True,
            )
            return
        if claimed_by == interaction.user.id:
            await interaction.response.send_message(
                "Tu as déjà pris ce ticket en charge.", ephemeral=True
            )
            return
        if is_helper(interaction.user) and not is_ticket_staff(interaction.user):
            if ticket_type not in {"assistance", "signalement"} or escalated:
                await interaction.response.send_message(
                    "Ce ticket est réservé au staff supérieur.", ephemeral=True
                )
                return
        connection.execute(
            """
            UPDATE tickets SET claimed_by = ?, claimed_at = ?
            WHERE channel_id = ?
            """,
            (interaction.user.id, int(time.time()), interaction.channel.id),
        )
        connection.commit()
        helper_role = discord.utils.get(
            interaction.guild.roles, name=HELPER_ROLE_NAME
        )
        if (
            helper_role is not None
            and is_helper(interaction.user)
            and not is_ticket_staff(interaction.user)
        ):
            await interaction.channel.set_permissions(
                helper_role,
                view_channel=False,
                reason=f"Ticket claim par {interaction.user}",
            )
            await interaction.channel.set_permissions(
                interaction.user,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                reason="Helper assigné au ticket",
            )
        await interaction.response.send_message(
            f"🙋 Ticket pris en charge par {interaction.user.mention}."
        )
        log_channel = discord.utils.get(
            interaction.guild.text_channels, name=TICKET_LOG_CHANNEL_NAME
        )
        if log_channel is not None:
            claimed_at = datetime.now(timezone.utc)
            claimed_timestamp = int(claimed_at.timestamp())
            embed = discord.Embed(
                title=f"🙋 Ticket #{ticket_id} pris en charge",
                colour=discord.Colour.blurple(),
                timestamp=claimed_at,
            )
            embed.add_field(
                name="Ticket",
                value=(
                    f"{interaction.channel.mention}\n"
                    f"Type : **{ticket_type.replace('-', ' ').title()}**"
                ),
                inline=True,
            )
            embed.add_field(
                name="Membre concerné",
                value=f"<@{opener_id}>\n`{opener_id}`",
                inline=True,
            )
            embed.add_field(
                name="Pris en charge par",
                value=(
                    f"{interaction.user.mention}\n"
                    f"`{interaction.user.id}`"
                ),
                inline=True,
            )
            embed.add_field(
                name="Date et heure exactes",
                value=(
                    f"<t:{claimed_timestamp}:F>\n"
                    f"(<t:{claimed_timestamp}:R>)"
                ),
                inline=False,
            )
            try:
                await log_channel.send(embed=embed)
            except discord.HTTPException:
                logging.exception(
                    "Impossible de journaliser le claim du ticket %s",
                    ticket_id,
                )

    @discord.ui.button(
        label="Faire remonter",
        emoji="⬆️",
        style=discord.ButtonStyle.secondary,
        custom_id="radarok:ticket:escalate",
    )
    async def escalate(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if (
            not isinstance(interaction.user, discord.Member)
            or not isinstance(interaction.channel, discord.TextChannel)
            or (not is_helper(interaction.user) and not is_ticket_staff(interaction.user))
        ):
            await interaction.response.send_message(
                "Cette action est réservée à l'équipe.", ephemeral=True
            )
            return
        row = require_database().execute(
            """
            SELECT id, user_id, claimed_by, ticket_type FROM tickets
            WHERE channel_id = ? AND status = 'open'
            """,
            (interaction.channel.id,),
        ).fetchone()
        if row is None or (
            row[2] not in {None, interaction.user.id}
            and not is_ticket_staff(interaction.user)
        ):
            await interaction.response.send_message(
                "Tu ne peux pas faire remonter ce ticket.", ephemeral=True
            )
            return
        superior_role, escalated_category = await ensure_superior_staff_area(
            interaction.guild
        )
        if superior_role is None or escalated_category is None:
            await interaction.response.send_message(
                "Impossible de préparer l'espace du staff supérieur. Vérifie les "
                "permissions du bot.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Le ticket a été transmis au staff supérieur.", ephemeral=True
        )
        try:
            await secure_escalated_ticket(
                interaction.channel,
                row[1],
                superior_role,
                escalated_category,
            )
        except discord.HTTPException:
            logging.exception(
                "Impossible de déplacer le ticket %s vers le Staff supérieur",
                row[0],
            )
            await interaction.followup.send(
                "Discord a refusé le déplacement du ticket.", ephemeral=True
            )
            return
        require_database().execute(
            """
            UPDATE tickets SET escalated = 1, claimed_by = NULL,
                               claimed_at = NULL
            WHERE channel_id = ?
            """,
            (interaction.channel.id,),
        )
        require_database().commit()
        await interaction.channel.send(
            f"⬆️ {superior_role.mention} • Le ticket **#{row[0]}** "
            f"({row[3]}) a été remonté par {interaction.user.mention}.\n"
            "Seul le membre concerné et le Staff supérieur peuvent désormais y accéder."
        )
        log_channel = discord.utils.get(
            interaction.guild.text_channels, name=TICKET_LOG_CHANNEL_NAME
        )
        if log_channel is not None:
            escalated_at = int(time.time())
            embed = discord.Embed(
                title=f"⬆️ Ticket #{row[0]} remonté",
                colour=discord.Colour.purple(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(
                name="Ticket",
                value=f"{interaction.channel.mention}\nType : **{row[3]}**",
                inline=True,
            )
            embed.add_field(
                name="Remonté par",
                value=f"{interaction.user.mention}\n`{interaction.user.id}`",
                inline=True,
            )
            embed.add_field(
                name="Accès",
                value=superior_role.mention,
                inline=True,
            )
            embed.add_field(
                name="Date et heure exactes",
                value=f"<t:{escalated_at}:F>\n(<t:{escalated_at}:R>)",
                inline=False,
            )
            try:
                await log_channel.send(embed=embed)
            except discord.HTTPException:
                logging.exception(
                    "Impossible de journaliser la remontée du ticket %s", row[0]
                )

    @discord.ui.button(
        label="Fermer",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="radarok:ticket:close",
    )
    async def close(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.send_message(
            "Confirmer la fermeture définitive de ce ticket ?",
            view=TicketCloseConfirmationView(),
            ephemeral=True,
        )


def parse_duration(value: str) -> int | None:
    cleaned = value.lower().replace(" ", "")
    matches = re.findall(r"(\d+)([smhdw])", cleaned)
    if not matches or "".join(f"{number}{unit}" for number, unit in matches) != cleaned:
        return None
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    seconds = sum(int(number) * multipliers[unit] for number, unit in matches)
    return seconds if 10 <= seconds <= 31_536_000 else None


def format_remaining(seconds: int) -> str:
    if seconds <= 0:
        return "Terminé"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} j")
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if secs or not parts:
        parts.append(f"{secs} s")
    return " ".join(parts)


def giveaway_chance(member: discord.Member) -> tuple[float, float, float]:
    invite_count = get_invite_count(member.guild.id, member.id)
    invite_bonus = next(
        (
            bonus
            for required, _, bonus in INVITE_ROLE_TIERS
            if invite_count >= required
        ),
        0.0,
    )
    booster_bonus = 1.0 if member.premium_since is not None else 0.0
    return 1.0 + invite_bonus + booster_bonus, invite_bonus, booster_bonus


def get_giveaway(message_id: int) -> tuple | None:
    return require_database().execute(
        """
        SELECT guild_id, channel_id, host_id, prize, winners_count, ends_at, status
        FROM giveaways WHERE message_id = ?
        """,
        (message_id,),
    ).fetchone()


async def select_giveaway_winners(
    guild: discord.Guild, message_id: int, winners_count: int
) -> list[discord.Member]:
    rows = require_database().execute(
        "SELECT user_id FROM giveaway_entries WHERE message_id = ?",
        (message_id,),
    ).fetchall()
    pool = [
        member
        for (user_id,) in rows
        if (member := guild.get_member(user_id)) is not None and not member.bot
    ]
    winners: list[discord.Member] = []
    while pool and len(winners) < winners_count:
        weights = [giveaway_chance(member)[0] for member in pool]
        selected_index = random.choices(
            range(len(pool)), weights=weights, k=1
        )[0]
        winners.append(pool.pop(selected_index))
    return winners


async def finish_giveaway(message_id: int, *, reroll: bool = False) -> list[discord.Member]:
    giveaway = get_giveaway(message_id)
    if giveaway is None:
        return []
    guild_id, channel_id, _, prize, winners_count, ends_at, status = giveaway
    guild = bot.get_guild(guild_id)
    if guild is None:
        return []
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return []
    winners = await select_giveaway_winners(guild, message_id, winners_count)
    mentions = ", ".join(winner.mention for winner in winners)
    if reroll:
        await channel.send(
            f"🎲 **Nouveau tirage pour {prize}** : "
            f"{mentions or 'aucun participant valide'}"
        )
        return winners

    require_database().execute(
        "UPDATE giveaways SET status = 'ended' WHERE message_id = ?",
        (message_id,),
    )
    require_database().commit()
    try:
        message = await channel.fetch_message(message_id)
        embed = message.embeds[0] if message.embeds else discord.Embed()
        embed.colour = discord.Colour.dark_grey()
        embed.title = f"🎉 Giveaway terminé • {prize}"
        embed.description = (
            f"Terminé <t:{ends_at}:R>\n"
            f"Gagnant(s) : {mentions or '**Aucun participant valide**'}"
        )
        await message.edit(embed=embed, view=GiveawayView())
    except discord.HTTPException:
        logging.exception("Impossible de modifier le giveaway %s", message_id)
    await channel.send(
        f"🎉 Félicitations {mentions} ! Vous remportez **{prize}**."
        if winners
        else f"Le giveaway **{prize}** est terminé sans participant valide."
    )
    return winners


class GiveawayView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Participer",
        emoji="🎉",
        style=discord.ButtonStyle.success,
        custom_id="radarok:giveaway:join",
    )
    async def participate(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if (
            interaction.message is None
            or interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
        ):
            return
        giveaway = get_giveaway(interaction.message.id)
        if giveaway is None or giveaway[6] != "active" or giveaway[5] <= int(time.time()):
            await interaction.response.send_message(
                "Ce giveaway est terminé.", ephemeral=True
            )
            return
        connection = require_database()
        existing = connection.execute(
            """
            SELECT 1 FROM giveaway_entries
            WHERE message_id = ? AND user_id = ?
            """,
            (interaction.message.id, interaction.user.id),
        ).fetchone()
        if existing:
            connection.execute(
                "DELETE FROM giveaway_entries WHERE message_id = ? AND user_id = ?",
                (interaction.message.id, interaction.user.id),
            )
            connection.commit()
            await interaction.response.send_message(
                "Ta participation a été retirée.", ephemeral=True
            )
            return
        connection.execute(
            """
            INSERT INTO giveaway_entries (message_id, user_id, joined_at)
            VALUES (?, ?, ?)
            """,
            (interaction.message.id, interaction.user.id, int(time.time())),
        )
        connection.commit()
        chance, _, _ = giveaway_chance(interaction.user)
        await interaction.response.send_message(
            f"Participation enregistrée avec **{chance:g} chance(s)**.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Participants",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        custom_id="radarok:giveaway:participants",
    )
    async def participants(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if interaction.message is None or interaction.guild is None:
            return
        rows = require_database().execute(
            "SELECT user_id FROM giveaway_entries WHERE message_id = ?",
            (interaction.message.id,),
        ).fetchall()
        names = [
            member.mention
            for (user_id,) in rows[:40]
            if (member := interaction.guild.get_member(user_id)) is not None
        ]
        suffix = f"\n… et {len(rows) - 40} autre(s)." if len(rows) > 40 else ""
        await interaction.response.send_message(
            f"**{len(rows)} participant(s)**\n"
            f"{', '.join(names) if names else 'Aucun participant.'}{suffix}",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Durée",
        emoji="⏳",
        style=discord.ButtonStyle.primary,
        custom_id="radarok:giveaway:duration",
    )
    async def duration(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if interaction.message is None:
            return
        giveaway = get_giveaway(interaction.message.id)
        if giveaway is None:
            await interaction.response.send_message(
                "Giveaway introuvable.", ephemeral=True
            )
            return
        remaining = max(giveaway[5] - int(time.time()), 0)
        await interaction.response.send_message(
            f"Temps restant exact : **{format_remaining(remaining)}**.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Mes chances",
        emoji="🍀",
        style=discord.ButtonStyle.primary,
        custom_id="radarok:giveaway:chance",
    )
    async def chances(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            return
        total, invite_bonus, booster_bonus = giveaway_chance(interaction.user)
        await interaction.response.send_message(
            f"Chance de base : **1**\n"
            f"Bonus invitations : **+{invite_bonus:g}**\n"
            f"Bonus Booster : **+{booster_bonus:g}**\n"
            f"Total : **{total:g} chance(s)**",
            ephemeral=True,
        )


async def ensure_roles(
    guild: discord.Guild, reason: str
) -> tuple[dict[str, discord.Role], int]:
    roles: dict[str, discord.Role] = {}
    created_count = 0

    for spec in ROLE_SPECS:
        role = discord.utils.get(guild.roles, name=spec.name)
        if role is None:
            role = await guild.create_role(
                name=spec.name,
                colour=discord.Colour(spec.colour),
                permissions=spec.permissions,
                hoist=spec.hoist,
                mentionable=False,
                reason=reason,
            )
            created_count += 1
        roles[spec.name] = role

    radarok_role = roles["👑・Radarok"]
    owner = guild.owner
    if owner is None:
        owner = await guild.fetch_member(guild.owner_id)
    if radarok_role not in owner.roles:
        await owner.add_roles(radarok_role, reason=reason)

    return roles, created_count


async def ensure_helper_role(guild: discord.Guild) -> discord.Role | None:
    role = discord.utils.get(guild.roles, name=HELPER_ROLE_NAME)
    if role is not None:
        if role.permissions != discord.Permissions.none():
            try:
                await role.edit(
                    permissions=discord.Permissions.none(),
                    reason="Sécurisation du rôle Helper",
                )
            except discord.HTTPException:
                logging.exception("Impossible de sécuriser le rôle Helper")
        return role
    legacy_role = discord.utils.get(
        guild.roles, name="🆘・Helper Blox Fruits"
    )
    try:
        if legacy_role is not None:
            await legacy_role.edit(
                name=HELPER_ROLE_NAME,
                permissions=discord.Permissions.none(),
                reason="Migration du rôle Helper",
            )
            return legacy_role
        return await guild.create_role(
            name=HELPER_ROLE_NAME,
            colour=discord.Colour(0x27AE60),
            permissions=discord.Permissions.none(),
            hoist=True,
            mentionable=False,
            reason="Création automatique du rôle Helper",
        )
    except discord.HTTPException:
        logging.exception("Impossible de créer ou migrer le rôle Helper")
        return None


async def ensure_superior_staff_area(
    guild: discord.Guild,
) -> tuple[discord.Role | None, discord.CategoryChannel | None]:
    role = discord.utils.get(guild.roles, name=SUPERIOR_STAFF_ROLE_NAME)
    try:
        if role is None:
            role = await guild.create_role(
                name=SUPERIOR_STAFF_ROLE_NAME,
                colour=discord.Colour(0x8E44AD),
                permissions=discord.Permissions.none(),
                hoist=True,
                mentionable=False,
                reason="Création automatique du rôle Staff supérieur",
            )
        elif role.permissions != discord.Permissions.none():
            await role.edit(
                permissions=discord.Permissions.none(),
                reason="Sécurisation du rôle Staff supérieur",
            )
    except discord.HTTPException:
        logging.exception("Impossible de créer le rôle Staff supérieur")
        return None, None

    members_to_promote: set[discord.Member] = set()
    if guild.owner is not None:
        members_to_promote.add(guild.owner)
    for source_name in SUPERIOR_SOURCE_ROLE_NAMES:
        source_role = discord.utils.get(guild.roles, name=source_name)
        if source_role is not None:
            members_to_promote.update(source_role.members)
    for member in members_to_promote:
        if role not in member.roles:
            try:
                await member.add_roles(
                    role,
                    reason="Accès automatique aux tickets remontés",
                )
            except discord.HTTPException:
                logging.exception(
                    "Impossible d'attribuer Staff supérieur à %s", member.id
                )

    bot_member = guild.me
    if bot_member is None:
        return role, None
    overwrites: dict[
        discord.Role | discord.Member, discord.PermissionOverwrite
    ] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        ),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
        ),
    }
    category = discord.utils.get(
        guild.categories, name=ESCALATED_TICKET_CATEGORY_NAME
    )
    try:
        if category is None:
            category = await guild.create_category(
                ESCALATED_TICKET_CATEGORY_NAME,
                overwrites=overwrites,
                reason="Création automatique des tickets remontés",
            )
        else:
            await category.edit(
                overwrites=overwrites,
                reason="Sécurisation des tickets remontés",
            )
        open_ticket_category = discord.utils.get(
            guild.categories, name=TICKET_CATEGORY_NAME
        )
        if (
            open_ticket_category is not None
            and category.position != open_ticket_category.position + 1
        ):
            await category.edit(
                position=open_ticket_category.position + 1,
                reason="Placement des tickets remontés",
            )
    except discord.HTTPException:
        logging.exception(
            "Impossible de créer ou sécuriser la catégorie Staff supérieur"
        )
        return role, None
    return role, category


async def secure_escalated_ticket(
    channel: discord.TextChannel,
    opener_id: int,
    superior_role: discord.Role,
    category: discord.CategoryChannel,
) -> None:
    guild = channel.guild
    opener = guild.get_member(opener_id)
    bot_member = guild.me
    overwrites: dict[
        discord.Role | discord.Member, discord.PermissionOverwrite
    ] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        superior_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        ),
    }
    if bot_member is not None:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            manage_channels=True,
            manage_messages=True,
        )
    if opener is not None:
        overwrites[opener] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )
    await channel.edit(
        category=category,
        overwrites=overwrites,
        reason="Ticket déplacé vers le Staff supérieur",
    )


async def reconcile_helper_ticket_permissions(
    guild: discord.Guild, helper_role: discord.Role
) -> None:
    connection = require_database()
    rows = connection.execute(
        """
        SELECT channel_id, user_id, ticket_type, claimed_by, escalated
        FROM tickets WHERE guild_id = ? AND status = 'open'
        """,
        (guild.id,),
    ).fetchall()
    database_changed = False
    for channel_id, opener_id, ticket_type, claimed_by, escalated in rows:
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            connection.execute(
                "UPDATE tickets SET status = 'closed' WHERE channel_id = ?",
                (channel_id,),
            )
            database_changed = True
            continue
        helper_ticket = ticket_type in {"assistance", "signalement"} and not escalated
        assigned_helper = (
            guild.get_member(claimed_by) if claimed_by is not None else None
        )
        valid_assignment = (
            assigned_helper is not None and is_helper(assigned_helper)
        )
        try:
            if helper_ticket and valid_assignment:
                await channel.set_permissions(
                    helper_role,
                    view_channel=False,
                    reason="Restauration du claim exclusif Helper",
                )
                await channel.set_permissions(
                    assigned_helper,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    reason="Restauration du Helper assigné",
                )
            elif helper_ticket:
                if claimed_by is not None:
                    connection.execute(
                        """
                        UPDATE tickets SET claimed_by = NULL
                        WHERE channel_id = ?
                        """,
                        (channel_id,),
                    )
                    database_changed = True
                    former_helper = guild.get_member(claimed_by)
                    if former_helper is not None and former_helper.id != opener_id:
                        await channel.set_permissions(
                            former_helper,
                            view_channel=False,
                            reason="Ancien Helper retiré du ticket",
                        )
                await channel.set_permissions(
                    helper_role,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    reason="Ticket disponible pour les Helpers",
                )
            else:
                await channel.set_permissions(
                    helper_role,
                    view_channel=False,
                    reason="Type de ticket réservé au staff supérieur",
                )
                if escalated:
                    superior_role = discord.utils.get(
                        guild.roles, name=SUPERIOR_STAFF_ROLE_NAME
                    )
                    escalated_category = discord.utils.get(
                        guild.categories, name=ESCALATED_TICKET_CATEGORY_NAME
                    )
                    if superior_role is not None and escalated_category is not None:
                        await secure_escalated_ticket(
                            channel,
                            opener_id,
                            superior_role,
                            escalated_category,
                        )
        except discord.HTTPException:
            logging.exception(
                "Impossible de réparer les permissions Helper du ticket %s",
                channel_id,
            )
    if database_changed:
        connection.commit()


def staff_overwrites(
    guild: discord.Guild, roles: dict[str, discord.Role]
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[
        discord.Role | discord.Member, discord.PermissionOverwrite
    ] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            connect=True,
            manage_channels=True,
        ),
    }
    for role_name in (
        "👑・Radarok",
        "⚙️・Responsable",
        "🛡️・Administrateur",
        "🔨・Modérateur",
        "🧪・Modérateur en test",
    ):
        overwrites[roles[role_name]] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            connect=True,
            speak=True,
        )
    return overwrites


def member_overwrites(
    guild: discord.Guild, roles: dict[str, discord.Role]
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[
        discord.Role | discord.Member, discord.PermissionOverwrite
    ] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        roles[MEMBER_ROLE_NAME]: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            connect=True,
            manage_channels=True,
        ),
    }
    for role_name in STAFF_ROLE_NAMES:
        overwrites[roles[role_name]] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            connect=True,
            speak=True,
        )
    return overwrites


def verification_overwrites(
    guild: discord.Guild, roles: dict[str, discord.Role]
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    return {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            add_reactions=False,
        ),
        roles[UNVERIFIED_ROLE_NAME]: discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
    }


def staff_voice_overwrites(
    guild: discord.Guild, roles: dict[str, discord.Role]
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[
        discord.Role | discord.Member, discord.PermissionOverwrite
    ] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        roles[MEMBER_ROLE_NAME]: discord.PermissionOverwrite(
            view_channel=True,
            connect=False,
            speak=False,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True,
        ),
    }
    for role_name in STAFF_ROLE_NAMES:
        overwrites[roles[role_name]] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
            move_members=True,
        )
    return overwrites


def server_stats_overwrites(
    guild: discord.Guild, roles: dict[str, discord.Role]
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[
        discord.Role | discord.Member, discord.PermissionOverwrite
    ] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        roles[MEMBER_ROLE_NAME]: discord.PermissionOverwrite(
            view_channel=True,
            connect=False,
            speak=False,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=False,
            speak=False,
            manage_channels=True,
        ),
    }
    for role_name in STAFF_ROLE_NAMES:
        overwrites[roles[role_name]] = discord.PermissionOverwrite(
            view_channel=True,
            connect=False,
            speak=False,
        )
    return overwrites


def find_category(guild: discord.Guild, name: str) -> discord.CategoryChannel | None:
    return discord.utils.get(guild.categories, name=name)


def find_channel(
    guild: discord.Guild,
    name: str,
    category: discord.CategoryChannel | None,
    kind: ChannelKind,
) -> discord.abc.GuildChannel | None:
    expected_type = {
        "text": discord.ChannelType.text,
        "voice": discord.ChannelType.voice,
        "stage": discord.ChannelType.stage_voice,
    }[kind]
    return discord.utils.find(
        lambda channel: (
            channel.name == name
            and channel.category == category
            and channel.type == expected_type
        ),
        guild.channels,
    )


async def ensure_channel(
    guild: discord.Guild,
    spec: ChannelSpec,
    category: discord.CategoryChannel | None,
    reason: str,
    *,
    reuse_existing: bool = True,
) -> tuple[discord.abc.GuildChannel, bool, bool]:
    existing = (
        find_channel(guild, spec.name, category, spec.kind)
        if reuse_existing
        else None
    )
    used_stage_fallback = False
    if reuse_existing and existing is None and spec.kind == "stage":
        # Reconnaît aussi le salon vocal créé lors d'un précédent repli afin
        # qu'une seconde exécution de /setup ne crée pas de doublon.
        existing = find_channel(guild, spec.name, category, "voice")
        used_stage_fallback = existing is not None
    if existing is not None:
        if isinstance(existing, discord.VoiceChannel) and existing.user_limit != spec.user_limit:
            await existing.edit(user_limit=spec.user_limit, reason=reason)
        return existing, False, used_stage_fallback

    if spec.kind == "text":
        channel = await guild.create_text_channel(
            spec.name, category=category, reason=reason
        )
    elif spec.kind == "voice":
        channel = await guild.create_voice_channel(
            spec.name,
            category=category,
            user_limit=spec.user_limit,
            reason=reason,
        )
    else:
        try:
            channel = await guild.create_stage_channel(
                spec.name, category=category, reason=reason
            )
        except discord.HTTPException as error:
            # 50024 arrive notamment lorsque les salons de conférence ne sont
            # pas disponibles sur le serveur (mode Communauté désactivé).
            if error.code != 50024:
                raise
            channel = await guild.create_voice_channel(
                spec.name, category=category, reason=reason
            )
            return channel, True, True
    return channel, True, False


async def delete_all_channels(guild: discord.Guild, reason: str) -> tuple[int, int]:
    """Supprime les salons et catégories, sauf les identifiants protégés."""
    channels = list(guild.channels)
    regular_channels = [
        channel
        for channel in channels
        if not isinstance(channel, discord.CategoryChannel)
        and channel.id not in PRESERVED_SETUP_CHANNEL_IDS
    ]
    categories = [
        channel
        for channel in channels
        if isinstance(channel, discord.CategoryChannel)
        and channel.id not in PRESERVED_SETUP_CHANNEL_IDS
    ]

    for channel in regular_channels:
        await channel.delete(reason=reason)
    for category in categories:
        await category.delete(reason=reason)

    return len(regular_channels), len(categories)


async def update_server_stats(guild: discord.Guild) -> None:
    category = discord.utils.get(
        guild.categories, name=SERVER_STATS_CATEGORY_NAME
    )
    if category is None:
        return

    total_members = guild.member_count or len(guild.members)
    bot_count = sum(member.bot for member in guild.members)
    human_count = max(total_members - bot_count, 0)
    boost_count = guild.premium_subscription_count or 0
    desired_names = {
        "👥・": stylize_channel_name(f"👥・Membres : {total_members}"),
        "✅・": stylize_channel_name(f"✅・Humains : {human_count}"),
        "🤖・": stylize_channel_name(f"🤖・Bots : {bot_count}"),
        "💎・": stylize_channel_name(f"💎・Boosts : {boost_count}"),
    }
    for channel in category.voice_channels:
        desired_name = next(
            (
                name
                for prefix, name in desired_names.items()
                if channel.name.startswith(prefix)
            ),
            None,
        )
        if desired_name is not None and channel.name != desired_name:
            try:
                await channel.edit(
                    name=desired_name,
                    reason="Actualisation automatique des statistiques du serveur",
                )
            except discord.HTTPException:
                logging.exception(
                    "Impossible d'actualiser le compteur %s", channel.id
                )


def get_invite_count(guild_id: int, user_id: int) -> int:
    row = require_database().execute(
        """
        SELECT invite_count FROM invite_stats
        WHERE guild_id = ? AND user_id = ?
        """,
        (guild_id, user_id),
    ).fetchone()
    return int(row[0]) if row is not None else 0


async def update_invite_role(member: discord.Member) -> None:
    count = get_invite_count(member.guild.id, member.id)
    tier_names = {role_name for _, role_name, _ in INVITE_ROLE_TIERS}
    target_name = next(
        (
            role_name
            for required, role_name, _ in INVITE_ROLE_TIERS
            if count >= required
        ),
        None,
    )
    target_role = (
        discord.utils.get(member.guild.roles, name=target_name)
        if target_name is not None
        else None
    )
    roles_to_remove = [
        role
        for role in member.roles
        if role.name in tier_names and role != target_role
    ]
    try:
        if roles_to_remove:
            await member.remove_roles(
                *roles_to_remove,
                reason=f"Mise à jour automatique après {count} invitations",
            )
        if target_role is not None and target_role not in member.roles:
            await member.add_roles(
                target_role,
                reason=f"Palier automatique atteint avec {count} invitations",
            )
    except discord.Forbidden:
        logging.warning(
            "Impossible de mettre à jour le rôle d'invitation de %s", member
        )


async def refresh_invite_cache(guild: discord.Guild) -> list[discord.Invite]:
    try:
        invites = await guild.invites()
    except discord.Forbidden:
        logging.warning(
            "Permission Gérer le serveur requise pour suivre les invitations sur %s",
            guild.id,
        )
        return []
    invite_cache[guild.id] = {
        invite.code: invite.uses or 0 for invite in invites
    }
    return invites


async def restore_invite_roles(guild: discord.Guild) -> None:
    rows = require_database().execute(
        "SELECT user_id FROM invite_stats WHERE guild_id = ? AND invite_count > 0",
        (guild.id,),
    ).fetchall()
    for (user_id,) in rows:
        member = guild.get_member(user_id)
        if member is not None:
            await update_invite_role(member)


async def process_member_invite(member: discord.Member) -> None:
    previous = invite_cache.get(member.guild.id, {})
    try:
        current_invites = await member.guild.invites()
    except discord.Forbidden:
        return
    used_invite = next(
        (
            invite
            for invite in current_invites
            if (invite.uses or 0) > previous.get(invite.code, 0)
        ),
        None,
    )
    invite_cache[member.guild.id] = {
        invite.code: invite.uses or 0 for invite in current_invites
    }
    if used_invite is None or used_invite.inviter is None:
        return

    inviter_id = used_invite.inviter.id
    connection = require_database()
    connection.execute(
        """
        INSERT INTO invite_stats (guild_id, user_id, invite_count)
        VALUES (?, ?, 1)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            invite_count = invite_count + 1
        """,
        (member.guild.id, inviter_id),
    )
    connection.commit()
    inviter = member.guild.get_member(inviter_id)
    if inviter is not None:
        await update_invite_role(inviter)


def build_voice_help_embed() -> discord.Embed:
    return discord.Embed(
        title="⚓ Gestion de ton équipage vocal",
        description=(
            f"Rejoins **{TEMP_VOICE_TRIGGER_NAME}** pour créer automatiquement "
            f"un salon nommé `{TEMP_VOICE_PREFIX}ton pseudo`.\n\n"
            "`/vocal-limite` — choisir le nombre maximal de membres\n"
            "`/vocal-prive` — verrouiller ou rouvrir le vocal\n"
            "`/vocal-inviter` — autoriser un membre dans un vocal privé\n"
            "`/vocal-expulser` — déconnecter un membre du vocal\n\n"
            "Le salon est supprimé automatiquement lorsqu'il devient vide."
        ),
        colour=discord.Colour.blue(),
    )


def owned_temporary_channel(
    interaction: discord.Interaction,
) -> discord.VoiceChannel | None:
    if not isinstance(interaction.user, discord.Member):
        return None
    voice = interaction.user.voice
    if voice is None or not isinstance(voice.channel, discord.VoiceChannel):
        return None
    channel = voice.channel
    if (
        channel.name == TEMP_VOICE_TRIGGER_NAME
        or channel.category is None
        or channel.category.name != TEMP_VOICE_CATEGORY_NAME
    ):
        return None
    overwrite = channel.overwrites_for(interaction.user)
    return channel if overwrite.manage_channels is True else None


@bot.tree.command(name="vocal-limite", description="Change la limite de ton vocal.")
@app_commands.describe(nombre="Nombre maximal de membres, ou 0 pour aucune limite")
async def vocal_limit(interaction: discord.Interaction, nombre: int) -> None:
    channel = owned_temporary_channel(interaction)
    if channel is None:
        await interaction.response.send_message(
            "Tu dois être dans le vocal temporaire dont tu es propriétaire.",
            ephemeral=True,
        )
        return
    if not 0 <= nombre <= 99:
        await interaction.response.send_message(
            "La limite doit être comprise entre 0 et 99.", ephemeral=True
        )
        return

    await channel.edit(
        user_limit=nombre,
        reason=f"Limite choisie par le propriétaire {interaction.user}",
    )
    label = "illimitée" if nombre == 0 else f"fixée à **{nombre}**"
    await interaction.response.send_message(
        f"La capacité du vocal est maintenant {label}.", ephemeral=True
    )


@bot.tree.command(
    name="vocal-prive",
    description="Rend ton vocal privé ou de nouveau public.",
)
@app_commands.describe(active="Oui pour verrouiller le vocal, non pour le rouvrir")
async def vocal_private(interaction: discord.Interaction, active: bool) -> None:
    channel = owned_temporary_channel(interaction)
    if channel is None or interaction.guild is None:
        await interaction.response.send_message(
            "Tu dois être dans le vocal temporaire dont tu es propriétaire.",
            ephemeral=True,
        )
        return

    member_role = discord.utils.get(
        interaction.guild.roles, name=MEMBER_ROLE_NAME
    )
    if member_role is None:
        await interaction.response.send_message(
            "Le rôle Membre est introuvable.", ephemeral=True
        )
        return
    await channel.set_permissions(
        member_role,
        view_channel=True,
        connect=not active,
        reason=f"Mode privé modifié par {interaction.user}",
    )
    state = "privé 🔒" if active else "public 🔓"
    await interaction.response.send_message(
        f"Ton vocal est maintenant **{state}**.", ephemeral=True
    )


@bot.tree.command(
    name="vocal-inviter",
    description="Autorise un membre à rejoindre ton vocal privé.",
)
@app_commands.describe(membre="Membre à autoriser dans ton vocal")
async def vocal_invite(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    channel = owned_temporary_channel(interaction)
    if channel is None:
        await interaction.response.send_message(
            "Tu dois être dans le vocal temporaire dont tu es propriétaire.",
            ephemeral=True,
        )
        return

    await channel.set_permissions(
        membre,
        view_channel=True,
        connect=True,
        reason=f"Invitation par le propriétaire {interaction.user}",
    )
    invite_sent = False
    invite_view = discord.ui.View(timeout=3600)
    invite_view.add_item(
        discord.ui.Button(
            label="Rejoindre le vocal",
            emoji="🔊",
            style=discord.ButtonStyle.link,
            url=channel.jump_url,
        )
    )
    invite_embed = discord.Embed(
        title="⚓ Invitation dans un équipage vocal",
        description=(
            f"**{interaction.user.display_name}** t'invite à rejoindre "
            f"**{channel.name}** sur **{interaction.guild.name}**.\n\n"
            "Clique sur le bouton ci-dessous pour ouvrir directement le salon vocal."
        ),
        colour=discord.Colour.blue(),
    )
    try:
        await membre.send(embed=invite_embed, view=invite_view)
        invite_sent = True
    except discord.HTTPException:
        logging.info(
            "Message privé d'invitation vocale impossible pour %s", membre.id
        )

    confirmation = (
        f"{membre.mention} peut maintenant rejoindre {channel.mention}."
    )
    if invite_sent:
        confirmation += " Une invitation avec un lien direct lui a été envoyée en privé."
    else:
        confirmation += (
            " Je n'ai pas pu lui envoyer de message privé, probablement parce que "
            "ses messages privés sont fermés."
        )
    await interaction.response.send_message(confirmation, ephemeral=True)


@bot.tree.command(
    name="vocal-expulser",
    description="Expulse un membre de ton vocal.",
)
@app_commands.describe(membre="Membre à déconnecter de ton vocal")
async def vocal_kick(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    channel = owned_temporary_channel(interaction)
    if channel is None:
        await interaction.response.send_message(
            "Tu dois être dans le vocal temporaire dont tu es propriétaire.",
            ephemeral=True,
        )
        return
    if membre == interaction.user:
        await interaction.response.send_message(
            "Tu ne peux pas t'expulser toi-même.", ephemeral=True
        )
        return
    if membre.voice is None or membre.voice.channel != channel:
        await interaction.response.send_message(
            "Ce membre n'est pas dans ton vocal.", ephemeral=True
        )
        return

    await membre.move_to(
        None, reason=f"Expulsé du vocal temporaire par {interaction.user}"
    )
    await interaction.response.send_message(
        f"{membre.mention} a été expulsé du vocal.", ephemeral=True
    )


class PlayerCVModal(discord.ui.Modal):
    def __init__(self) -> None:
        super().__init__(title="📄 Créer ou modifier mon CV", timeout=600)
        self.roblox_name = discord.ui.TextInput(
            label="Pseudo Roblox",
            placeholder="Ton pseudo exact sur Roblox",
            max_length=50,
        )
        self.level_and_sea = discord.ui.TextInput(
            label="Niveau et mer actuelle",
            placeholder="Exemple : niveau 2550, troisième mer",
            max_length=100,
        )
        self.profile = discord.ui.TextInput(
            label="Fruit, race, V4, prime et activités",
            placeholder="Présente ton profil et ce que tu aimes faire",
            style=discord.TextStyle.paragraph,
            max_length=600,
        )
        self.availability = discord.ui.TextInput(
            label="Disponibilités, plateforme et région",
            placeholder="Exemple : soir, PC, Europe, micro oui",
            max_length=200,
        )
        self.looking_for = discord.ui.TextInput(
            label="Ce que tu recherches",
            placeholder="Décris l'équipage que tu souhaites rejoindre",
            style=discord.TextStyle.paragraph,
            max_length=500,
        )
        for item in (
            self.roblox_name,
            self.level_and_sea,
            self.profile,
            self.availability,
            self.looking_for,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not isinstance(interaction.channel, discord.TextChannel)
            or interaction.channel.name != PLAYER_CV_CHANNEL_NAME
        ):
            await interaction.response.send_message(
                f"Utilise ce formulaire dans `{PLAYER_CV_CHANNEL_NAME}`.",
                ephemeral=True,
            )
            return
        connection = require_database()
        previous = connection.execute(
            """
            SELECT channel_id, message_id FROM player_cvs
            WHERE guild_id = ? AND user_id = ?
            """,
            (interaction.guild.id, interaction.user.id),
        ).fetchone()
        embed = discord.Embed(
            title=f"📄 CV de {interaction.user.display_name}",
            colour=discord.Colour.teal(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(
            name="🎮 Pseudo Roblox", value=str(self.roblox_name), inline=False
        )
        embed.add_field(
            name="🌊 Niveau et progression",
            value=str(self.level_and_sea),
            inline=False,
        )
        embed.add_field(
            name="🍈 Profil Blox Fruits", value=str(self.profile), inline=False
        )
        embed.add_field(
            name="🕒 Disponibilités", value=str(self.availability), inline=False
        )
        embed.add_field(
            name="🔎 Recherche", value=str(self.looking_for), inline=False
        )
        embed.set_footer(
            text=f"ID Discord : {interaction.user.id} • CV requis pour postuler"
        )
        message: discord.Message | None = None
        if previous is not None:
            old_channel = interaction.guild.get_channel(previous[0])
            if isinstance(old_channel, discord.TextChannel):
                try:
                    message = await old_channel.fetch_message(previous[1])
                    await message.edit(embed=embed)
                except discord.HTTPException:
                    message = None
        if message is None:
            message = await interaction.channel.send(embed=embed)
        connection.execute(
            """
            INSERT INTO player_cvs (
                guild_id, user_id, message_id, channel_id, roblox_name,
                level, sea, profile, availability, looking_for, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                message_id = excluded.message_id,
                channel_id = excluded.channel_id,
                roblox_name = excluded.roblox_name,
                level = excluded.level,
                sea = excluded.sea,
                profile = excluded.profile,
                availability = excluded.availability,
                looking_for = excluded.looking_for,
                updated_at = excluded.updated_at
            """,
            (
                interaction.guild.id,
                interaction.user.id,
                message.id,
                interaction.channel.id,
                str(self.roblox_name),
                str(self.level_and_sea),
                "",
                str(self.profile),
                str(self.availability),
                str(self.looking_for),
                int(time.time()),
            ),
        )
        connection.commit()
        await interaction.response.send_message(
            f"✅ Ton CV est publié : {message.jump_url}", ephemeral=True
        )


@bot.tree.command(name="cv-creer", description="Ouvre le formulaire de CV joueur.")
async def cv_create(interaction: discord.Interaction) -> None:
    if (
        not isinstance(interaction.channel, discord.TextChannel)
        or interaction.channel.name != PLAYER_CV_CHANNEL_NAME
    ):
        await interaction.response.send_message(
            f"Cette commande est uniquement disponible dans "
            f"`{PLAYER_CV_CHANNEL_NAME}`.",
            ephemeral=True,
        )
        return
    await interaction.response.send_modal(PlayerCVModal())


def member_level(guild_id: int, user_id: int) -> int:
    row = require_database().execute(
        """
        SELECT message_xp + voice_xp + bonus_xp
        FROM member_stats WHERE guild_id = ? AND user_id = ?
        """,
        (guild_id, user_id),
    ).fetchone()
    return calculate_level(row[0] if row is not None else 0)


async def reset_dynamic_server_data(guild: discord.Guild) -> None:
    connection = require_database()
    captain_role = discord.utils.get(guild.roles, name=CAPTAIN_ROLE_NAME)
    if captain_role is not None and captain_role.members:
        for captain in tuple(captain_role.members):
            try:
                await captain.remove_roles(
                    captain_role, reason="Réinitialisation des équipages"
                )
            except discord.HTTPException:
                pass
    crew_rows = connection.execute(
        "SELECT id, role_id FROM crews WHERE guild_id = ?", (guild.id,)
    ).fetchall()
    for _, role_id in crew_rows:
        role = guild.get_role(role_id)
        if role is not None:
            try:
                await role.delete(reason="Réinitialisation complète du serveur")
            except discord.HTTPException:
                pass
    for crew_id, _ in crew_rows:
        connection.execute("DELETE FROM crew_members WHERE crew_id = ?", (crew_id,))
    connection.execute("DELETE FROM crews WHERE guild_id = ?", (guild.id,))
    connection.execute("DELETE FROM player_cvs WHERE guild_id = ?", (guild.id,))
    connection.execute(
        "DELETE FROM crew_applications WHERE guild_id = ?", (guild.id,)
    )
    connection.execute(
        "DELETE FROM crew_recruitments WHERE guild_id = ?", (guild.id,)
    )
    connection.execute(
        "UPDATE trade_deals SET status = 'closed' WHERE guild_id = ?",
        (guild.id,),
    )
    connection.execute(
        "UPDATE trade_posts SET status = 'closed' WHERE guild_id = ?",
        (guild.id,),
    )
    connection.execute(
        "UPDATE community_events SET status = 'cancelled' WHERE guild_id = ?",
        (guild.id,),
    )
    connection.commit()


async def update_crew_presentation(guild: discord.Guild, crew_id: int) -> None:
    connection = require_database()
    row = connection.execute(
        """
        SELECT owner_id, name, text_channel_id, presentation_message_id,
               vice_captain_id, max_members
        FROM crews WHERE id = ? AND guild_id = ?
        """,
        (crew_id, guild.id),
    ).fetchone()
    if row is None:
        return
    member_count = connection.execute(
        "SELECT COUNT(*) FROM crew_members WHERE crew_id = ?", (crew_id,)
    ).fetchone()[0]
    channel = discord.utils.get(
        guild.text_channels, name=CREW_PRESENTATION_CHANNEL_NAME
    )
    if channel is None:
        return
    private_channel = guild.get_channel(row[2])
    embed = discord.Embed(
        title=f"🏴‍☠️ {row[1]}",
        description=(
            f"**Capitaine :** <@{row[0]}>\n"
            + (
                f"**Vice-capitaine :** <@{row[4]}>\n"
                if row[4] is not None
                else ""
            )
            + f"**Membres :** {member_count}/{row[5]}\n"
            f"**Créé sur Radarok Community**"
        ),
        colour=discord.Colour.gold(),
    )
    if isinstance(private_channel, discord.TextChannel):
        embed.set_footer(text=f"Salon privé : {private_channel.name}")
    message = None
    if row[3] is not None:
        try:
            message = await channel.fetch_message(row[3])
            await message.edit(embed=embed)
        except discord.HTTPException:
            message = None
    if message is None:
        message = await channel.send(embed=embed)
        connection.execute(
            "UPDATE crews SET presentation_message_id = ? WHERE id = ?",
            (message.id, crew_id),
        )
        connection.commit()


def crew_captain_guide_embed(crew_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏴‍☠️ Commandes de capitaine • {crew_name}",
        description=(
            "Conserve ce message : il contient toutes les commandes permettant "
            "de gérer ton équipage."
        ),
        colour=discord.Colour.gold(),
    )
    embed.add_field(
        name="Gestion des membres",
        value=(
            "`/equipage-inviter` — ajouter un membre\n"
            "`/equipage-exclure` — retirer un membre\n"
            "`/equipage-membres` — afficher l'équipage\n"
            "`/equipage-vice-capitaine` — nommer ou remplacer le second\n"
            "`/equipage-limite` — fixer la capacité entre 2 et 50"
        ),
        inline=False,
    )
    embed.add_field(
        name="Direction et recrutement",
        value=(
            "`/equipage-recrutement` — publier l'annonce officielle\n"
            "`/equipage-transferer` — transmettre définitivement l'équipage\n"
            "`/equipage-classement` — comparer l'activité des équipages\n"
            "`/equipage-commandes` — recevoir à nouveau ce guide\n"
            "`/equipage-supprimer` — supprimer définitivement l'équipage"
        ),
        inline=False,
    )
    embed.add_field(
        name="Commandes des membres",
        value="`/equipage-quitter` — quitter volontairement l'équipage.",
        inline=False,
    )
    embed.set_footer(
        text="Une personne ne peut appartenir qu'à un seul équipage."
    )
    return embed


async def send_crew_captain_guide(
    captain: discord.Member, crew_name: str
) -> bool:
    try:
        await captain.send(embed=crew_captain_guide_embed(crew_name))
        return True
    except discord.HTTPException:
        return False


async def log_crew_action(
    guild: discord.Guild,
    crew_id: int,
    actor_id: int,
    action: str,
    target_id: int | None = None,
) -> None:
    connection = require_database()
    connection.execute(
        """
        INSERT INTO crew_logs (
            guild_id, crew_id, actor_id, action, target_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (guild.id, crew_id, actor_id, action[:500], target_id, int(time.time())),
    )
    connection.commit()
    row = connection.execute(
        "SELECT text_channel_id FROM crews WHERE id = ? AND guild_id = ?",
        (crew_id, guild.id),
    ).fetchone()
    if row is None:
        return
    channel = guild.get_channel(row[0])
    if isinstance(channel, discord.TextChannel):
        target = f" • <@{target_id}>" if target_id is not None else ""
        try:
            await channel.send(
                f"📒 <t:{int(time.time())}:F> • <@{actor_id}> — "
                f"**{action}**{target}"
            )
        except discord.HTTPException:
            pass


async def create_crew_for_member(
    guild: discord.Guild,
    owner: discord.Member,
    clean_name: str,
    *,
    reason: str,
) -> discord.TextChannel:
    category = discord.utils.get(guild.categories, name=CREW_CATEGORY_NAME)
    if category is None:
        raise RuntimeError("La catégorie privée des équipages est absente.")
    connection = require_database()
    role = await guild.create_role(
        name=f"🏴‍☠️・{clean_name}",
        colour=discord.Colour.random(),
        reason=reason,
    )
    overwrites = dict(category.overwrites)
    overwrites[role] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        connect=True,
        speak=True,
    )
    text_channel: discord.TextChannel | None = None
    voice_channel: discord.VoiceChannel | None = None
    try:
        text_channel = await guild.create_text_channel(
            stylize_channel_name(f"🏴‍☠️・{clean_name}"),
            category=category,
            overwrites=overwrites,
            reason=reason,
        )
        voice_channel = await guild.create_voice_channel(
            stylize_channel_name(f"🔊・{clean_name}"),
            category=category,
            overwrites=overwrites,
            reason=reason,
        )
        cursor = connection.execute(
            """
            INSERT INTO crews (
                guild_id, owner_id, name, role_id, text_channel_id,
                voice_channel_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild.id,
                owner.id,
                clean_name,
                role.id,
                text_channel.id,
                voice_channel.id,
                int(time.time()),
            ),
        )
        connection.execute(
            """
            INSERT INTO crew_members (crew_id, guild_id, user_id, joined_at)
            VALUES (?, ?, ?, ?)
            """,
            (cursor.lastrowid, guild.id, owner.id, int(time.time())),
        )
        connection.commit()
        captain_role = discord.utils.get(guild.roles, name=CAPTAIN_ROLE_NAME)
        roles_to_add = [role]
        if captain_role is not None:
            roles_to_add.append(captain_role)
        await owner.add_roles(
            *roles_to_add, reason="Créateur et capitaine de l'équipage"
        )
        await text_channel.send(
            f"🏴‍☠️ Bienvenue dans l'équipage **{clean_name}** de "
            f"{owner.mention} !"
        )
        guide_sent = await send_crew_captain_guide(owner, clean_name)
        if not guide_sent:
            await text_channel.send(
                f"{owner.mention}, tes messages privés sont fermés. Utilise "
                "`/equipage-commandes` après les avoir ouverts pour recevoir le guide."
            )
        await log_crew_action(
            guild, cursor.lastrowid, owner.id, "Équipage créé"
        )
        await update_crew_presentation(guild, cursor.lastrowid)
        return text_channel
    except Exception:
        logging.exception("Échec de création de l'équipage %s", clean_name)
        connection.rollback()
        for channel in (text_channel, voice_channel):
            if channel is not None:
                try:
                    await channel.delete(reason="Création d'équipage échouée")
                except discord.HTTPException:
                    pass
        try:
            await role.delete(reason="Création d'équipage échouée")
        except discord.HTTPException:
            pass
        raise


@bot.tree.command(name="equipage-creer", description="Crée ton équipage permanent.")
@app_commands.describe(nom="Nom de l'équipage")
async def crew_create(interaction: discord.Interaction, nom: str) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    level = member_level(interaction.guild.id, interaction.user.id)
    if level < CREW_CREATION_LEVEL:
        await interaction.response.send_message(
            f"Il faut être niveau **{CREW_CREATION_LEVEL}** pour créer un équipage. "
            f"Tu es niveau **{level}**.",
            ephemeral=True,
        )
        return
    connection = require_database()
    if connection.execute(
        "SELECT 1 FROM crew_members WHERE guild_id = ? AND user_id = ?",
        (interaction.guild.id, interaction.user.id),
    ).fetchone():
        await interaction.response.send_message(
            "Tu appartiens déjà à un équipage. Une personne ne peut avoir qu'un "
            "seul équipage.",
            ephemeral=True,
        )
        return
    clean_name = " ".join(nom.split())[:40]
    if len(clean_name) < 2:
        await interaction.response.send_message(
            "Le nom doit contenir au moins deux caractères.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        text_channel = await create_crew_for_member(
            interaction.guild,
            interaction.user,
            clean_name,
            reason=f"Équipage créé par {interaction.user}",
        )
    except Exception:
        await interaction.followup.send(
            "La création de l'équipage a échoué. Vérifie que la catégorie privée "
            "des équipages existe et que le bot peut gérer les rôles et salons.",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        f"Équipage **{clean_name}** créé : {text_channel.mention}", ephemeral=True
    )


@bot.tree.command(
    name="equipage-creer-pour",
    description="Crée un équipage et désigne directement son capitaine.",
)
@app_commands.describe(
    membre="Membre qui deviendra capitaine",
    nom="Nom du nouvel équipage",
)
async def crew_create_for_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    nom: str,
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
    ):
        return
    if not is_ticket_staff(interaction.user) or is_helper(interaction.user):
        await interaction.response.send_message(
            "Cette commande est réservée au staff supérieur.", ephemeral=True
        )
        return
    if membre.bot:
        await interaction.response.send_message(
            "Un bot ne peut pas devenir capitaine.", ephemeral=True
        )
        return
    if require_database().execute(
        "SELECT 1 FROM crew_members WHERE guild_id = ? AND user_id = ?",
        (interaction.guild.id, membre.id),
    ).fetchone():
        await interaction.response.send_message(
            "Ce membre appartient déjà à un équipage.", ephemeral=True
        )
        return
    clean_name = " ".join(nom.split())[:40]
    if len(clean_name) < 2:
        await interaction.response.send_message(
            "Le nom doit contenir au moins deux caractères.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        text_channel = await create_crew_for_member(
            interaction.guild,
            membre,
            clean_name,
            reason=f"Équipage créé pour {membre} par {interaction.user}",
        )
    except Exception:
        await interaction.followup.send(
            "La création a échoué. Vérifie les permissions et la catégorie privée "
            "des équipages.",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        f"✅ {membre.mention} devient capitaine de **{clean_name}** : "
        f"{text_channel.mention}",
        ephemeral=True,
    )


class CrewRecruitmentModal(discord.ui.Modal):
    def __init__(self, crew_id: int) -> None:
        super().__init__(title="📢 Recrutement de mon équipage", timeout=600)
        self.crew_id = crew_id
        self.description_input = discord.ui.TextInput(
            label="Présentation de l'équipage",
            placeholder="Ambiance, objectifs et activités principales",
            style=discord.TextStyle.paragraph,
            min_length=30,
            max_length=800,
        )
        self.requirements = discord.ui.TextInput(
            label="Conditions pour rejoindre",
            placeholder="Niveau, mer, activité, micro, âge...",
            style=discord.TextStyle.paragraph,
            max_length=600,
        )
        self.sought_profiles = discord.ui.TextInput(
            label="Profils recherchés",
            placeholder="PvP, raids, sea events, farm, fruits recherchés...",
            style=discord.TextStyle.paragraph,
            max_length=600,
        )
        self.add_item(self.description_input)
        self.add_item(self.requirements)
        self.add_item(self.sought_profiles)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if (
            interaction.guild is None
            or not isinstance(interaction.channel, discord.TextChannel)
            or interaction.channel.name != CREW_RECRUITMENT_CHANNEL_NAME
        ):
            await interaction.response.send_message(
                f"Utilise ce formulaire dans `{CREW_RECRUITMENT_CHANNEL_NAME}`.",
                ephemeral=True,
            )
            return
        connection = require_database()
        crew = connection.execute(
            """
            SELECT name FROM crews
            WHERE id = ? AND guild_id = ? AND owner_id = ?
            """,
            (self.crew_id, interaction.guild.id, interaction.user.id),
        ).fetchone()
        if crew is None:
            await interaction.response.send_message(
                "Tu n'es plus propriétaire de cet équipage.", ephemeral=True
            )
            return
        previous_rows = connection.execute(
            """
            SELECT message_id FROM crew_recruitments
            WHERE crew_id = ? AND status = 'open'
            """,
            (self.crew_id,),
        ).fetchall()
        for (message_id,) in previous_rows:
            try:
                old_message = await interaction.channel.fetch_message(message_id)
                await old_message.delete()
            except discord.HTTPException:
                pass
        connection.execute(
            """
            UPDATE crew_recruitments SET status = 'replaced'
            WHERE crew_id = ? AND status = 'open'
            """,
            (self.crew_id,),
        )
        embed = discord.Embed(
            title=f"🏴‍☠️ {crew[0]} recrute !",
            description=str(self.description_input),
            colour=discord.Colour.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="📋 Conditions", value=str(self.requirements), inline=False
        )
        embed.add_field(
            name="🔎 Profils recherchés",
            value=str(self.sought_profiles),
            inline=False,
        )
        embed.add_field(
            name="👑 Capitaine", value=interaction.user.mention, inline=False
        )
        embed.set_footer(text="Un CV joueur est obligatoire pour postuler")
        message = await interaction.channel.send(
            embed=embed, view=CrewRecruitmentView()
        )
        connection.execute(
            """
            INSERT INTO crew_recruitments (
                message_id, guild_id, crew_id, captain_id, description,
                requirements, sought_profiles, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                interaction.guild.id,
                self.crew_id,
                interaction.user.id,
                str(self.description_input),
                str(self.requirements),
                str(self.sought_profiles),
                int(time.time()),
            ),
        )
        connection.commit()
        await interaction.response.send_message(
            f"✅ Ton recrutement est publié : {message.jump_url}", ephemeral=True
        )


@bot.tree.command(
    name="equipage-recrutement",
    description="Publie l'annonce de recrutement de ton équipage.",
)
async def crew_recruitment(interaction: discord.Interaction) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.channel, discord.TextChannel)
        or interaction.channel.name != CREW_RECRUITMENT_CHANNEL_NAME
    ):
        await interaction.response.send_message(
            f"Cette commande est uniquement disponible dans "
            f"`{CREW_RECRUITMENT_CHANNEL_NAME}`.",
            ephemeral=True,
        )
        return
    crew = require_database().execute(
        """
        SELECT id FROM crews WHERE guild_id = ? AND owner_id = ?
        """,
        (interaction.guild.id, interaction.user.id),
    ).fetchone()
    if crew is None:
        await interaction.response.send_message(
            "Seuls les capitaines possédant un équipage peuvent publier ici.",
            ephemeral=True,
        )
        return
    await interaction.response.send_modal(CrewRecruitmentModal(crew[0]))


async def finish_crew_application(
    interaction: discord.Interaction, *, accepted: bool
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
        or not isinstance(interaction.channel, discord.TextChannel)
    ):
        return
    connection = require_database()
    application = connection.execute(
        """
        SELECT id, crew_id, captain_id, applicant_id FROM crew_applications
        WHERE channel_id = ? AND status = 'open'
        """,
        (interaction.channel.id,),
    ).fetchone()
    if application is None:
        await interaction.response.send_message(
            "Cette candidature est déjà terminée.", ephemeral=True
        )
        return
    if (
        interaction.user.id != application[2]
        and not is_ticket_staff(interaction.user)
    ):
        await interaction.response.send_message(
            "Seul le capitaine ou le staff peut décider.", ephemeral=True
        )
        return
    applicant = interaction.guild.get_member(application[3])
    crew = connection.execute(
        "SELECT name, role_id FROM crews WHERE id = ?", (application[1],)
    ).fetchone()
    if applicant is None or crew is None:
        await interaction.response.send_message(
            "Le membre ou l'équipage est introuvable.", ephemeral=True
        )
        return
    if accepted:
        already_member = connection.execute(
            "SELECT 1 FROM crew_members WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, applicant.id),
        ).fetchone()
        if already_member:
            await interaction.response.send_message(
                "Ce membre a déjà rejoint un équipage.", ephemeral=True
            )
            return
        role = interaction.guild.get_role(crew[1])
        if role is None:
            await interaction.response.send_message(
                "Le rôle de l'équipage est introuvable.", ephemeral=True
            )
            return
        connection.execute(
            """
            INSERT INTO crew_members (crew_id, guild_id, user_id, joined_at)
            VALUES (?, ?, ?, ?)
            """,
            (application[1], interaction.guild.id, applicant.id, int(time.time())),
        )
        await applicant.add_roles(role, reason=f"Accepté dans {crew[0]}")
        status = "accepted"
        announcement = (
            f"✅ {applicant.mention} est accepté dans l'équipage **{crew[0]}** !"
        )
    else:
        status = "rejected"
        announcement = f"❌ La candidature de {applicant.mention} est refusée."
    connection.execute(
        "UPDATE crew_applications SET status = ? WHERE id = ?",
        (status, application[0]),
    )
    connection.commit()
    await interaction.response.send_message(announcement)
    await update_crew_presentation(interaction.guild, application[1])
    await asyncio.sleep(10)
    try:
        await interaction.channel.delete(
            reason=f"Candidature d'équipage {status}"
        )
    except discord.HTTPException:
        pass


class CrewApplicationView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Accepter",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="radarok:crew:application:accept",
    )
    async def accept(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await finish_crew_application(interaction, accepted=True)

    @discord.ui.button(
        label="Refuser",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="radarok:crew:application:reject",
    )
    async def reject(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await finish_crew_application(interaction, accepted=False)


class CrewRecruitmentView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Postuler",
        emoji="📨",
        style=discord.ButtonStyle.primary,
        custom_id="radarok:crew:apply",
    )
    async def apply(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if (
            interaction.guild is None
            or interaction.message is None
            or not isinstance(interaction.user, discord.Member)
        ):
            return
        connection = require_database()
        recruitment = connection.execute(
            """
            SELECT crew_id, captain_id, status FROM crew_recruitments
            WHERE message_id = ?
            """,
            (interaction.message.id,),
        ).fetchone()
        if recruitment is None or recruitment[2] != "open":
            await interaction.response.send_message(
                "Ce recrutement n'est plus ouvert.", ephemeral=True
            )
            return
        if interaction.user.id == recruitment[1]:
            await interaction.response.send_message(
                "Tu ne peux pas postuler dans ton propre équipage.", ephemeral=True
            )
            return
        if connection.execute(
            "SELECT 1 FROM crew_members WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, interaction.user.id),
        ).fetchone():
            await interaction.response.send_message(
                "Tu appartiens déjà à un équipage.", ephemeral=True
            )
            return
        cv = connection.execute(
            """
            SELECT roblox_name, level, profile, availability, looking_for,
                   message_id, channel_id
            FROM player_cvs WHERE guild_id = ? AND user_id = ?
            """,
            (interaction.guild.id, interaction.user.id),
        ).fetchone()
        if cv is None:
            await interaction.response.send_message(
                f"Tu dois d'abord créer ton CV avec `/cv-creer` dans "
                f"`{PLAYER_CV_CHANNEL_NAME}`.",
                ephemeral=True,
            )
            return
        if connection.execute(
            """
            SELECT 1 FROM crew_applications
            WHERE guild_id = ? AND applicant_id = ? AND status = 'open'
            """,
            (interaction.guild.id, interaction.user.id),
        ).fetchone():
            await interaction.response.send_message(
                "Tu as déjà une candidature d'équipage en cours.", ephemeral=True
            )
            return
        captain = interaction.guild.get_member(recruitment[1])
        crew = connection.execute(
            "SELECT name FROM crews WHERE id = ?", (recruitment[0],)
        ).fetchone()
        category = discord.utils.get(
            interaction.guild.categories, name=CREW_CATEGORY_NAME
        )
        if captain is None or crew is None or category is None:
            await interaction.response.send_message(
                "Cet équipage n'est plus disponible.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        overwrites = dict(category.overwrites)
        for participant in (captain, interaction.user):
            overwrites[participant] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )
        channel = await interaction.guild.create_text_channel(
            stylize_channel_name(
                f"📨・candidature-{interaction.user.display_name[:25]}"
            ),
            category=category,
            overwrites=overwrites,
            reason=f"Candidature pour l'équipage {crew[0]}",
        )
        cursor = connection.execute(
            """
            INSERT INTO crew_applications (
                guild_id, recruitment_message_id, crew_id, captain_id,
                applicant_id, channel_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interaction.guild.id,
                interaction.message.id,
                recruitment[0],
                captain.id,
                interaction.user.id,
                channel.id,
                int(time.time()),
            ),
        )
        connection.commit()
        cv_link = (
            f"https://discord.com/channels/{interaction.guild.id}/{cv[6]}/{cv[5]}"
        )
        embed = discord.Embed(
            title=f"📨 Candidature #{cursor.lastrowid} • {crew[0]}",
            description=(
                f"Candidat : {interaction.user.mention}\n"
                f"Capitaine : {captain.mention}\n"
                f"[Voir le CV publié]({cv_link})"
            ),
            colour=discord.Colour.blue(),
        )
        embed.add_field(name="🎮 Roblox", value=cv[0], inline=False)
        embed.add_field(name="🌊 Niveau", value=cv[1], inline=False)
        embed.add_field(name="🍈 Profil", value=cv[2], inline=False)
        embed.add_field(name="🕒 Disponibilités", value=cv[3], inline=False)
        embed.add_field(name="🔎 Recherche", value=cv[4], inline=False)
        await channel.send(
            content=f"{captain.mention} {interaction.user.mention}",
            embed=embed,
            view=CrewApplicationView(),
        )
        await interaction.followup.send(
            f"Ta candidature est ouverte : {channel.mention}", ephemeral=True
        )


def get_managed_crew(guild_id: int, user_id: int) -> tuple | None:
    return require_database().execute(
        """
        SELECT id, owner_id, vice_captain_id, name, role_id, text_channel_id,
               voice_channel_id, max_members
        FROM crews
        WHERE guild_id = ? AND (owner_id = ? OR vice_captain_id = ?)
        """,
        (guild_id, user_id, user_id),
    ).fetchone()


@bot.tree.command(
    name="equipage-commandes",
    description="Reçoit en privé le guide complet de son équipage.",
)
async def crew_commands(interaction: discord.Interaction) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    crew = get_managed_crew(interaction.guild.id, interaction.user.id)
    if crew is None:
        await interaction.response.send_message(
            "Tu ne diriges aucun équipage.", ephemeral=True
        )
        return
    if await send_crew_captain_guide(interaction.user, crew[3]):
        await interaction.response.send_message(
            "📨 Le guide complet vient de t'être envoyé en message privé.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "Je ne peux pas t'envoyer de MP. Autorise les messages privés des "
            "membres du serveur puis réessaie.",
            ephemeral=True,
        )


@bot.tree.command(
    name="equipage-inviter",
    description="Ajoute un membre à ton équipage.",
)
async def crew_invite(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    crew = get_managed_crew(interaction.guild.id, interaction.user.id)
    if crew is None:
        await interaction.response.send_message(
            "Tu dois être capitaine ou vice-capitaine.", ephemeral=True
        )
        return
    if membre.bot or membre.id == interaction.user.id:
        await interaction.response.send_message(
            "Ce membre ne peut pas être ajouté.", ephemeral=True
        )
        return
    connection = require_database()
    if connection.execute(
        "SELECT 1 FROM crew_members WHERE guild_id = ? AND user_id = ?",
        (interaction.guild.id, membre.id),
    ).fetchone():
        await interaction.response.send_message(
            "Ce membre appartient déjà à un équipage.", ephemeral=True
        )
        return
    member_count = connection.execute(
        "SELECT COUNT(*) FROM crew_members WHERE crew_id = ?", (crew[0],)
    ).fetchone()[0]
    if member_count >= crew[7]:
        await interaction.response.send_message(
            f"L'équipage a atteint sa limite de **{crew[7]} membres**.",
            ephemeral=True,
        )
        return
    role = interaction.guild.get_role(crew[4])
    if role is None:
        await interaction.response.send_message(
            "Le rôle de l'équipage est introuvable.", ephemeral=True
        )
        return
    connection.execute(
        """
        INSERT INTO crew_members (crew_id, guild_id, user_id, joined_at)
        VALUES (?, ?, ?, ?)
        """,
        (crew[0], interaction.guild.id, membre.id, int(time.time())),
    )
    connection.commit()
    try:
        await membre.add_roles(
            role, reason=f"Invité dans {crew[3]} par {interaction.user}"
        )
    except discord.HTTPException:
        connection.execute(
            "DELETE FROM crew_members WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, membre.id),
        )
        connection.commit()
        await interaction.response.send_message(
            "Je n'ai pas pu attribuer le rôle à ce membre.", ephemeral=True
        )
        return
    await log_crew_action(
        interaction.guild, crew[0], interaction.user.id, "Membre ajouté", membre.id
    )
    await update_crew_presentation(interaction.guild, crew[0])
    await interaction.response.send_message(
        f"✅ {membre.mention} rejoint **{crew[3]}**.", ephemeral=True
    )
    try:
        await membre.send(
            f"🏴‍☠️ Tu as rejoint l'équipage **{crew[3]}** sur "
            f"**{interaction.guild.name}**."
        )
    except discord.HTTPException:
        pass


@bot.tree.command(
    name="equipage-exclure",
    description="Exclut un membre de ton équipage.",
)
async def crew_exclude(
    interaction: discord.Interaction, membre: discord.Member, raison: str
) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    crew = get_managed_crew(interaction.guild.id, interaction.user.id)
    if crew is None:
        await interaction.response.send_message(
            "Tu dois être capitaine ou vice-capitaine.", ephemeral=True
        )
        return
    if membre.id == crew[1]:
        await interaction.response.send_message(
            "Le capitaine ne peut pas être exclu.", ephemeral=True
        )
        return
    if interaction.user.id == crew[2] and membre.id == crew[2]:
        await interaction.response.send_message(
            "Le vice-capitaine ne peut pas s'exclure avec cette commande.",
            ephemeral=True,
        )
        return
    connection = require_database()
    membership = connection.execute(
        """
        SELECT 1 FROM crew_members
        WHERE crew_id = ? AND guild_id = ? AND user_id = ?
        """,
        (crew[0], interaction.guild.id, membre.id),
    ).fetchone()
    if membership is None:
        await interaction.response.send_message(
            "Ce membre ne fait pas partie de ton équipage.", ephemeral=True
        )
        return
    connection.execute(
        "DELETE FROM crew_members WHERE guild_id = ? AND user_id = ?",
        (interaction.guild.id, membre.id),
    )
    if membre.id == crew[2]:
        connection.execute(
            "UPDATE crews SET vice_captain_id = NULL WHERE id = ?", (crew[0],)
        )
    connection.commit()
    role = interaction.guild.get_role(crew[4])
    if role is not None:
        await membre.remove_roles(
            role, reason=f"Exclu de {crew[3]} : {raison[:200]}"
        )
    await log_crew_action(
        interaction.guild,
        crew[0],
        interaction.user.id,
        f"Membre exclu • {raison[:300]}",
        membre.id,
    )
    await update_crew_presentation(interaction.guild, crew[0])
    await interaction.response.send_message(
        f"✅ {membre.mention} a été exclu de **{crew[3]}**.", ephemeral=True
    )


@bot.tree.command(
    name="equipage-vice-capitaine",
    description="Nomme ou remplace le vice-capitaine.",
)
async def crew_vice_captain(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    crew = require_database().execute(
        """
        SELECT id, name, text_channel_id, voice_channel_id, vice_captain_id
        FROM crews WHERE guild_id = ? AND owner_id = ?
        """,
        (interaction.guild.id, interaction.user.id),
    ).fetchone()
    if crew is None:
        await interaction.response.send_message(
            "Seul le capitaine peut nommer son vice-capitaine.", ephemeral=True
        )
        return
    if membre.id == interaction.user.id:
        await interaction.response.send_message(
            "Tu es déjà capitaine.", ephemeral=True
        )
        return
    membership = require_database().execute(
        "SELECT 1 FROM crew_members WHERE crew_id = ? AND user_id = ?",
        (crew[0], membre.id),
    ).fetchone()
    if membership is None:
        await interaction.response.send_message(
            "Ce membre doit d'abord appartenir à ton équipage.", ephemeral=True
        )
        return
    require_database().execute(
        "UPDATE crews SET vice_captain_id = ? WHERE id = ?",
        (membre.id, crew[0]),
    )
    require_database().commit()
    former_vice = (
        interaction.guild.get_member(crew[4]) if crew[4] is not None else None
    )
    for channel_id in crew[2:4]:
        channel = interaction.guild.get_channel(channel_id)
        if channel is not None:
            if former_vice is not None and former_vice.id != membre.id:
                await channel.set_permissions(
                    former_vice,
                    overwrite=None,
                    reason="Remplacement du vice-capitaine",
                )
            await channel.set_permissions(
                membre,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                connect=True,
                speak=True,
                manage_messages=True,
                move_members=True,
                reason="Vice-capitaine de l'équipage",
            )
    await log_crew_action(
        interaction.guild,
        crew[0],
        interaction.user.id,
        "Vice-capitaine nommé",
        membre.id,
    )
    await send_crew_captain_guide(membre, crew[1])
    await interaction.response.send_message(
        f"✅ {membre.mention} est vice-capitaine de **{crew[1]}**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="equipage-limite",
    description="Définit le nombre maximal de membres.",
)
async def crew_limit(interaction: discord.Interaction, limite: int) -> None:
    if interaction.guild is None:
        return
    crew = require_database().execute(
        "SELECT id, name FROM crews WHERE guild_id = ? AND owner_id = ?",
        (interaction.guild.id, interaction.user.id),
    ).fetchone()
    if crew is None:
        await interaction.response.send_message(
            "Seul le capitaine peut modifier la limite.", ephemeral=True
        )
        return
    count = require_database().execute(
        "SELECT COUNT(*) FROM crew_members WHERE crew_id = ?", (crew[0],)
    ).fetchone()[0]
    if limite < max(2, count) or limite > 50:
        await interaction.response.send_message(
            f"La limite doit être comprise entre **{max(2, count)}** et **50**.",
            ephemeral=True,
        )
        return
    require_database().execute(
        "UPDATE crews SET max_members = ? WHERE id = ?", (limite, crew[0])
    )
    require_database().commit()
    await log_crew_action(
        interaction.guild,
        crew[0],
        interaction.user.id,
        f"Limite fixée à {limite} membres",
    )
    await interaction.response.send_message(
        f"✅ **{crew[1]}** accepte maintenant jusqu'à **{limite} membres**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="equipage-membres",
    description="Affiche les membres de ton équipage.",
)
async def crew_members_command(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    row = require_database().execute(
        """
        SELECT c.id, c.name, c.owner_id, c.vice_captain_id, c.max_members
        FROM crew_members cm JOIN crews c ON c.id = cm.crew_id
        WHERE cm.guild_id = ? AND cm.user_id = ?
        """,
        (interaction.guild.id, interaction.user.id),
    ).fetchone()
    if row is None:
        await interaction.response.send_message(
            "Tu n'appartiens à aucun équipage.", ephemeral=True
        )
        return
    member_rows = require_database().execute(
        """
        SELECT user_id, joined_at FROM crew_members
        WHERE crew_id = ? ORDER BY joined_at
        """,
        (row[0],),
    ).fetchall()
    lines = []
    for user_id, joined_at in member_rows:
        badge = "👑" if user_id == row[2] else "⚔️" if user_id == row[3] else "•"
        lines.append(f"{badge} <@{user_id}> • depuis <t:{joined_at}:d>")
    await interaction.response.send_message(
        embed=discord.Embed(
            title=f"🏴‍☠️ {row[1]} • {len(lines)}/{row[4]}",
            description="\n".join(lines)[:4000],
            colour=discord.Colour.gold(),
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="equipage-transferer",
    description="Transfère définitivement ton équipage à un membre.",
)
async def crew_transfer(
    interaction: discord.Interaction, nouveau_capitaine: discord.Member
) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    connection = require_database()
    crew = connection.execute(
        """
        SELECT id, name, vice_captain_id, text_channel_id, voice_channel_id
        FROM crews WHERE guild_id = ? AND owner_id = ?
        """,
        (interaction.guild.id, interaction.user.id),
    ).fetchone()
    if crew is None:
        await interaction.response.send_message(
            "Tu n'es capitaine d'aucun équipage.", ephemeral=True
        )
        return
    if connection.execute(
        "SELECT 1 FROM crew_members WHERE crew_id = ? AND user_id = ?",
        (crew[0], nouveau_capitaine.id),
    ).fetchone() is None:
        await interaction.response.send_message(
            "Le nouveau capitaine doit appartenir à ton équipage.", ephemeral=True
        )
        return
    connection.execute(
        """
        UPDATE crews SET owner_id = ?, vice_captain_id = NULL WHERE id = ?
        """,
        (nouveau_capitaine.id, crew[0]),
    )
    connection.commit()
    former_vice = (
        interaction.guild.get_member(crew[2]) if crew[2] is not None else None
    )
    if former_vice is not None:
        for channel_id in crew[3:5]:
            channel = interaction.guild.get_channel(channel_id)
            if channel is not None:
                await channel.set_permissions(
                    former_vice,
                    overwrite=None,
                    reason="Transfert de la capitainerie",
                )
    captain_role = discord.utils.get(interaction.guild.roles, name=CAPTAIN_ROLE_NAME)
    if captain_role is not None:
        await interaction.user.remove_roles(
            captain_role, reason="Transfert de l'équipage"
        )
        await nouveau_capitaine.add_roles(
            captain_role, reason="Nouveau capitaine de l'équipage"
        )
    await log_crew_action(
        interaction.guild,
        crew[0],
        interaction.user.id,
        "Capitainerie transférée",
        nouveau_capitaine.id,
    )
    await send_crew_captain_guide(nouveau_capitaine, crew[1])
    await update_crew_presentation(interaction.guild, crew[0])
    await interaction.response.send_message(
        f"✅ {nouveau_capitaine.mention} est maintenant capitaine de "
        f"**{crew[1]}**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="equipage-classement",
    description="Affiche le classement d'activité des équipages.",
)
async def crew_ranking(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    rows = require_database().execute(
        """
        SELECT c.name, COUNT(cm.user_id),
               COALESCE(SUM(ms.message_xp + ms.voice_xp + ms.bonus_xp), 0)
        FROM crews c
        LEFT JOIN crew_members cm ON cm.crew_id = c.id
        LEFT JOIN member_stats ms
          ON ms.guild_id = c.guild_id AND ms.user_id = cm.user_id
        WHERE c.guild_id = ?
        GROUP BY c.id ORDER BY 3 DESC LIMIT 15
        """,
        (interaction.guild.id,),
    ).fetchall()
    lines = [
        f"`#{position}` **{name}** • {members} membre(s) • **{xp:,} XP**"
        for position, (name, members, xp) in enumerate(rows, start=1)
    ]
    await interaction.response.send_message(
        embed=discord.Embed(
            title="🏆 Classement des équipages",
            description="\n".join(lines) or "Aucun équipage.",
            colour=discord.Colour.gold(),
        )
    )


@bot.tree.command(name="equipage-quitter", description="Quitte ton équipage.")
async def crew_leave(interaction: discord.Interaction) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    connection = require_database()
    row = connection.execute(
        """
        SELECT c.id, c.owner_id, c.name, c.role_id, c.text_channel_id,
               c.voice_channel_id, c.vice_captain_id
        FROM crew_members cm JOIN crews c ON c.id = cm.crew_id
        WHERE cm.guild_id = ? AND cm.user_id = ?
        """,
        (interaction.guild.id, interaction.user.id),
    ).fetchone()
    if row is None:
        await interaction.response.send_message(
            "Tu n'appartiens à aucun équipage.", ephemeral=True
        )
        return
    if row[1] == interaction.user.id:
        await interaction.response.send_message(
            "Le propriétaire doit utiliser `/equipage-supprimer`.", ephemeral=True
        )
        return
    connection.execute(
        "DELETE FROM crew_members WHERE guild_id = ? AND user_id = ?",
        (interaction.guild.id, interaction.user.id),
    )
    connection.execute(
        """
        UPDATE crews SET vice_captain_id = NULL
        WHERE id = ? AND vice_captain_id = ?
        """,
        (row[0], interaction.user.id),
    )
    connection.commit()
    role = interaction.guild.get_role(row[3])
    if role is not None:
        await interaction.user.remove_roles(role, reason="Départ de l'équipage")
    if row[6] == interaction.user.id:
        for channel_id in row[4:6]:
            channel = interaction.guild.get_channel(channel_id)
            if channel is not None:
                await channel.set_permissions(
                    interaction.user,
                    overwrite=None,
                    reason="Départ du vice-capitaine",
                )
    await update_crew_presentation(interaction.guild, row[0])
    await log_crew_action(
        interaction.guild,
        row[0],
        interaction.user.id,
        "Membre parti volontairement",
        interaction.user.id,
    )
    await interaction.response.send_message(
        f"Tu as quitté **{row[2]}**.", ephemeral=True
    )


@bot.tree.command(name="equipage-supprimer", description="Supprime ton équipage.")
async def crew_delete(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    connection = require_database()
    row = connection.execute(
        """
        SELECT id, name, role_id, text_channel_id, voice_channel_id,
               presentation_message_id
        FROM crews WHERE guild_id = ? AND owner_id = ?
        """,
        (interaction.guild.id, interaction.user.id),
    ).fetchone()
    if row is None:
        await interaction.response.send_message(
            "Tu n'es propriétaire d'aucun équipage.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True)
    recruitment_messages = connection.execute(
        "SELECT message_id FROM crew_recruitments WHERE crew_id = ?",
        (row[0],),
    ).fetchall()
    application_channels = connection.execute(
        """
        SELECT channel_id FROM crew_applications
        WHERE crew_id = ? AND status = 'open'
        """,
        (row[0],),
    ).fetchall()
    connection.execute(
        "UPDATE crew_recruitments SET status = 'closed' WHERE crew_id = ?",
        (row[0],),
    )
    connection.execute(
        "UPDATE crew_applications SET status = 'closed' WHERE crew_id = ?",
        (row[0],),
    )
    connection.execute("DELETE FROM crew_members WHERE crew_id = ?", (row[0],))
    connection.execute("DELETE FROM crews WHERE id = ?", (row[0],))
    connection.commit()
    for channel_id in row[3:5]:
        channel = interaction.guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.delete(reason=f"Équipage {row[1]} supprimé")
            except discord.HTTPException:
                pass
    for (channel_id,) in application_channels:
        channel = interaction.guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.delete(reason=f"Équipage {row[1]} supprimé")
            except discord.HTTPException:
                pass
    role = interaction.guild.get_role(row[2])
    if role is not None:
        try:
            await role.delete(reason=f"Équipage {row[1]} supprimé")
        except discord.HTTPException:
            pass
    captain_role = discord.utils.get(
        interaction.guild.roles, name=CAPTAIN_ROLE_NAME
    )
    if captain_role is not None and isinstance(interaction.user, discord.Member):
        await interaction.user.remove_roles(
            captain_role, reason="Équipage supprimé"
        )
    presentation_channel = discord.utils.get(
        interaction.guild.text_channels, name=CREW_PRESENTATION_CHANNEL_NAME
    )
    if presentation_channel is not None and row[5] is not None:
        try:
            presentation = await presentation_channel.fetch_message(row[5])
            await presentation.delete()
        except discord.HTTPException:
            pass
    recruitment_channel = discord.utils.get(
        interaction.guild.text_channels, name=CREW_RECRUITMENT_CHANNEL_NAME
    )
    if recruitment_channel is not None:
        for (message_id,) in recruitment_messages:
            try:
                recruitment = await recruitment_channel.fetch_message(message_id)
                await recruitment.delete()
            except discord.HTTPException:
                pass
    await interaction.followup.send(
        f"L'équipage **{row[1]}** a été supprimé.", ephemeral=True
    )


def active_trade_for(guild_id: int, user_id: int) -> tuple | None:
    return require_database().execute(
        """
        SELECT id, channel_id FROM trade_deals
        WHERE guild_id = ? AND status = 'active'
          AND (seller_id = ? OR buyer_id = ?)
        """,
        (guild_id, user_id, user_id),
    ).fetchone()


async def close_trade_deal(
    channel: discord.TextChannel, status: str, closed_by: discord.Member
) -> None:
    connection = require_database()
    row = connection.execute(
        """
        SELECT id, post_message_id FROM trade_deals
        WHERE channel_id = ? AND status = 'active'
        """,
        (channel.id,),
    ).fetchone()
    if row is None:
        return
    connection.execute(
        "UPDATE trade_deals SET status = ? WHERE id = ?", (status, row[0])
    )
    connection.execute(
        "UPDATE trade_posts SET status = ? WHERE message_id = ?",
        ("completed" if status == "completed" else "closed", row[1]),
    )
    connection.commit()
    await channel.send(
        f"🔒 Trade **{status}** par {closed_by.mention}. "
        "Le salon sera supprimé dans 10 secondes."
    )
    await asyncio.sleep(10)
    try:
        await channel.delete(reason=f"Trade {status} par {closed_by}")
    except discord.HTTPException:
        pass


class TradeOfferView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Je suis intéressé",
        emoji="🤝",
        style=discord.ButtonStyle.success,
        custom_id="radarok:trade:interested",
    )
    async def interested(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if (
            interaction.guild is None
            or interaction.message is None
            or not isinstance(interaction.user, discord.Member)
        ):
            return
        connection = require_database()
        post = connection.execute(
            """
            SELECT author_id, offered, wanted, status FROM trade_posts
            WHERE message_id = ?
            """,
            (interaction.message.id,),
        ).fetchone()
        if post is None or post[3] != "open":
            await interaction.response.send_message(
                "Cette offre n'est plus disponible.", ephemeral=True
            )
            return
        if post[0] == interaction.user.id:
            await interaction.response.send_message(
                "Tu ne peux pas accepter ta propre offre.", ephemeral=True
            )
            return
        if active_trade_for(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message(
                "Tu dois finaliser ton trade actuel avant d'en commencer un autre.",
                ephemeral=True,
            )
            return
        if active_trade_for(interaction.guild.id, post[0]):
            await interaction.response.send_message(
                "L'auteur est déjà engagé dans un autre trade.", ephemeral=True
            )
            return
        seller = interaction.guild.get_member(post[0])
        if seller is None:
            await interaction.response.send_message(
                "L'auteur de l'offre a quitté le serveur.", ephemeral=True
            )
            return
        category = discord.utils.get(
            interaction.guild.categories, name=PRIVATE_TRADE_CATEGORY_NAME
        )
        if category is None:
            await interaction.response.send_message(
                "La catégorie privée des trades est absente. "
                "Contacte un administrateur.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        overwrites = dict(category.overwrites)
        for participant in (seller, interaction.user):
            overwrites[participant] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )
        channel = await interaction.guild.create_text_channel(
            stylize_channel_name(
                f"🤝・trade-{seller.display_name[:15]}-{interaction.user.display_name[:15]}"
            ),
            category=category,
            overwrites=overwrites,
            reason="Discussion privée pour un trade",
        )
        cursor = connection.execute(
            """
            INSERT INTO trade_deals (
                guild_id, post_message_id, seller_id, buyer_id,
                channel_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                interaction.guild.id,
                interaction.message.id,
                seller.id,
                interaction.user.id,
                channel.id,
                int(time.time()),
            ),
        )
        connection.execute(
            "UPDATE trade_posts SET status = 'matched' WHERE message_id = ?",
            (interaction.message.id,),
        )
        connection.commit()
        await channel.send(
            embed=discord.Embed(
                title=f"🤝 Trade #{cursor.lastrowid}",
                description=(
                    f"Participants : {seller.mention} et {interaction.user.mention}\n\n"
                    f"**Proposition :** {post[1]}\n"
                    f"**Recherche :** {post[2]}\n\n"
                    "Discutez ici sans partager d'identifiants ni accepter de promesse "
                    "hors de la fenêtre officielle du jeu.\n\n"
                    "À la fin, chacun utilise `/trade-avis`. Après les deux avis, "
                    "le salon se ferme. Utilisez `/trade-fermer` si le trade est annulé."
                ),
                colour=discord.Colour.teal(),
            )
        )
        await interaction.followup.send(
            f"Salon de trade créé : {channel.mention}", ephemeral=True
        )


@bot.tree.command(name="trade-publier", description="Publie une offre sur le marché.")
@app_commands.describe(
    proposition="Ce que tu proposes, emojis personnalisés acceptés",
    recherche="Ce que tu recherches, emojis personnalisés acceptés",
)
async def trade_publish(
    interaction: discord.Interaction, proposition: str, recherche: str
) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    if active_trade_for(interaction.guild.id, interaction.user.id):
        await interaction.response.send_message(
            "Finalise ton trade actuel avant de publier une nouvelle offre.",
            ephemeral=True,
        )
        return
    channel = discord.utils.get(
        interaction.guild.text_channels, name=TRADE_MARKET_CHANNEL_NAME
    )
    if channel is None:
        await interaction.response.send_message(
            "Le marché des trades est absent. Contacte un administrateur.",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title="🤝 Nouvelle offre de trade",
        description=(
            f"**Proposé par :** {interaction.user.mention}\n\n"
            f"📦 **Je propose**\n{proposition[:1000]}\n\n"
            f"🔎 **Je recherche**\n{recherche[:1000]}"
        ),
        colour=discord.Colour.teal(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(
        text="Aucun échange entre jeux différents ni promesse de paiement après"
    )
    message = await channel.send(embed=embed, view=TradeOfferView())
    require_database().execute(
        """
        INSERT INTO trade_posts (
            message_id, guild_id, channel_id, author_id,
            offered, wanted, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.id,
            interaction.guild.id,
            channel.id,
            interaction.user.id,
            proposition[:1000],
            recherche[:1000],
            int(time.time()),
        ),
    )
    require_database().commit()
    await interaction.followup.send(
        f"Offre publiée : {message.jump_url}", ephemeral=True
    )


@bot.tree.command(name="trade-avis", description="Évalue l'autre participant du trade.")
@app_commands.describe(etoiles="Note de 1 à 5", commentaire="Commentaire sur le trade")
async def trade_review(
    interaction: discord.Interaction,
    etoiles: app_commands.Range[int, 1, 5],
    commentaire: str = "Aucun commentaire",
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
        or not isinstance(interaction.channel, discord.TextChannel)
    ):
        return
    connection = require_database()
    deal = connection.execute(
        """
        SELECT id, seller_id, buyer_id FROM trade_deals
        WHERE channel_id = ? AND status = 'active'
        """,
        (interaction.channel.id,),
    ).fetchone()
    if deal is None or interaction.user.id not in deal[1:3]:
        await interaction.response.send_message(
            "Cette commande doit être utilisée dans ton trade actif.", ephemeral=True
        )
        return
    target_id = deal[2] if interaction.user.id == deal[1] else deal[1]
    try:
        connection.execute(
            """
            INSERT INTO trade_reviews (
                deal_id, reviewer_id, target_id, stars, comment, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                deal[0],
                interaction.user.id,
                target_id,
                etoiles,
                commentaire[:500],
                int(time.time()),
            ),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        await interaction.response.send_message(
            "Tu as déjà donné ton avis pour ce trade.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        f"⭐ Avis enregistré pour <@{target_id}> : **{etoiles}/5**."
    )
    review_count = connection.execute(
        "SELECT COUNT(*) FROM trade_reviews WHERE deal_id = ?", (deal[0],)
    ).fetchone()[0]
    if review_count >= 2:
        await close_trade_deal(interaction.channel, "completed", interaction.user)


@bot.tree.command(name="trade-fermer", description="Ferme un trade non terminé.")
@app_commands.describe(raison="Pourquoi le trade n'a pas été terminé")
async def trade_close(
    interaction: discord.Interaction, raison: str = "Trade annulé"
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
        or not isinstance(interaction.channel, discord.TextChannel)
    ):
        return
    deal = require_database().execute(
        """
        SELECT seller_id, buyer_id FROM trade_deals
        WHERE channel_id = ? AND status = 'active'
        """,
        (interaction.channel.id,),
    ).fetchone()
    if deal is None or (
        interaction.user.id not in deal and not is_ticket_staff(interaction.user)
    ):
        await interaction.response.send_message(
            "Tu ne peux pas fermer ce trade.", ephemeral=True
        )
        return
    await interaction.response.send_message(f"❌ Trade non terminé : {raison[:500]}")
    await close_trade_deal(interaction.channel, "cancelled", interaction.user)


@bot.tree.command(name="trade-profil", description="Affiche la réputation de trade.")
async def trade_profile(
    interaction: discord.Interaction, membre: discord.Member | None = None
) -> None:
    if interaction.guild is None:
        return
    target = membre or interaction.user
    rows = require_database().execute(
        """
        SELECT stars FROM trade_reviews tr
        JOIN trade_deals td ON td.id = tr.deal_id
        WHERE td.guild_id = ? AND tr.target_id = ?
        """,
        (interaction.guild.id, target.id),
    ).fetchall()
    average = sum(row[0] for row in rows) / len(rows) if rows else 0
    await interaction.response.send_message(
        embed=discord.Embed(
            title=f"⭐ Réputation de {target.display_name}",
            description=(
                f"**{average:.1f}/5** sur **{len(rows)} avis**."
                if rows
                else "Aucun trade évalué pour le moment."
            ),
            colour=discord.Colour.gold(),
        )
    )


class SanctionUndoView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Annuler la sanction",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        custom_id="radarok:moderation:undo",
    )
    async def undo(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if (
            interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
            or not is_ticket_staff(interaction.user)
            or is_helper(interaction.user)
            or interaction.message is None
            or not interaction.message.embeds
        ):
            await interaction.response.send_message(
                "Cette action est réservée au staff supérieur.", ephemeral=True
            )
            return
        footer = interaction.message.embeds[0].footer.text or ""
        match = re.search(r"#(\d+)", footer)
        if match is None:
            await interaction.response.send_message(
                "Numéro de dossier introuvable.", ephemeral=True
            )
            return
        case_id = int(match.group(1))
        connection = require_database()
        row = connection.execute(
            """
            SELECT user_id, action, cancelled_at FROM sanctions
            WHERE id = ? AND guild_id = ?
            """,
            (case_id, interaction.guild.id),
        ).fetchone()
        if row is None or row[2] is not None:
            await interaction.response.send_message(
                "Ce dossier est introuvable ou déjà annulé.", ephemeral=True
            )
            return
        target = interaction.guild.get_member(row[0])
        if target is None:
            await interaction.response.send_message(
                "Le membre n'est plus sur le serveur.", ephemeral=True
            )
            return
        action = row[1]
        if action.startswith("Avertissement #"):
            warning_match = re.search(r"#(\d+)", action)
            if warning_match is None:
                await interaction.response.send_message(
                    "Avertissement associé introuvable.", ephemeral=True
                )
                return
            connection.execute(
                """
                UPDATE warnings SET active = 0, removed_by = ?, removed_at = ?
                WHERE id = ? AND guild_id = ? AND active = 1
                """,
                (
                    interaction.user.id,
                    int(time.time()),
                    int(warning_match.group(1)),
                    interaction.guild.id,
                ),
            )
        elif action.startswith("Timeout") or action.startswith(
            "Escalade automatique"
        ):
            try:
                await target.timeout(
                    None,
                    reason=f"Dossier #{case_id} annulé par {interaction.user}",
                )
            except discord.HTTPException:
                await interaction.response.send_message(
                    "Discord a refusé le retrait du timeout.", ephemeral=True
                )
                return
        else:
            await interaction.response.send_message(
                "Ce type de dossier ne peut pas être annulé automatiquement.",
                ephemeral=True,
            )
            return
        connection.execute(
            """
            UPDATE sanctions SET cancelled_by = ?, cancelled_at = ?
            WHERE id = ?
            """,
            (interaction.user.id, int(time.time()), case_id),
        )
        connection.commit()
        embed = interaction.message.embeds[0]
        embed.colour = discord.Colour.green()
        embed.title = f"↩️ Dossier #{case_id} annulé"
        embed.add_field(
            name="Annulation",
            value=(
                f"Par {interaction.user.mention} • "
                f"<t:{int(time.time())}:F>"
            ),
            inline=False,
        )
        await interaction.response.edit_message(embed=embed, view=None)


@bot.tree.command(
    name="clear",
    description="Supprime un nombre précis de messages récents.",
)
@app_commands.describe(
    nombre="Nombre de messages à supprimer, entre 1 et 500",
    membre="Supprimer uniquement les messages de ce membre",
)
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
async def clear_messages_command(
    interaction: discord.Interaction,
    nombre: app_commands.Range[int, 1, 500],
    membre: discord.Member | None = None,
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.channel, discord.TextChannel)
        or not isinstance(interaction.user, discord.Member)
        or not is_ticket_staff(interaction.user)
        or is_helper(interaction.user)
    ):
        await interaction.response.send_message(
            "Cette commande est réservée au staff de modération.",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    selected = 0

    def message_matches(message: discord.Message) -> bool:
        nonlocal selected
        if selected >= nombre or message.pinned:
            return False
        if membre is not None and message.author.id != membre.id:
            return False
        selected += 1
        return True

    scan_limit = (
        min(2500, max(500, nombre * 5))
        if membre is None
        else min(5000, max(500, nombre * 20))
    )
    try:
        deleted = await interaction.channel.purge(
            limit=scan_limit,
            check=message_matches,
            bulk=True,
            reason=(
                f"Clear de {nombre} message(s) par {interaction.user}"
                + (f" pour {membre}" if membre is not None else "")
            ),
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "Discord refuse la suppression. Vérifie la permission "
            "**Gérer les messages** du bot.",
            ephemeral=True,
        )
        return
    except discord.HTTPException:
        logging.exception(
            "Impossible d'effectuer le clear dans le salon %s",
            interaction.channel.id,
        )
        await interaction.followup.send(
            "Discord a rencontré une erreur pendant la suppression.",
            ephemeral=True,
        )
        return

    target_text = (
        f" de {membre.mention}" if membre is not None else ""
    )
    await interaction.followup.send(
        f"🧹 **{len(deleted)} message(s)**{target_text} supprimé(s) dans "
        f"{interaction.channel.mention}. Les messages épinglés ont été conservés.",
        ephemeral=True,
    )
    log_channel = discord.utils.get(
        interaction.guild.text_channels, name=DISCORD_AUDIT_LOG_CHANNEL_NAME
    )
    if log_channel is not None:
        embed = discord.Embed(
            title="🧹 Messages supprimés par commande",
            colour=discord.Colour.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="Effectué par",
            value=f"{interaction.user.mention}\n`{interaction.user.id}`",
            inline=True,
        )
        embed.add_field(
            name="Salon",
            value=interaction.channel.mention,
            inline=True,
        )
        embed.add_field(
            name="Résultat",
            value=(
                f"Demandés : **{nombre}**\n"
                f"Supprimés : **{len(deleted)}**"
            ),
            inline=True,
        )
        if membre is not None:
            embed.add_field(
                name="Membre ciblé",
                value=f"{membre.mention}\n`{membre.id}`",
                inline=False,
            )
        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            logging.exception("Impossible de journaliser la commande clear")


async def send_sanction_log(
    guild: discord.Guild,
    *,
    action: str,
    target: discord.abc.User,
    moderator: discord.abc.User | None,
    reason: str,
    colour: discord.Colour = discord.Colour.red(),
) -> int | None:
    case_id: int | None = None
    if database is not None:
        cursor = require_database().execute(
            """
            INSERT INTO sanctions (
                guild_id, user_id, moderator_id, action, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                guild.id,
                target.id,
                moderator.id if moderator is not None else None,
                action[:100],
                reason[:1000],
                int(time.time()),
            ),
        )
        case_id = cursor.lastrowid
        require_database().commit()
    channel = discord.utils.get(guild.text_channels, name=SANCTION_LOG_CHANNEL_NAME)
    if channel is None:
        return case_id
    embed = discord.Embed(
        title=f"⚖️ Dossier #{case_id} • {action}",
        colour=colour,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="Membre", value=f"{target} (`{target.id}`)", inline=False
    )
    embed.add_field(
        name="Modérateur",
        value=(
            f"{moderator} (`{moderator.id}`)" if moderator is not None else "Automod"
        ),
        inline=False,
    )
    embed.add_field(name="Motif", value=reason[:1024], inline=False)
    embed.set_footer(text=f"Dossier de modération #{case_id}")
    try:
        reversible = (
            action.startswith("Avertissement #")
            or action.startswith("Timeout")
            or action.startswith("Escalade automatique")
        )
        await channel.send(
            embed=embed,
            view=SanctionUndoView() if reversible else None,
        )
    except discord.HTTPException:
        logging.exception("Impossible d'envoyer un journal de sanction")
    return case_id


@bot.tree.command(name="warn", description="Avertit un membre.")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
async def warn_command(
    interaction: discord.Interaction, membre: discord.Member, raison: str
) -> None:
    if interaction.guild is None:
        return
    cursor = require_database().execute(
        """
        INSERT INTO warnings (
            guild_id, user_id, moderator_id, reason, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            interaction.guild.id,
            membre.id,
            interaction.user.id,
            raison[:1000],
            int(time.time()),
        ),
    )
    require_database().commit()
    await interaction.response.send_message(
        f"⚠️ Avertissement **#{cursor.lastrowid}** ajouté à {membre.mention}.",
        ephemeral=True,
    )
    await send_sanction_log(
        interaction.guild,
        action=f"Avertissement #{cursor.lastrowid}",
        target=membre,
        moderator=interaction.user,
        reason=raison,
        colour=discord.Colour.orange(),
    )
    try:
        await membre.send(
            f"⚠️ Tu as reçu un avertissement sur **{interaction.guild.name}**.\n"
            f"Motif : {raison}"
        )
    except discord.HTTPException:
        pass
    active_warns = require_database().execute(
        """
        SELECT COUNT(*) FROM warnings
        WHERE guild_id = ? AND user_id = ? AND active = 1
        """,
        (interaction.guild.id, membre.id),
    ).fetchone()[0]
    escalation_seconds = {3: 3600, 5: 86400, 7: 604800}.get(active_warns)
    if escalation_seconds is not None:
        until = datetime.now(timezone.utc) + timedelta(seconds=escalation_seconds)
        try:
            await membre.timeout(
                until,
                reason=f"Escalade automatique après {active_warns} warns actifs",
            )
            await send_sanction_log(
                interaction.guild,
                action=(
                    f"Escalade automatique • timeout "
                    f"{format_remaining(escalation_seconds)}"
                ),
                target=membre,
                moderator=interaction.user,
                reason=f"Seuil de {active_warns} avertissements actifs atteint",
            )
        except discord.HTTPException:
            logging.exception(
                "Impossible d'appliquer l'escalade automatique à %s", membre.id
            )


@bot.tree.command(name="warns", description="Affiche les avertissements d'un membre.")
async def warnings_command(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
    ):
        return
    if not is_ticket_staff(interaction.user) and not is_helper(interaction.user):
        await interaction.response.send_message(
            "Cette commande est réservée aux helpers et au staff.", ephemeral=True
        )
        return
    rows = require_database().execute(
        """
        SELECT id, moderator_id, reason, created_at FROM warnings
        WHERE guild_id = ? AND user_id = ? AND active = 1
        ORDER BY created_at DESC LIMIT 20
        """,
        (interaction.guild.id, membre.id),
    ).fetchall()
    description = "\n\n".join(
        f"**#{warning_id}** • <t:{created_at}:f> • par <@{moderator_id}>\n"
        f"{reason}"
        for warning_id, moderator_id, reason, created_at in rows
    )[:4000]
    await interaction.response.send_message(
        embed=discord.Embed(
            title=f"⚠️ Avertissements de {membre.display_name}",
            description=description or "Aucun avertissement actif.",
            colour=discord.Colour.orange(),
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="warn-retirer",
    description="Retire un avertissement par son numéro.",
)
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
async def unwarn_command(interaction: discord.Interaction, identifiant: int) -> None:
    if interaction.guild is None:
        return
    row = require_database().execute(
        """
        SELECT user_id, reason FROM warnings
        WHERE id = ? AND guild_id = ? AND active = 1
        """,
        (identifiant, interaction.guild.id),
    ).fetchone()
    if row is None:
        await interaction.response.send_message(
            "Avertissement actif introuvable.", ephemeral=True
        )
        return
    require_database().execute(
        """
        UPDATE warnings SET active = 0, removed_by = ?, removed_at = ?
        WHERE id = ?
        """,
        (interaction.user.id, int(time.time()), identifiant),
    )
    require_database().commit()
    target = interaction.guild.get_member(row[0]) or await bot.fetch_user(row[0])
    await interaction.response.send_message(
        f"✅ Avertissement **#{identifiant}** retiré.", ephemeral=True
    )
    await send_sanction_log(
        interaction.guild,
        action=f"Retrait de l'avertissement #{identifiant}",
        target=target,
        moderator=interaction.user,
        reason=row[1],
        colour=discord.Colour.green(),
    )


@bot.tree.command(name="timeout", description="Place un membre en timeout.")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    duree: str,
    raison: str,
) -> None:
    seconds = parse_duration(duree)
    if interaction.guild is None or seconds is None or seconds > 2_419_200:
        await interaction.response.send_message(
            "Durée invalide ou supérieure à 28 jours. Exemple : `30m`, `2h`, `7d`.",
            ephemeral=True,
        )
        return
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    await membre.timeout(until, reason=raison)
    await interaction.response.send_message(
        f"🔇 {membre.mention} est en timeout jusqu'à <t:{int(until.timestamp())}:F>.",
        ephemeral=True,
    )
    await send_sanction_log(
        interaction.guild,
        action=f"Timeout de {format_remaining(seconds)}",
        target=membre,
        moderator=interaction.user,
        reason=raison,
    )


@bot.tree.command(
    name="timeout-retirer",
    description="Retire le timeout d'un membre.",
)
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout_command(
    interaction: discord.Interaction, membre: discord.Member, raison: str = "Fin anticipée"
) -> None:
    if interaction.guild is None:
        return
    await membre.timeout(None, reason=raison)
    await interaction.response.send_message(
        f"🔊 Timeout retiré pour {membre.mention}.", ephemeral=True
    )
    await send_sanction_log(
        interaction.guild,
        action="Fin de timeout",
        target=membre,
        moderator=interaction.user,
        reason=raison,
        colour=discord.Colour.green(),
    )


@bot.tree.command(
    name="sanctions",
    description="Affiche l'historique complet des sanctions d'un membre.",
)
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
async def sanctions_command(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    if interaction.guild is None:
        return
    rows = require_database().execute(
        """
        SELECT action, moderator_id, reason, created_at FROM sanctions
        WHERE guild_id = ? AND user_id = ?
        ORDER BY created_at DESC LIMIT 25
        """,
        (interaction.guild.id, membre.id),
    ).fetchall()
    description = "\n\n".join(
        f"**{action}** • <t:{created_at}:f>\n"
        f"Par {f'<@{moderator_id}>' if moderator_id else 'Automod'} — {reason}"
        for action, moderator_id, reason, created_at in rows
    )[:4000]
    await interaction.response.send_message(
        embed=discord.Embed(
            title=f"⚖️ Historique de {membre.display_name}",
            description=description or "Aucune sanction enregistrée.",
            colour=discord.Colour.red(),
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="infos-joueur",
    description="Affiche les informations utiles sur un membre.",
)
async def player_info_command(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
    ):
        return
    if not is_ticket_staff(interaction.user) and not is_helper(interaction.user):
        await interaction.response.send_message(
            "Cette commande est réservée aux helpers et au staff.", ephemeral=True
        )
        return
    message_xp, voice_xp, bonus_xp, voice_seconds, total_messages = (
        get_member_stats(interaction.guild.id, membre.id)
    )
    total_xp = message_xp + voice_xp + bonus_xp
    warning_count = require_database().execute(
        """
        SELECT COUNT(*) FROM warnings
        WHERE guild_id = ? AND user_id = ? AND active = 1
        """,
        (interaction.guild.id, membre.id),
    ).fetchone()[0]
    sanction_count = require_database().execute(
        """
        SELECT COUNT(*) FROM sanctions
        WHERE guild_id = ? AND user_id = ?
        """,
        (interaction.guild.id, membre.id),
    ).fetchone()[0]
    created_timestamp = int(membre.created_at.timestamp())
    joined_timestamp = (
        int(membre.joined_at.timestamp()) if membre.joined_at is not None else None
    )
    roles = [
        role.mention for role in reversed(membre.roles[1:]) if not role.is_default()
    ]
    embed = discord.Embed(
        title=f"🔎 Informations • {membre.display_name}",
        colour=membre.colour if membre.colour.value else discord.Colour.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=membre.display_avatar.url)
    embed.add_field(
        name="Identité",
        value=(
            f"Compte : {membre.mention}\n"
            f"Identifiant : `{membre.id}`\n"
            f"Bot : **{'Oui' if membre.bot else 'Non'}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Dates",
        value=(
            f"Compte créé : <t:{created_timestamp}:F> • <t:{created_timestamp}:R>\n"
            + (
                f"Serveur rejoint : <t:{joined_timestamp}:F> • "
                f"<t:{joined_timestamp}:R>"
                if joined_timestamp is not None
                else "Date d'arrivée indisponible"
            )
        ),
        inline=False,
    )
    embed.add_field(
        name="Activité",
        value=(
            f"Niveau : **{calculate_level(total_xp)}** • XP : **{total_xp:,}**\n"
            f"Messages comptabilisés : **{total_messages:,}**\n"
            f"Temps vocal : **{format_duration(voice_seconds)}**\n"
            f"Invitations : **{get_invite_count(interaction.guild.id, membre.id)}**"
        ),
        inline=False,
    )
    embed.add_field(
        name="Modération",
        value=(
            f"Warns actifs : **{warning_count}**\n"
            f"Sanctions enregistrées : **{sanction_count}**\n"
            f"Timeout actuel : "
            f"**{'Oui' if membre.is_timed_out() else 'Non'}**"
        ),
        inline=False,
    )
    embed.add_field(
        name=f"Rôles ({len(roles)})",
        value=(" ".join(roles)[:1024] if roles else "Aucun rôle"),
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


def can_manage_helpers(member: discord.Member) -> bool:
    return is_ticket_staff(member)


@bot.tree.command(
    name="helper-ajouter",
    description="Ajoute le rôle Helper à un membre.",
)
async def helper_add_command(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
    ):
        return
    if not can_manage_helpers(interaction.user):
        await interaction.response.send_message(
            "Cette commande est réservée au staff supérieur.", ephemeral=True
        )
        return
    if membre.bot:
        await interaction.response.send_message(
            "Un bot ne peut pas devenir Helper.", ephemeral=True
        )
        return
    role = await ensure_helper_role(interaction.guild)
    if role is None:
        await interaction.response.send_message(
            "Le rôle Helper n'a pas pu être créé.", ephemeral=True
        )
        return
    await membre.add_roles(role, reason=f"Helper ajouté par {interaction.user}")
    require_database().execute(
        """
        INSERT INTO helper_stats (guild_id, user_id, resolved_tickets, points)
        VALUES (?, ?, 0, 0)
        ON CONFLICT(guild_id, user_id) DO NOTHING
        """,
        (interaction.guild.id, membre.id),
    )
    require_database().commit()
    await reconcile_helper_ticket_permissions(interaction.guild, role)
    await update_helper_leaderboard(interaction.guild)
    await interaction.response.send_message(
        f"✅ {membre.mention} est maintenant **Helper**.", ephemeral=True
    )


@bot.tree.command(
    name="helper-retirer",
    description="Retire le rôle Helper à un membre.",
)
async def helper_remove_command(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
    ):
        return
    if not can_manage_helpers(interaction.user):
        await interaction.response.send_message(
            "Cette commande est réservée au staff supérieur.", ephemeral=True
        )
        return
    role = discord.utils.get(interaction.guild.roles, name=HELPER_ROLE_NAME)
    if role is None or role not in membre.roles:
        await interaction.response.send_message(
            "Ce membre ne possède pas le rôle Helper.", ephemeral=True
        )
        return
    await membre.remove_roles(role, reason=f"Helper retiré par {interaction.user}")
    require_database().execute(
        """
        UPDATE tickets SET claimed_by = NULL
        WHERE guild_id = ? AND claimed_by = ? AND status = 'open'
        """,
        (interaction.guild.id, membre.id),
    )
    require_database().commit()
    await reconcile_helper_ticket_permissions(interaction.guild, role)
    await update_helper_leaderboard(interaction.guild)
    await interaction.response.send_message(
        f"✅ Le rôle Helper a été retiré à {membre.mention}. "
        "Ses tickets ont été remis à disposition.",
        ephemeral=True,
    )


@bot.tree.command(
    name="helper-points-definir",
    description="Définit exactement les points d'un Helper.",
)
async def helper_points_set_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    points: int,
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
    ):
        return
    if not can_manage_helpers(interaction.user):
        await interaction.response.send_message(
            "Cette commande est réservée au staff supérieur.", ephemeral=True
        )
        return
    if points < 0:
        await interaction.response.send_message(
            "Le nombre de points ne peut pas être négatif.", ephemeral=True
        )
        return
    role = await ensure_helper_role(interaction.guild)
    if role is None or role not in membre.roles:
        await interaction.response.send_message(
            "Ce membre doit d'abord recevoir le rôle Helper.", ephemeral=True
        )
        return
    require_database().execute(
        """
        INSERT INTO helper_stats (guild_id, user_id, resolved_tickets, points)
        VALUES (?, ?, 0, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET points = excluded.points
        """,
        (interaction.guild.id, membre.id, points),
    )
    require_database().commit()
    await update_helper_leaderboard(interaction.guild)
    await interaction.response.send_message(
        f"🏆 {membre.mention} possède maintenant exactement "
        f"**{points} point(s) Helper**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="helper-classement",
    description="Actualise le classement des Helpers.",
)
async def helper_leaderboard_command(interaction: discord.Interaction) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
    ):
        return
    if not can_manage_helpers(interaction.user):
        await interaction.response.send_message(
            "Cette commande est réservée au staff supérieur.", ephemeral=True
        )
        return
    await update_helper_leaderboard(interaction.guild)
    await interaction.response.send_message(
        "✅ Classement des Helpers actualisé.", ephemeral=True
    )


@bot.tree.command(
    name="note-ajouter",
    description="Ajoute une note interne au dossier d'un membre.",
)
async def moderation_note_add(
    interaction: discord.Interaction, membre: discord.Member, note: str
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
        or not is_ticket_staff(interaction.user)
        or is_helper(interaction.user)
    ):
        await interaction.response.send_message(
            "Cette commande est réservée au staff supérieur.", ephemeral=True
        )
        return
    cursor = require_database().execute(
        """
        INSERT INTO moderation_notes (
            guild_id, user_id, moderator_id, note, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            interaction.guild.id,
            membre.id,
            interaction.user.id,
            note[:1500],
            int(time.time()),
        ),
    )
    require_database().commit()
    await interaction.response.send_message(
        f"📝 Note interne **#{cursor.lastrowid}** ajoutée au dossier de "
        f"{membre.mention}.",
        ephemeral=True,
    )


@bot.tree.command(
    name="notes-joueur",
    description="Consulte les notes internes d'un membre.",
)
async def moderation_notes_show(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
        or not is_ticket_staff(interaction.user)
        or is_helper(interaction.user)
    ):
        await interaction.response.send_message(
            "Cette commande est réservée au staff supérieur.", ephemeral=True
        )
        return
    rows = require_database().execute(
        """
        SELECT id, moderator_id, note, created_at FROM moderation_notes
        WHERE guild_id = ? AND user_id = ? AND active = 1
        ORDER BY created_at DESC LIMIT 25
        """,
        (interaction.guild.id, membre.id),
    ).fetchall()
    description = "\n\n".join(
        f"**Note #{note_id}** • <t:{created_at}:f> • <@{moderator_id}>\n{note}"
        for note_id, moderator_id, note, created_at in rows
    )[:4000]
    await interaction.response.send_message(
        embed=discord.Embed(
            title=f"📝 Notes internes • {membre.display_name}",
            description=description or "Aucune note interne active.",
            colour=discord.Colour.dark_grey(),
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="note-retirer",
    description="Archive une note interne par son numéro.",
)
async def moderation_note_remove(
    interaction: discord.Interaction, identifiant: int
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
        or not is_ticket_staff(interaction.user)
        or is_helper(interaction.user)
    ):
        await interaction.response.send_message(
            "Cette commande est réservée au staff supérieur.", ephemeral=True
        )
        return
    cursor = require_database().execute(
        """
        UPDATE moderation_notes
        SET active = 0, removed_by = ?, removed_at = ?
        WHERE id = ? AND guild_id = ? AND active = 1
        """,
        (
            interaction.user.id,
            int(time.time()),
            identifiant,
            interaction.guild.id,
        ),
    )
    require_database().commit()
    await interaction.response.send_message(
        (
            f"✅ Note **#{identifiant}** archivée."
            if cursor.rowcount
            else "Note active introuvable."
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="staff-statistiques",
    description="Affiche les statistiques mensuelles du staff.",
)
async def staff_statistics(
    interaction: discord.Interaction,
    membre: discord.Member | None = None,
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
        or not is_ticket_staff(interaction.user)
        or is_helper(interaction.user)
    ):
        await interaction.response.send_message(
            "Cette commande est réservée au staff supérieur.", ephemeral=True
        )
        return
    start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    since = int(start.timestamp())
    connection = require_database()
    if membre is not None:
        sanctions = connection.execute(
            """
            SELECT COUNT(*) FROM sanctions
            WHERE guild_id = ? AND moderator_id = ? AND created_at >= ?
            """,
            (interaction.guild.id, membre.id, since),
        ).fetchone()[0]
        claimed = connection.execute(
            """
            SELECT COUNT(*) FROM tickets
            WHERE guild_id = ? AND claimed_by = ? AND claimed_at >= ?
            """,
            (interaction.guild.id, membre.id, since),
        ).fetchone()[0]
        closed = connection.execute(
            """
            SELECT COUNT(*) FROM tickets
            WHERE guild_id = ? AND closed_by = ? AND closed_at >= ?
            """,
            (interaction.guild.id, membre.id, since),
        ).fetchone()[0]
        average_response = connection.execute(
            """
            SELECT AVG(claimed_at - created_at) FROM tickets
            WHERE guild_id = ? AND claimed_by = ? AND claimed_at >= ?
                  AND claimed_at IS NOT NULL
            """,
            (interaction.guild.id, membre.id, since),
        ).fetchone()[0]
        notes = connection.execute(
            """
            SELECT COUNT(*) FROM moderation_notes
            WHERE guild_id = ? AND moderator_id = ? AND created_at >= ?
            """,
            (interaction.guild.id, membre.id, since),
        ).fetchone()[0]
        description = (
            f"Sanctions enregistrées : **{sanctions}**\n"
            f"Tickets claim : **{claimed}**\n"
            f"Tickets clôturés : **{closed}**\n"
            f"Temps de réponse moyen : "
            f"**{format_duration(int(average_response or 0))}**\n"
            f"Notes internes : **{notes}**"
        )
        title = f"📊 Statistiques • {membre.display_name}"
    else:
        rows = connection.execute(
            """
            SELECT moderator_id, COUNT(*) AS actions FROM sanctions
            WHERE guild_id = ? AND moderator_id IS NOT NULL AND created_at >= ?
            GROUP BY moderator_id ORDER BY actions DESC LIMIT 15
            """,
            (interaction.guild.id, since),
        ).fetchall()
        ticket_rows = dict(
            connection.execute(
                """
                SELECT closed_by, COUNT(*) FROM tickets
                WHERE guild_id = ? AND closed_by IS NOT NULL AND closed_at >= ?
                GROUP BY closed_by
                """,
                (interaction.guild.id, since),
            ).fetchall()
        )
        totals: dict[int, int] = {
            moderator_id: actions for moderator_id, actions in rows
        }
        for user_id, tickets in ticket_rows.items():
            totals[user_id] = totals.get(user_id, 0) + tickets
        ranking = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        description = "\n".join(
            f"`#{position}` <@{user_id}> • **{score} action(s)**"
            for position, (user_id, score) in enumerate(ranking[:15], start=1)
        ) or "Aucune action enregistrée ce mois-ci."
        title = "📊 Classement mensuel du staff"
    embed = discord.Embed(
        title=title,
        description=description,
        colour=discord.Colour.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"Depuis le {start.strftime('%d/%m/%Y')} • données internes")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="admin-commandes",
    description="Publie la liste des commandes d'administration.",
)
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def admin_commands_command(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="🛠️ Commandes d'administration de RadarokBot",
        description=(
            "Toutes les commandes sensibles utilisent des tirets et sont protégées "
            "par les permissions Discord et les vérifications du bot."
        ),
        colour=discord.Colour.red(),
    )
    embed.add_field(
        name="⚖️ Modération",
        value=(
            "`/warn` • ajouter un avertissement\n"
            "`/warns` • consulter les warns — accessible aux helpers\n"
            "`/warn-retirer` • retirer un avertissement\n"
            "`/clear` • supprimer un nombre précis de messages\n"
            "`/timeout` • placer un membre en timeout\n"
            "`/timeout-retirer` • retirer un timeout\n"
            "`/sanctions` • historique complet\n"
            "`/note-ajouter`, `/notes-joueur`, `/note-retirer`\n"
            "`/staff-statistiques` • activité mensuelle du staff\n"
            "`/infos-joueur` • informations — accessible aux helpers"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎉 Giveaways",
        value=(
            "`/giveaway-creer`\n"
            "`/giveaway-terminer`\n"
            "`/giveaway-reroll`\n"
            "`/giveaway-annuler`"
        ),
        inline=False,
    )
    embed.add_field(
        name="🆘 Gestion des Helpers",
        value=(
            "`/helper-ajouter`\n"
            "`/helper-retirer`\n"
            "`/helper-points-definir`\n"
            "`/helper-classement`"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎪 Événements",
        value=(
            "`/evenement-creer`\n"
            "`/evenement-annuler`\n"
            "`/evenement-terminer`\n"
            "`/evenement-resultats`"
        ),
        inline=False,
    )
    embed.add_field(
        name="🏴‍☠️ Équipages, niveaux et invitations",
        value=(
            "`/equipage-creer-pour` • créer un équipage pour un membre\n"
            "`/suggestion-statut` • décision officielle\n"
            "`/niveau-donner`\n"
            "`/niveau-reinitialiser`\n"
            "`/invites-definir`"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎫 Gestion par boutons",
        value=(
            "Claim, fermeture et transmission des tickets ; acceptation ou refus "
            "des candidatures d'équipages ; contrôles persistants des événements "
            "et giveaways."
        ),
        inline=False,
    )
    embed.set_footer(
        text="Le rôle Helper ne possède aucune autre commande de modération"
    )
    await interaction.response.send_message(embed=embed)


async def refresh_suggestion_message(
    guild: discord.Guild, suggestion_id: int
) -> None:
    connection = require_database()
    row = connection.execute(
        """
        SELECT channel_id, message_id, title, description, user_id, status,
               staff_id, staff_response, created_at
        FROM suggestions WHERE id = ? AND guild_id = ?
        """,
        (suggestion_id, guild.id),
    ).fetchone()
    if row is None or row[1] is None:
        return
    channel = guild.get_channel(row[0])
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(row[1])
    except discord.HTTPException:
        return
    votes = connection.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN vote = 1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN vote = -1 THEN 1 ELSE 0 END), 0)
        FROM suggestion_votes WHERE suggestion_id = ?
        """,
        (suggestion_id,),
    ).fetchone()
    status_labels = {
        "pending": "🟡 En attente",
        "accepted": "🟢 Acceptée",
        "rejected": "🔴 Refusée",
        "done": "✅ Réalisée",
    }
    colours = {
        "pending": discord.Colour.gold(),
        "accepted": discord.Colour.green(),
        "rejected": discord.Colour.red(),
        "done": discord.Colour.blurple(),
    }
    embed = discord.Embed(
        title=f"💡 Suggestion #{suggestion_id} • {row[2]}",
        description=row[3],
        colour=colours.get(row[5], discord.Colour.gold()),
        timestamp=datetime.fromtimestamp(row[8], timezone.utc),
    )
    embed.add_field(name="Proposée par", value=f"<@{row[4]}>", inline=True)
    embed.add_field(
        name="Votes",
        value=f"👍 **{votes[0]}** • 👎 **{votes[1]}**",
        inline=True,
    )
    embed.add_field(
        name="Statut",
        value=status_labels.get(row[5], row[5]),
        inline=True,
    )
    if row[7]:
        embed.add_field(
            name="Réponse officielle",
            value=f"{row[7]}\n\n— <@{row[6]}>",
            inline=False,
        )
    embed.set_footer(text="Vote modifiable • un seul vote par membre")
    await message.edit(
        embed=embed,
        view=SuggestionVoteView() if row[5] == "pending" else None,
    )


class SuggestionVoteView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def record_vote(
        self, interaction: discord.Interaction, vote: int
    ) -> None:
        if (
            interaction.guild is None
            or interaction.message is None
            or interaction.user.bot
        ):
            return
        connection = require_database()
        suggestion = connection.execute(
            """
            SELECT id, user_id, status FROM suggestions
            WHERE guild_id = ? AND message_id = ?
            """,
            (interaction.guild.id, interaction.message.id),
        ).fetchone()
        if suggestion is None or suggestion[2] != "pending":
            await interaction.response.send_message(
                "Les votes sont fermés pour cette suggestion.", ephemeral=True
            )
            return
        if suggestion[1] == interaction.user.id:
            await interaction.response.send_message(
                "Tu ne peux pas voter pour ta propre suggestion.", ephemeral=True
            )
            return
        previous = connection.execute(
            """
            SELECT vote FROM suggestion_votes
            WHERE suggestion_id = ? AND user_id = ?
            """,
            (suggestion[0], interaction.user.id),
        ).fetchone()
        if previous is not None and previous[0] == vote:
            connection.execute(
                """
                DELETE FROM suggestion_votes
                WHERE suggestion_id = ? AND user_id = ?
                """,
                (suggestion[0], interaction.user.id),
            )
            result = "Ton vote a été retiré."
        else:
            connection.execute(
                """
                INSERT INTO suggestion_votes (
                    suggestion_id, user_id, vote, voted_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(suggestion_id, user_id) DO UPDATE SET
                    vote = excluded.vote, voted_at = excluded.voted_at
                """,
                (
                    suggestion[0],
                    interaction.user.id,
                    vote,
                    int(time.time()),
                ),
            )
            result = "Ton vote a été enregistré."
        connection.commit()
        await interaction.response.send_message(result, ephemeral=True)
        await refresh_suggestion_message(interaction.guild, suggestion[0])

    @discord.ui.button(
        label="Pour",
        emoji="👍",
        style=discord.ButtonStyle.success,
        custom_id="radarok:suggestion:up",
    )
    async def vote_up(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.record_vote(interaction, 1)

    @discord.ui.button(
        label="Contre",
        emoji="👎",
        style=discord.ButtonStyle.danger,
        custom_id="radarok:suggestion:down",
    )
    async def vote_down(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.record_vote(interaction, -1)


class SuggestionModal(discord.ui.Modal):
    def __init__(self) -> None:
        super().__init__(title="💡 Nouvelle suggestion", timeout=600)
        self.suggestion_title = discord.ui.TextInput(
            label="Titre",
            min_length=5,
            max_length=100,
            placeholder="Résume clairement ton idée",
        )
        self.details = discord.ui.TextInput(
            label="Description",
            min_length=20,
            max_length=1500,
            style=discord.TextStyle.paragraph,
            placeholder="Explique l'idée, son intérêt et son fonctionnement",
        )
        self.add_item(self.suggestion_title)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(
            interaction.channel, discord.TextChannel
        ):
            return
        connection = require_database()
        now = int(time.time())
        cursor = connection.execute(
            """
            INSERT INTO suggestions (
                guild_id, user_id, channel_id, title, description,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interaction.guild.id,
                interaction.user.id,
                interaction.channel.id,
                str(self.suggestion_title),
                str(self.details),
                now,
                now,
            ),
        )
        suggestion_id = cursor.lastrowid
        connection.commit()
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title=f"💡 Suggestion #{suggestion_id} • {self.suggestion_title}",
            description=str(self.details),
            colour=discord.Colour.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="Proposée par", value=interaction.user.mention, inline=True
        )
        embed.add_field(name="Votes", value="👍 **0** • 👎 **0**", inline=True)
        embed.add_field(name="Statut", value="🟡 En attente", inline=True)
        embed.set_footer(text="Vote modifiable • un seul vote par membre")
        message = await interaction.channel.send(
            embed=embed, view=SuggestionVoteView()
        )
        connection.execute(
            "UPDATE suggestions SET message_id = ? WHERE id = ?",
            (message.id, suggestion_id),
        )
        connection.commit()
        await interaction.followup.send(
            f"✅ Suggestion publiée : {message.jump_url}", ephemeral=True
        )


@bot.tree.command(
    name="suggestion",
    description="Ouvre le formulaire pour proposer une idée.",
)
async def suggestion_create_command(interaction: discord.Interaction) -> None:
    if (
        not isinstance(interaction.channel, discord.TextChannel)
        or interaction.channel.name != SUGGESTIONS_CHANNEL_NAME
    ):
        await interaction.response.send_message(
            f"Utilise cette commande dans `{SUGGESTIONS_CHANNEL_NAME}`.",
            ephemeral=True,
        )
        return
    await interaction.response.send_modal(SuggestionModal())


@bot.tree.command(
    name="suggestion-statut",
    description="Donne une décision officielle à une suggestion.",
)
@app_commands.choices(
    statut=[
        app_commands.Choice(name="Acceptée", value="accepted"),
        app_commands.Choice(name="Refusée", value="rejected"),
        app_commands.Choice(name="Réalisée", value="done"),
        app_commands.Choice(name="Remettre en attente", value="pending"),
    ]
)
async def suggestion_status_command(
    interaction: discord.Interaction,
    identifiant: int,
    statut: app_commands.Choice[str],
    reponse: str,
) -> None:
    if (
        interaction.guild is None
        or not isinstance(interaction.user, discord.Member)
        or not is_ticket_staff(interaction.user)
        or is_helper(interaction.user)
    ):
        await interaction.response.send_message(
            "Cette commande est réservée au staff supérieur.", ephemeral=True
        )
        return
    cursor = require_database().execute(
        """
        UPDATE suggestions
        SET status = ?, staff_id = ?, staff_response = ?, updated_at = ?
        WHERE id = ? AND guild_id = ?
        """,
        (
            statut.value,
            interaction.user.id,
            reponse[:1000],
            int(time.time()),
            identifiant,
            interaction.guild.id,
        ),
    )
    require_database().commit()
    if not cursor.rowcount:
        await interaction.response.send_message(
            "Suggestion introuvable.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        f"✅ Suggestion **#{identifiant}** mise à jour.", ephemeral=True
    )
    await refresh_suggestion_message(interaction.guild, identifiant)


class CommunityEventView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="S'inscrire",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="radarok:event:join",
    )
    async def join(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if (
            interaction.message is None
            or interaction.guild is None
            or not isinstance(interaction.user, discord.Member)
        ):
            return
        connection = require_database()
        event = connection.execute(
            """
            SELECT starts_at, capacity, status FROM community_events
            WHERE message_id = ?
            """,
            (interaction.message.id,),
        ).fetchone()
        if event is None or event[2] != "scheduled" or event[0] <= int(time.time()):
            await interaction.response.send_message(
                "Les inscriptions à cet événement sont fermées.", ephemeral=True
            )
            return
        existing = connection.execute(
            """
            SELECT 1 FROM community_event_entries
            WHERE message_id = ? AND user_id = ?
            """,
            (interaction.message.id, interaction.user.id),
        ).fetchone()
        if existing:
            connection.execute(
                """
                DELETE FROM community_event_entries
                WHERE message_id = ? AND user_id = ?
                """,
                (interaction.message.id, interaction.user.id),
            )
            connection.commit()
            await interaction.response.send_message(
                "Ton inscription a été retirée.", ephemeral=True
            )
            return
        count = connection.execute(
            """
            SELECT COUNT(*) FROM community_event_entries
            WHERE message_id = ?
            """,
            (interaction.message.id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO community_event_entries (message_id, user_id, joined_at)
            VALUES (?, ?, ?)
            """,
            (interaction.message.id, interaction.user.id, int(time.time())),
        )
        connection.commit()
        position = count + 1
        if position <= event[1]:
            message = f"✅ Inscription confirmée, place **#{position}**."
        else:
            message = (
                f"🕒 L'événement est complet. Tu es **#{position - event[1]}** "
                "sur la liste d'attente."
            )
        await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(
        label="Participants",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        custom_id="radarok:event:participants",
    )
    async def participants(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if interaction.message is None or interaction.guild is None:
            return
        event = require_database().execute(
            "SELECT capacity FROM community_events WHERE message_id = ?",
            (interaction.message.id,),
        ).fetchone()
        if event is None:
            return
        rows = require_database().execute(
            """
            SELECT user_id FROM community_event_entries
            WHERE message_id = ? ORDER BY joined_at LIMIT 50
            """,
            (interaction.message.id,),
        ).fetchall()
        confirmed = [
            f"<@{user_id}>" for (user_id,) in rows[: event[0]]
        ]
        waiting = [
            f"<@{user_id}>" for (user_id,) in rows[event[0] :]
        ]
        await interaction.response.send_message(
            f"**Participants ({len(confirmed)}/{event[0]})**\n"
            f"{', '.join(confirmed) or 'Aucun'}\n\n"
            f"**Liste d'attente ({len(waiting)})**\n"
            f"{', '.join(waiting) or 'Aucune'}",
            ephemeral=True,
        )


@bot.tree.command(
    name="evenement-creer",
    description="Crée un événement avec inscriptions.",
)
@app_commands.default_permissions(manage_events=True)
@app_commands.checks.has_permissions(manage_events=True)
@app_commands.describe(
    nom="Nom de l'événement",
    debut="Date et heure de Paris : JJ/MM/AAAA HH:MM",
    places="Nombre de places confirmées",
    description="Description et conditions",
)
async def event_create(
    interaction: discord.Interaction,
    nom: str,
    debut: str,
    places: app_commands.Range[int, 2, 500],
    description: str,
) -> None:
    if interaction.guild is None:
        return
    try:
        starts_at = datetime.strptime(debut, "%d/%m/%Y %H:%M").replace(
            tzinfo=PARIS_TIMEZONE
        )
    except ValueError:
        await interaction.response.send_message(
            "Format invalide. Utilise `JJ/MM/AAAA HH:MM`, par exemple "
            "`15/08/2026 20:30`.",
            ephemeral=True,
        )
        return
    if starts_at <= datetime.now(PARIS_TIMEZONE) + timedelta(minutes=5):
        await interaction.response.send_message(
            "L'événement doit commencer dans plus de cinq minutes.", ephemeral=True
        )
        return
    channel = discord.utils.get(
        interaction.guild.text_channels, name=EVENT_ANNOUNCEMENT_CHANNEL_NAME
    )
    if channel is None:
        await interaction.response.send_message(
            "Le salon d'annonces événement est absent. Contacte un administrateur.",
            ephemeral=True,
        )
        return
    timestamp = int(starts_at.timestamp())
    embed = discord.Embed(
        title=f"🎪 {nom[:180]}",
        description=description[:3000],
        colour=discord.Colour.purple(),
    )
    embed.add_field(
        name="📅 Début", value=f"<t:{timestamp}:F> • <t:{timestamp}:R>", inline=False
    )
    embed.add_field(name="👥 Places", value=str(places), inline=True)
    embed.add_field(
        name="🎙️ Organisé par", value=interaction.user.mention, inline=True
    )
    embed.set_footer(text="Inscris-toi avec le bouton • Liste d'attente automatique")
    await interaction.response.defer(ephemeral=True)
    message = await channel.send(embed=embed, view=CommunityEventView())
    require_database().execute(
        """
        INSERT INTO community_events (
            message_id, guild_id, channel_id, host_id, name,
            description, starts_at, capacity, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.id,
            interaction.guild.id,
            channel.id,
            interaction.user.id,
            nom[:180],
            description[:3000],
            timestamp,
            places,
            int(time.time()),
        ),
    )
    require_database().commit()
    await interaction.followup.send(
        f"Événement créé : {message.jump_url}", ephemeral=True
    )


@bot.tree.command(name="evenement-annuler", description="Annule un événement.")
@app_commands.default_permissions(manage_events=True)
@app_commands.checks.has_permissions(manage_events=True)
async def event_cancel(
    interaction: discord.Interaction, message_id: str, raison: str
) -> None:
    if interaction.guild is None or not message_id.isdigit():
        await interaction.response.send_message(
            "Identifiant de message invalide.", ephemeral=True
        )
        return
    row = require_database().execute(
        """
        SELECT channel_id, name FROM community_events
        WHERE message_id = ? AND guild_id = ? AND status = 'scheduled'
        """,
        (int(message_id), interaction.guild.id),
    ).fetchone()
    if row is None:
        await interaction.response.send_message(
            "Événement actif introuvable.", ephemeral=True
        )
        return
    require_database().execute(
        "UPDATE community_events SET status = 'cancelled' WHERE message_id = ?",
        (int(message_id),),
    )
    require_database().commit()
    channel = interaction.guild.get_channel(row[0])
    if isinstance(channel, discord.TextChannel):
        await channel.send(
            f"❌ L'événement **{row[1]}** est annulé.\nMotif : {raison[:1000]}"
        )
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(view=None)
        except discord.HTTPException:
            pass
    await interaction.response.send_message("Événement annulé.", ephemeral=True)


@bot.tree.command(name="evenement-terminer", description="Clôture un événement terminé.")
@app_commands.default_permissions(manage_events=True)
@app_commands.checks.has_permissions(manage_events=True)
async def event_finish(
    interaction: discord.Interaction, message_id: str
) -> None:
    if interaction.guild is None or not message_id.isdigit():
        await interaction.response.send_message(
            "Identifiant de message invalide.", ephemeral=True
        )
        return
    row = require_database().execute(
        """
        SELECT channel_id, name FROM community_events
        WHERE message_id = ? AND guild_id = ?
          AND status IN ('scheduled', 'started')
        """,
        (int(message_id), interaction.guild.id),
    ).fetchone()
    if row is None:
        await interaction.response.send_message(
            "Événement introuvable ou déjà clôturé.", ephemeral=True
        )
        return
    require_database().execute(
        "UPDATE community_events SET status = 'finished' WHERE message_id = ?",
        (int(message_id),),
    )
    require_database().commit()
    channel = interaction.guild.get_channel(row[0])
    if isinstance(channel, discord.TextChannel):
        await channel.send(f"🏁 L'événement **{row[1]}** est maintenant terminé.")
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(view=None)
        except discord.HTTPException:
            pass
    await interaction.response.send_message("Événement clôturé.", ephemeral=True)


@bot.tree.command(
    name="evenement-resultats",
    description="Publie le podium et attribue les rôles de l'événement.",
)
@app_commands.default_permissions(manage_events=True)
@app_commands.checks.has_permissions(manage_events=True)
async def event_results(
    interaction: discord.Interaction,
    message_id: str,
    premier: discord.Member,
    deuxieme: discord.Member | None = None,
    troisieme: discord.Member | None = None,
) -> None:
    if interaction.guild is None or not message_id.isdigit():
        await interaction.response.send_message(
            "Identifiant de message invalide.", ephemeral=True
        )
        return
    row = require_database().execute(
        """
        SELECT channel_id, name FROM community_events
        WHERE message_id = ? AND guild_id = ? AND status != 'cancelled'
        """,
        (int(message_id), interaction.guild.id),
    ).fetchone()
    if row is None:
        await interaction.response.send_message(
            "Événement introuvable.", ephemeral=True
        )
        return
    podium = [
        (premier, "🥇・Champion événement", "🥇"),
        (deuxieme, "🥈・Finaliste événement", "🥈"),
        (troisieme, "🥉・Troisième événement", "🥉"),
    ]
    if len({member.id for member, _, _ in podium if member is not None}) != len(
        [member for member, _, _ in podium if member is not None]
    ):
        await interaction.response.send_message(
            "Un membre ne peut pas occuper plusieurs places.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True)
    result_lines = []
    for member, role_name, medal in podium:
        if member is None:
            continue
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if role is not None:
            try:
                await member.add_roles(
                    role, reason=f"Podium de l'événement {row[1]}"
                )
            except discord.HTTPException:
                logging.exception("Impossible d'attribuer %s", role_name)
        result_lines.append(f"{medal} {member.mention}")
    require_database().execute(
        "UPDATE community_events SET status = 'finished' WHERE message_id = ?",
        (int(message_id),),
    )
    require_database().commit()
    channel = interaction.guild.get_channel(row[0])
    if isinstance(channel, discord.TextChannel):
        await channel.send(
            embed=discord.Embed(
                title=f"🏆 Résultats • {row[1]}",
                description="\n".join(result_lines),
                colour=discord.Colour.gold(),
            )
        )
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(view=None)
        except discord.HTTPException:
            pass
    await interaction.followup.send(
        "Podium publié et rôles attribués.", ephemeral=True
    )


@bot.tree.command(
    name="niveau",
    description="Affiche ton niveau ou celui d'un membre.",
)
@app_commands.guild_only()
@app_commands.describe(membre="Membre dont tu souhaites voir la progression")
async def level_command(
    interaction: discord.Interaction,
    membre: discord.Member | None = None,
) -> None:
    if interaction.guild is None:
        return
    target = membre or interaction.user
    if not isinstance(target, discord.Member):
        return

    message_xp, voice_xp, bonus_xp, voice_seconds, total_messages = get_member_stats(
        interaction.guild.id, target.id
    )
    total_xp = message_xp + voice_xp + bonus_xp
    level = calculate_level(total_xp)
    current_threshold = level * level * 100
    next_threshold = (level + 1) * (level + 1) * 100
    progress = total_xp - current_threshold
    required = next_threshold - current_threshold
    position_row = require_database().execute(
        """
        SELECT COUNT(*) + 1
        FROM member_stats
        WHERE guild_id = ? AND message_xp + voice_xp + bonus_xp > ?
        """,
        (interaction.guild.id, total_xp),
    ).fetchone()
    leaderboard_position = int(position_row[0]) if position_row else 1

    await interaction.response.defer(thinking=True)
    try:
        card = await asyncio.to_thread(
            generate_level_card,
            username=target.display_name,
            level=level,
            total_xp=total_xp,
            progress=progress,
            required=required,
            total_messages=total_messages,
            voice_seconds=voice_seconds,
            leaderboard_position=leaderboard_position,
        )
    except Exception:
        logging.exception("Impossible de générer la carte de niveau")
        await interaction.followup.send(
            "La carte de niveau n'a pas pu être générée.", ephemeral=True
        )
        return
    await interaction.followup.send(
        file=discord.File(card, filename=f"niveau-{target.id}.png")
    )


@bot.tree.command(
    name="classement",
    description="Affiche les membres les plus actifs du serveur.",
)
@app_commands.guild_only()
async def leaderboard_command(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    rows = require_database().execute(
        """
        SELECT user_id, message_xp + voice_xp + bonus_xp AS total_xp,
               voice_seconds, total_messages
        FROM member_stats
        WHERE guild_id = ?
        ORDER BY total_xp DESC
        LIMIT 10
        """,
        (interaction.guild.id,),
    ).fetchall()

    if not rows:
        await interaction.response.send_message(
            "Le classement est encore vide.", ephemeral=True
        )
        return

    lines = []
    medals = ("🥇", "🥈", "🥉")
    for position, (user_id, total_xp, voice_seconds, total_messages) in enumerate(
        rows, start=1
    ):
        member = interaction.guild.get_member(user_id)
        name = member.display_name if member is not None else f"Membre {user_id}"
        marker = medals[position - 1] if position <= 3 else f"`#{position}`"
        lines.append(
            f"{marker} **{name}** — niveau {calculate_level(total_xp)} "
            f"• {total_xp:,} XP • {format_duration(voice_seconds)}"
        )

    embed = discord.Embed(
        title="🏆 Classement de la communauté",
        description="\n".join(lines),
        colour=discord.Colour.gold(),
    )
    embed.set_footer(text="XP gagné avec les messages et l'activité vocale")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="invites",
    description="Affiche le nombre d'invitations d'un membre.",
)
@app_commands.guild_only()
@app_commands.describe(membre="Membre dont tu souhaites voir les invitations")
async def invites_command(
    interaction: discord.Interaction,
    membre: discord.Member | None = None,
) -> None:
    if interaction.guild is None:
        return
    target = membre or interaction.user
    if not isinstance(target, discord.Member):
        return
    count = get_invite_count(interaction.guild.id, target.id)
    current_tier = next(
        (
            (required, role_name, bonus)
            for required, role_name, bonus in INVITE_ROLE_TIERS
            if count >= required
        ),
        None,
    )
    next_tier = next(
        (
            (required, role_name, bonus)
            for required, role_name, bonus in reversed(INVITE_ROLE_TIERS)
            if count < required
        ),
        None,
    )
    description = f"{target.mention} possède **{count} invitation(s)**."
    if current_tier is not None:
        description += (
            f"\nRôle actuel : **{current_tier[1]}** "
            f"• bonus giveaway **+{current_tier[2]:g} chance**"
        )
    if next_tier is not None:
        description += (
            f"\nProchain palier : **{next_tier[1]}** à "
            f"**{next_tier[0]} invitations**"
        )
    embed = discord.Embed(
        title="🔗 Invitations",
        description=description,
        colour=discord.Colour.teal(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="invites-definir",
    description="Définit le nombre exact d'invitations d'un membre.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    membre="Membre à modifier",
    nombre="Nouveau nombre exact d'invitations",
)
async def set_invites_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    nombre: int,
) -> None:
    if interaction.guild is None:
        return
    if nombre < 0:
        await interaction.response.send_message(
            "Le nombre d'invitations ne peut pas être négatif.", ephemeral=True
        )
        return
    connection = require_database()
    connection.execute(
        """
        INSERT INTO invite_stats (guild_id, user_id, invite_count)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            invite_count = excluded.invite_count
        """,
        (interaction.guild.id, membre.id, nombre),
    )
    connection.commit()
    await update_invite_role(membre)
    await interaction.response.send_message(
        f"✅ {membre.mention} possède maintenant exactement "
        f"**{nombre} invitation(s)**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="giveaway-creer",
    description="Crée un giveaway complet avec tirage pondéré.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    lot="Lot à gagner",
    duree="Durée, par exemple 30m, 2h ou 1d12h",
    gagnants="Nombre de gagnants",
    salon="Salon où publier le giveaway",
)
async def create_giveaway_command(
    interaction: discord.Interaction,
    lot: str,
    duree: str,
    gagnants: app_commands.Range[int, 1, 20] = 1,
    salon: discord.TextChannel | None = None,
) -> None:
    if interaction.guild is None:
        return
    duration_seconds = parse_duration(duree)
    if duration_seconds is None:
        await interaction.response.send_message(
            "Durée invalide. Exemples : `30m`, `2h`, `1d12h` "
            "(minimum 10 secondes, maximum 1 an).",
            ephemeral=True,
        )
        return
    target_channel = salon or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message(
            "Choisis un salon textuel.", ephemeral=True
        )
        return

    ends_at = int(time.time()) + duration_seconds
    embed = discord.Embed(
        title=f"🎉 GIVEAWAY • {lot[:180]}",
        description=(
            f"Clique sur **Participer** pour tenter ta chance !\n\n"
            f"⏳ Fin : <t:{ends_at}:F> • <t:{ends_at}:R>\n"
            f"🏆 Gagnant(s) : **{gagnants}**\n"
            f"🎙️ Organisé par : {interaction.user.mention}\n\n"
            "**Bonus de chances**\n"
            "🥉 5 invitations : +0,5\n"
            "🥈 10 invitations : +1\n"
            "🥇 15 invitations : +1,5\n"
            "💎 20 invitations : +2\n"
            "💎 Booster du serveur : +1"
        ),
        colour=discord.Colour.magenta(),
    )
    embed.set_footer(
        text="Les rôles d'invitations ne se cumulent pas • Le bonus Booster se cumule"
    )
    await interaction.response.defer(ephemeral=True, thinking=True)
    message = await target_channel.send(embed=embed, view=GiveawayView())
    connection = require_database()
    connection.execute(
        """
        INSERT INTO giveaways (
            message_id, guild_id, channel_id, host_id, prize,
            winners_count, ends_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.id,
            interaction.guild.id,
            target_channel.id,
            interaction.user.id,
            lot[:180],
            gagnants,
            ends_at,
            int(time.time()),
        ),
    )
    connection.commit()
    await interaction.followup.send(
        f"Giveaway créé : {message.jump_url}", ephemeral=True
    )


@bot.tree.command(
    name="giveaway-terminer",
    description="Termine immédiatement un giveaway.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(message_id="Identifiant du message du giveaway")
async def end_giveaway_command(
    interaction: discord.Interaction, message_id: str
) -> None:
    if not message_id.isdigit() or get_giveaway(int(message_id)) is None:
        await interaction.response.send_message(
            "Giveaway introuvable.", ephemeral=True
        )
        return
    giveaway = get_giveaway(int(message_id))
    if giveaway is None or giveaway[6] != "active":
        await interaction.response.send_message(
            "Ce giveaway est déjà terminé.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    winners = await finish_giveaway(int(message_id))
    await interaction.followup.send(
        f"Giveaway terminé avec **{len(winners)} gagnant(s)**.", ephemeral=True
    )


@bot.tree.command(
    name="giveaway-reroll",
    description="Effectue un nouveau tirage d'un giveaway terminé.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(message_id="Identifiant du message du giveaway")
async def reroll_giveaway_command(
    interaction: discord.Interaction, message_id: str
) -> None:
    if not message_id.isdigit():
        await interaction.response.send_message(
            "Identifiant invalide.", ephemeral=True
        )
        return
    giveaway = get_giveaway(int(message_id))
    if giveaway is None or giveaway[6] != "ended":
        await interaction.response.send_message(
            "Ce giveaway est introuvable ou encore actif.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    winners = await finish_giveaway(int(message_id), reroll=True)
    await interaction.followup.send(
        f"Nouveau tirage effectué avec **{len(winners)} gagnant(s)**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="giveaway-annuler",
    description="Annule un giveaway sans tirer de gagnant.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(message_id="Identifiant du message du giveaway")
async def cancel_giveaway_command(
    interaction: discord.Interaction, message_id: str
) -> None:
    if not message_id.isdigit():
        await interaction.response.send_message(
            "Identifiant invalide.", ephemeral=True
        )
        return
    giveaway = get_giveaway(int(message_id))
    if giveaway is None or giveaway[6] != "active":
        await interaction.response.send_message(
            "Ce giveaway est introuvable ou n'est plus actif.", ephemeral=True
        )
        return
    guild_id, channel_id, _, prize, _, _, _ = giveaway
    guild = bot.get_guild(guild_id)
    channel = guild.get_channel(channel_id) if guild is not None else None
    require_database().execute(
        "UPDATE giveaways SET status = 'cancelled' WHERE message_id = ?",
        (int(message_id),),
    )
    require_database().commit()
    if isinstance(channel, discord.TextChannel):
        try:
            message = await channel.fetch_message(int(message_id))
            embed = message.embeds[0] if message.embeds else discord.Embed()
            embed.title = f"🚫 Giveaway annulé • {prize}"
            embed.colour = discord.Colour.red()
            await message.edit(embed=embed, view=GiveawayView())
        except discord.HTTPException:
            pass
    await interaction.response.send_message(
        "Giveaway annulé sans tirage.", ephemeral=True
    )


@bot.tree.command(
    name="niveau-donner",
    description="Accorde un ou plusieurs niveaux à un membre.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    membre="Membre qui recevra les niveaux",
    niveaux="Nombre de niveaux à ajouter",
)
async def give_levels_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    niveaux: int,
) -> None:
    if interaction.guild is None:
        return
    if membre.bot:
        await interaction.response.send_message(
            "Les niveaux ne peuvent pas être attribués à un bot.", ephemeral=True
        )
        return
    if niveaux < 1:
        await interaction.response.send_message(
            "Le nombre de niveaux doit être supérieur à zéro.", ephemeral=True
        )
        return

    message_xp, voice_xp, bonus_xp, _, _ = get_member_stats(
        interaction.guild.id, membre.id
    )
    total_xp = message_xp + voice_xp + bonus_xp
    current_level = calculate_level(total_xp)
    target_level = current_level + niveaux
    target_xp = target_level * target_level * 100
    if target_xp > 9_223_372_036_854_775_807:
        await interaction.response.send_message(
            "Ce nombre dépasse la capacité maximale de la base de données.",
            ephemeral=True,
        )
        return
    granted_xp = target_xp - total_xp

    connection = require_database()
    connection.execute(
        """
        INSERT INTO member_stats (guild_id, user_id, bonus_xp)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            bonus_xp = bonus_xp + excluded.bonus_xp
        """,
        (interaction.guild.id, membre.id, granted_xp),
    )
    connection.commit()
    await update_level_role(membre)

    await interaction.response.send_message(
        f"✅ {membre.mention} passe du niveau **{current_level}** au niveau "
        f"**{target_level}** grâce à un bonus de **{granted_xp:,} XP**.",
        ephemeral=True,
    )


@bot.tree.command(
    name="niveau-reinitialiser",
    description="Remet à zéro le niveau et l'XP d'un membre.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(membre="Membre dont le niveau sera réinitialisé")
async def reset_level_command(
    interaction: discord.Interaction,
    membre: discord.Member,
) -> None:
    if interaction.guild is None:
        return
    if membre.bot:
        await interaction.response.send_message(
            "Les niveaux des bots ne sont pas gérés.", ephemeral=True
        )
        return

    message_xp, voice_xp, bonus_xp, _, _ = get_member_stats(
        interaction.guild.id, membre.id
    )
    previous_xp = message_xp + voice_xp + bonus_xp
    previous_level = calculate_level(previous_xp)
    connection = require_database()
    connection.execute(
        """
        INSERT INTO member_stats (
            guild_id, user_id, message_xp, voice_xp, bonus_xp
        )
        VALUES (?, ?, 0, 0, 0)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            message_xp = 0,
            voice_xp = 0,
            bonus_xp = 0,
            last_message_xp = 0
        """,
        (interaction.guild.id, membre.id),
    )
    connection.commit()
    await update_level_role(membre)

    await interaction.response.send_message(
        f"♻️ Le niveau de {membre.mention} a été réinitialisé : "
        f"niveau **{previous_level} → 0** et **{previous_xp:,} XP** retirés.",
        ephemeral=True,
    )


async def _setup_server_structure(interaction: discord.Interaction) -> None:
    """Ancien outil de reconstruction, volontairement absent des commandes slash."""
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "Cette commande doit être utilisée dans un serveur.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    reason = f"Commande /setup lancée par {interaction.user} ({interaction.user.id})"
    created_categories = 0
    created_channels = 0
    created_roles = 0
    stage_fallbacks = 0
    role_selection_channel: discord.TextChannel | None = None
    ticket_panel_channel: discord.TextChannel | None = None
    ticket_rules_channel: discord.TextChannel | None = None
    recruitment_info_channel: discord.TextChannel | None = None
    recruitment_panel_channel: discord.TextChannel | None = None
    faq_channel: discord.TextChannel | None = None
    changelog_channel: discord.TextChannel | None = None
    trade_channel: discord.TextChannel | None = None
    trade_market_channel: discord.TextChannel | None = None
    player_cv_channel: discord.TextChannel | None = None
    crew_presentation_channel: discord.TextChannel | None = None
    crew_recruitment_channel: discord.TextChannel | None = None
    clips_channel: discord.TextChannel | None = None
    verification_channel: discord.TextChannel | None = None
    rules_channel: discord.TextChannel | None = None

    try:
        await reset_dynamic_server_data(guild)
        roles, created_roles = await ensure_roles(guild, reason)
        await restore_invite_roles(guild)
        default_permissions = guild.default_role.permissions
        default_permissions.update(mention_everyone=False)
        await guild.default_role.edit(
            permissions=default_permissions,
            reason="Désactivation de @everyone et @here pour les membres",
        )
        deleted_channels, deleted_categories = await delete_all_channels(guild, reason)

        for spec in UNCATEGORIZED_CHANNELS:
            _, created, fallback = await ensure_channel(
                guild, spec, None, reason, reuse_existing=False
            )
            created_channels += int(created)
            stage_fallbacks += int(fallback)

        for category_spec in SERVER_STRUCTURE:
            if category_spec.staff_only:
                category = await guild.create_category(
                    category_spec.name,
                    overwrites=staff_overwrites(guild, roles),
                    reason=reason,
                )
            elif category_spec.staff_voice:
                category = await guild.create_category(
                    category_spec.name,
                    overwrites=staff_voice_overwrites(guild, roles),
                    reason=reason,
                )
            elif category_spec.stats_only:
                category = await guild.create_category(
                    category_spec.name,
                    overwrites=server_stats_overwrites(guild, roles),
                    reason=reason,
                )
            elif category_spec.verification_only:
                category = await guild.create_category(
                    category_spec.name,
                    overwrites=verification_overwrites(guild, roles),
                    reason=reason,
                )
            else:
                category = await guild.create_category(
                    category_spec.name,
                    overwrites=member_overwrites(guild, roles),
                    reason=reason,
                )
            created_categories += 1

            for channel_spec in category_spec.channels:
                channel, created, fallback = await ensure_channel(
                    guild,
                    channel_spec,
                    category,
                    reason,
                    reuse_existing=False,
                )
                created_channels += int(created)
                stage_fallbacks += int(fallback)
                if (
                    isinstance(channel, discord.TextChannel)
                    and not category_spec.staff_only
                ):
                    await channel.set_permissions(
                        roles[MEMBER_ROLE_NAME],
                        view_channel=True,
                        read_message_history=True,
                        send_messages=not channel_spec.read_only,
                        add_reactions=True,
                        use_application_commands=True,
                        reason=reason,
                    )
                    for role_name in channel_spec.write_roles:
                        await channel.set_permissions(
                            roles[role_name],
                            view_channel=True,
                            read_message_history=True,
                            send_messages=True,
                            add_reactions=True,
                            reason=reason,
                        )
                if (
                    isinstance(channel, discord.VoiceChannel)
                    and category_spec.staff_voice
                    and channel_spec.member_connect is not None
                ):
                    await channel.set_permissions(
                        roles[MEMBER_ROLE_NAME],
                        view_channel=True,
                        connect=channel_spec.member_connect,
                        speak=False,
                        reason=reason,
                    )
                if (
                    channel_spec.name == ROLE_SELECTION_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    role_selection_channel = channel
                if (
                    channel_spec.name == TICKET_PANEL_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    ticket_panel_channel = channel
                if (
                    channel_spec.name == TICKET_RULES_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    ticket_rules_channel = channel
                if (
                    channel_spec.name == RECRUITMENT_INFO_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    recruitment_info_channel = channel
                if (
                    channel_spec.name == RECRUITMENT_PANEL_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    recruitment_panel_channel = channel
                if (
                    channel_spec.name == FAQ_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    faq_channel = channel
                if (
                    channel_spec.name == CHANGELOG_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    changelog_channel = channel
                if (
                    channel_spec.name == TRADE_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    trade_channel = channel
                if (
                    channel_spec.name == TRADE_MARKET_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    trade_market_channel = channel
                if (
                    channel_spec.name == PLAYER_CV_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    player_cv_channel = channel
                if (
                    channel_spec.name == CREW_PRESENTATION_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    crew_presentation_channel = channel
                if (
                    channel_spec.name == CREW_RECRUITMENT_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    crew_recruitment_channel = channel
                if (
                    channel_spec.name == CLIPS_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    clips_channel = channel
                if (
                    channel_spec.name == VERIFICATION_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    verification_channel = channel
                if (
                    channel_spec.name == RULES_CHANNEL_NAME
                    and isinstance(channel, discord.TextChannel)
                ):
                    rules_channel = channel

        await update_server_stats(guild)

        if rules_channel is not None:
            rules_embed = discord.Embed(
                title="📜 Règlement de la communauté Radarok",
                description=(
                    "Bienvenue dans l'équipage ! En rejoignant et en utilisant ce "
                    "serveur, tu acceptes les règles ci-dessous. Elles permettent de "
                    "garder une communauté agréable, sûre et accessible à tous."
                ),
                colour=discord.Colour.orange(),
            )
            rules_embed.add_field(
                name="1・Respect et comportement",
                value=(
                    "Reste respectueux envers tous les membres. Le harcèlement, les "
                    "insultes, discriminations, menaces, provocations répétées et "
                    "comportements toxiques sont interdits."
                ),
                inline=False,
            )
            rules_embed.add_field(
                name="2・Contenu autorisé",
                value=(
                    "Aucun contenu NSFW, choquant, illégal ou dangereux. Les avatars, "
                    "pseudonymes, statuts, liens, images et vocaux sont également "
                    "concernés."
                ),
                inline=False,
            )
            rules_embed.add_field(
                name="3・Spam et mentions",
                value=(
                    "Le spam, flood, messages copiés en boucle, abus de majuscules, "
                    "mentions massives et utilisation gênante des bots sont interdits."
                ),
                inline=False,
            )
            rules_embed.add_field(
                name="4・Publicité et partenariats",
                value=(
                    "La publicité privée ou publique sans autorisation est interdite. "
                    "Toute proposition doit passer par un ticket **Partenariat**."
                ),
                inline=False,
            )
            rules_embed.add_field(
                name="5・Blox Fruits et échanges",
                value=(
                    "Les arnaques, faux giveaways, liens Roblox suspects, ventes contre "
                    "de l'argent réel et échanges de comptes sont interdits. Chaque "
                    "échange reste sous la responsabilité des participants."
                ),
                inline=False,
            )
            rules_embed.add_field(
                name="6・Triche et sécurité",
                value=(
                    "Ne partage aucun script, exploit, logiciel malveillant, méthode de "
                    "piratage ou contenu destiné à contourner les règles de Roblox, "
                    "Discord ou Blox Fruits."
                ),
                inline=False,
            )
            rules_embed.add_field(
                name="7・Salons et vocaux",
                value=(
                    "Utilise chaque salon pour son sujet. Dans les vocaux, évite les "
                    "cris, soundboards abusives, bruits gênants et expulsions injustifiées "
                    "des vocaux temporaires."
                ),
                inline=False,
            )
            rules_embed.add_field(
                name="8・Tickets et signalements",
                value=(
                    "N'ouvre pas de faux tickets et ne contacte pas inutilement le staff "
                    "en privé. Pour signaler un problème, fournis des informations sincères "
                    "et, si possible, des preuves."
                ),
                inline=False,
            )
            rules_embed.add_field(
                name="9・Vie privée",
                value=(
                    "Ne publie aucune information personnelle sans consentement. "
                    "L'usurpation d'identité, le doxxing et le partage de conversations "
                    "privées dans le but de nuire sont interdits."
                ),
                inline=False,
            )
            rules_embed.add_field(
                name="10・Modération et sanctions",
                value=(
                    "Le staff peut avertir, rendre muet, expulser ou bannir selon la "
                    "gravité et la répétition des faits. Contourner une sanction avec un "
                    "autre compte aggravera celle-ci. Les décisions peuvent être "
                    "contestées calmement via un ticket."
                ),
                inline=False,
            )
            rules_embed.add_field(
                name="✅ Validation",
                value=(
                    f"Clique ensuite sur le bouton dans **{VERIFICATION_CHANNEL_NAME}**. "
                    "L'ignorance du règlement ne pourra pas justifier une infraction."
                ),
                inline=False,
            )
            rules_embed.set_footer(
                text="Radarok Community • Le règlement peut évoluer si nécessaire"
            )
            await rules_channel.send(embed=rules_embed)

        if verification_channel is not None:
            verification_embed = discord.Embed(
                title="✅ Vérification de la communauté",
                description=(
                    "Bienvenue dans la communauté de **Radarok** !\n\n"
                    "Avant d'accéder au serveur, lis attentivement le règlement puis "
                    "clique sur le bouton ci-dessous pour confirmer que tu l'acceptes.\n\n"
                    "En validant, tu recevras automatiquement le rôle `✅・Membre`."
                ),
                colour=discord.Colour.green(),
            )
            verification_embed.set_footer(
                text="Le respect du règlement est obligatoire"
            )
            await verification_channel.send(
                embed=verification_embed,
                view=VerificationView(),
            )

        if role_selection_channel is not None:
            embed = discord.Embed(
                title="🎭 Choisis tes rôles",
                description=(
                    "Utilise les menus ci-dessous pour personnaliser tes notifications, "
                    "indiquer tes activités Blox Fruits et choisir ta race.\n\n"
                    "Tu peux sélectionner plusieurs activités, mais une seule race."
                ),
                colour=discord.Colour.orange(),
            )
            embed.set_footer(text="Communauté de Radarok")
            await role_selection_channel.send(
                embed=embed, view=RoleSelectionView()
            )

        if faq_channel is not None:
            faq_embed = discord.Embed(
                title="❓ Questions fréquentes",
                description=(
                    "Retrouve ici les réponses rapides aux questions les plus courantes "
                    "sur la communauté de Radarok."
                ),
                colour=discord.Colour.blurple(),
            )
            faq_embed.add_field(
                name="🔐 Comment accéder au serveur ?",
                value=(
                    "Lis le règlement puis valide la vérification. Le rôle Membre "
                    "débloquera automatiquement les salons de la communauté."
                ),
                inline=False,
            )
            faq_embed.add_field(
                name="🎭 Comment obtenir mes rôles ?",
                value=(
                    "Utilise les menus du salon choix-des-rôles pour sélectionner tes "
                    "notifications, tes activités Blox Fruits et ta race."
                ),
                inline=False,
            )
            faq_embed.add_field(
                name="🎫 Comment contacter le staff ?",
                value=(
                    "Lis le règlement des tickets puis utilise le centre d'assistance. "
                    "Les candidatures possèdent une catégorie séparée."
                ),
                inline=False,
            )
            faq_embed.add_field(
                name="⚓ Comment créer un vocal privé ?",
                value=(
                    "Rejoins le salon Créer un vocal. Ton équipage sera créé "
                    "automatiquement. Gère-le avec `/vocal-limite`, `/vocal-prive`, "
                    "`/vocal-inviter` et `/vocal-expulser`."
                ),
                inline=False,
            )
            faq_embed.add_field(
                name="🏆 Comment gagner des niveaux ?",
                value=(
                    "Sois actif dans les discussions et les vocaux. Utilise `/niveau` "
                    "pour afficher ta carte et `/classement` pour voir le classement."
                ),
                inline=False,
            )
            faq_embed.add_field(
                name="🎉 Comment fonctionnent les giveaways ?",
                value=(
                    "Clique sur Participer sous le giveaway. Les rôles d'invitations et "
                    "le boost du serveur peuvent augmenter tes chances."
                ),
                inline=False,
            )
            faq_embed.set_footer(
                text="Une question manque ? Ouvre un ticket Assistance"
            )
            await faq_channel.send(embed=faq_embed)

        if changelog_channel is not None:
            changelog_embed = discord.Embed(
                title="📰 Changelog du serveur",
                description=(
                    "Les nouveautés, modifications de salons, fonctionnalités du bot "
                    "et changements importants seront annoncés ici."
                ),
                colour=discord.Colour.orange(),
            )
            changelog_embed.add_field(
                name="🚀 Mise en place initiale",
                value=(
                    "Création de la structure communautaire, des tickets, recrutements, "
                    "vocaux temporaires, niveaux, invitations, giveaways et protections."
                ),
                inline=False,
            )
            changelog_embed.set_footer(text="Radarok Community")
            await changelog_channel.send(embed=changelog_embed)

        if trade_channel is not None:
            trade_embed = discord.Embed(
                title="🛡️ Sécurité et valeur des trades",
                description=(
                    "Avant d'accepter un échange, tu peux consulter les valeurs des "
                    "fruits sur **Blox Fruits Values** :\n\n"
                    "🔗 https://bloxfruitsvalues.com/\n\n"
                    "Compare les deux côtés du trade et demande l'avis de la communauté "
                    "si tu as un doute."
                ),
                colour=discord.Colour.green(),
            )
            trade_embed.add_field(
                name="⛔ Refuse toujours ces propositions",
                value=(
                    "• Échanger contre un objet ou une monnaie d'un **autre jeu**\n"
                    "• Donner ton fruit en premier contre une promesse de paiement après\n"
                    "• Prêter un fruit, un compte ou un objet avec promesse de restitution\n"
                    "• Utiliser un faux middleman ou un intermédiaire imposé par l'autre\n"
                    "• Cliquer sur un lien Roblox, Discord ou inventaire envoyé en privé\n"
                    "• Échanger un compte, de l'argent réel ou tes identifiants"
                ),
                inline=False,
            )
            trade_embed.add_field(
                name="✅ Bonnes pratiques",
                value=(
                    "Effectue tout l'échange dans la fenêtre officielle de Blox Fruits, "
                    "vérifie une dernière fois avant de confirmer et fais des captures. "
                    "Si l'échange ne tient pas dans une seule transaction sécurisée, "
                    "**refuse-le**. Une promesse n'est jamais une garantie."
                ),
                inline=False,
            )
            trade_embed.add_field(
                name="⚠️ Valeurs indicatives",
                value=(
                    "Les valeurs d'un site peuvent évoluer et ne garantissent pas qu'un "
                    "échange soit juste. Demande plusieurs avis si tu as un doute."
                ),
                inline=False,
            )
            trade_embed.set_footer(
                text="Radarok n'est pas affilié à Blox Fruits Values"
            )
            await trade_channel.send(embed=trade_embed)

        if trade_market_channel is not None:
            await trade_market_channel.send(
                embed=discord.Embed(
                    title="🤝 Marché sécurisé des trades",
                    description=(
                        "Publie une offre avec `/trade-publier` en indiquant ce que tu "
                        "proposes et recherches. Tu peux coller les emojis personnalisés "
                        "du serveur dans les deux champs.\n\n"
                        "Une personne intéressée clique sur le bouton : un salon privé "
                        "est alors créé. Chaque participant ne peut avoir qu'un seul "
                        "trade actif. À la fin, utilisez `/trade-avis` ou `/trade-fermer`."
                    ),
                    colour=discord.Colour.teal(),
                )
            )

        if player_cv_channel is not None:
            cv_embed = discord.Embed(
                title="📄 Crée ton CV de joueur",
                description=(
                    "Aucun message normal n'est autorisé dans ce salon.\n\n"
                    "Utilise uniquement **`/cv-creer`** : le bot ouvrira un formulaire "
                    "privé puis publiera ton CV à ta place. Relance la même commande "
                    "pour modifier ton CV existant."
                ),
                colour=discord.Colour.teal(),
            )
            cv_embed.add_field(
                name="📋 Informations demandées",
                value=(
                    "Pseudo Roblox, niveau et mer, fruit/race/V4, activités, "
                    "disponibilités, plateforme, région et type d'équipage recherché."
                ),
                inline=False,
            )
            cv_embed.add_field(
                name="📌 Règles",
                value=(
                    "Pas de fausses informations, de spam, de recrutement pour un "
                    "serveur externe ni de coordonnées personnelles. Réponds aux CV "
                    "en message privé sans harceler leur auteur."
                ),
                inline=False,
            )
            await player_cv_channel.send(embed=cv_embed)

        if crew_presentation_channel is not None:
            await crew_presentation_channel.send(
                embed=discord.Embed(
                    title="📋 Présentation des équipages",
                    description=(
                        "Chaque équipage créé avec `/equipage-creer` apparaît "
                        "automatiquement ici avec son capitaine et son nombre de "
                        "membres. Les présentations sont mises à jour par le bot."
                    ),
                    colour=discord.Colour.gold(),
                )
            )

        if crew_recruitment_channel is not None:
            await crew_recruitment_channel.send(
                embed=discord.Embed(
                    title="📢 Recrutements d'équipages",
                    description=(
                        "Aucun message normal n'est autorisé dans ce salon.\n\n"
                        "Les capitaines publient avec **`/equipage-recrutement`**. "
                        "Le bot ouvre un formulaire puis envoie l'annonce avec un "
                        "bouton **Postuler**.\n\n"
                        "Pour postuler, tu dois avoir créé ton CV avec `/cv-creer`. "
                        "Un salon privé sera ensuite ouvert avec le capitaine."
                    ),
                    colour=discord.Colour.gold(),
                )
            )

        if clips_channel is not None:
            clips_embed = discord.Embed(
                title="🎥 Règles des clips de la communauté",
                description=(
                    "Partage ici tes meilleurs moments Blox Fruits, YouTube ou Twitch."
                ),
                colour=discord.Colour.purple(),
            )
            clips_embed.add_field(
                name="✅ Autorisé",
                value=(
                    "Tes propres clips, les clips de Radarok et les créations pour "
                    "lesquelles tu as l'autorisation. Ajoute une courte description."
                ),
                inline=False,
            )
            clips_embed.add_field(
                name="⛔ Interdit",
                value=(
                    "Contenu volé ou sans crédit, publicité répétée, contenu NSFW, "
                    "humiliation, harcèlement, triche, liens suspects et spam."
                ),
                inline=False,
            )
            clips_embed.set_footer(
                text="Un rappel automatique de ces règles est publié chaque jour"
            )
            await clips_channel.send(embed=clips_embed)

        if ticket_rules_channel is not None:
            ticket_rules_embed = discord.Embed(
                title="📜 Règlement et utilisation des tickets",
                description=(
                    "Les tickets servent à contacter l'équipe de Radarok de manière "
                    "privée. Lis ces consignes avant d'en ouvrir un."
                ),
                colour=discord.Colour.orange(),
            )
            ticket_rules_embed.add_field(
                name="🎫 Comment ouvrir un ticket ?",
                value=(
                    f"1. Va dans {TICKET_PANEL_CHANNEL_NAME}.\n"
                    "2. Choisis le bouton correspondant à ta demande.\n"
                    "3. Remplis le formulaire avec des informations précises.\n"
                    "4. Attends la réponse du staff dans le salon privé créé."
                ),
                inline=False,
            )
            ticket_rules_embed.add_field(
                name="✅ À faire",
                value=(
                    "Explique clairement le problème, ajoute des captures ou preuves "
                    "si nécessaire et reste disponible pour répondre aux questions."
                ),
                inline=False,
            )
            ticket_rules_embed.add_field(
                name="⛔ Interdit",
                value=(
                    "Faux tickets, spam, insultes, mentions répétées du staff, demandes "
                    "en double et fermeture du ticket avant la fin de son traitement."
                ),
                inline=False,
            )
            ticket_rules_embed.add_field(
                name="📝 Recrutement",
                value=(
                    "Les candidatures ne se font pas ici. Consulte la catégorie "
                    "**RECRUTEMENT** et utilise son bouton pour postuler."
                ),
                inline=False,
            )
            ticket_rules_embed.set_footer(
                text="Tout abus du système de tickets peut être sanctionné"
            )
            await ticket_rules_channel.send(embed=ticket_rules_embed)

        if ticket_panel_channel is not None:
            ticket_embed = discord.Embed(
                title="🎫 Centre d'assistance de Radarok",
                description=(
                    "Choisis le type de demande correspondant à ta situation.\n"
                    "Un salon privé sera créé entre toi et l'équipe.\n\n"
                    "🆘 **Assistance** — question ou problème général\n"
                    "🤝 **Partenariat** — proposer une collaboration\n"
                    "🛡️ **Signalement** — signaler un membre ou un comportement"
                ),
                colour=discord.Colour.orange(),
            )
            ticket_embed.set_footer(
                text="Un seul ticket ouvert par type et par membre"
            )
            await ticket_panel_channel.send(
                embed=ticket_embed,
                view=TicketPanelView(),
            )

        if recruitment_info_channel is not None:
            recruitment_info_embed = discord.Embed(
                title="📋 Rejoindre l'équipe de Radarok",
                description=(
                    "Tu souhaites aider la communauté et participer à son évolution ? "
                    "Lis les conditions ci-dessous avant de déposer ta candidature."
                ),
                colour=discord.Colour.green(),
            )
            recruitment_info_embed.add_field(
                name="✅ Profil recherché",
                value=(
                    "• Être mature, respectueux et actif sur le serveur\n"
                    "• Bien connaître le règlement et savoir garder son calme\n"
                    "• Être disponible régulièrement et travailler en équipe\n"
                    "• Fournir une candidature honnête et suffisamment détaillée"
                ),
                inline=False,
            )
            recruitment_info_embed.add_field(
                name="📝 Comment postuler ?",
                value=(
                    f"Rends-toi dans {RECRUITMENT_PANEL_CHANNEL_NAME}, clique sur "
                    "**Déposer ma candidature**, puis complète toutes les questions. "
                    "Un ticket privé sera créé pour échanger avec les responsables."
                ),
                inline=False,
            )
            recruitment_info_embed.add_field(
                name="⚠️ À savoir",
                value=(
                    "Ne demande pas quand ta candidature sera traitée et ne contacte "
                    "pas le staff en privé. Une candidature refusée ne doit pas être "
                    "redéposée immédiatement. Mentir peut entraîner un refus définitif."
                ),
                inline=False,
            )
            recruitment_info_embed.set_footer(
                text="La décision finale appartient aux responsables du serveur"
            )
            await recruitment_info_channel.send(embed=recruitment_info_embed)

        if recruitment_panel_channel is not None:
            recruitment_panel_embed = discord.Embed(
                title="📝 Déposer une candidature",
                description=(
                    "Après avoir lu les informations de recrutement, clique sur le "
                    "bouton ci-dessous et réponds soigneusement au formulaire.\n\n"
                    "Une seule candidature ouverte est autorisée par membre."
                ),
                colour=discord.Colour.green(),
            )
            await recruitment_panel_channel.send(
                embed=recruitment_panel_embed,
                view=RecruitmentPanelView(),
            )

        await update_helper_leaderboard(guild)

        fallback_message = (
            f"\n⚠️ **{stage_fallbacks}** salon(s) de conférence ont été créés en "
            "salons vocaux, car Discord n'autorise pas les conférences sur ce serveur."
            if stage_fallbacks
            else ""
        )
        try:
            await interaction.followup.send(
                f"Réinitialisation terminée : **{deleted_categories}** catégorie(s) et "
                f"**{deleted_channels}** salon(s) supprimés, puis "
                f"**{created_categories}** catégorie(s), **{created_channels}** salon(s) "
                f"et **{created_roles}** nouveau(x) rôle(s) créés."
                f"{fallback_message}",
                ephemeral=True,
            )
        except discord.NotFound:
            # Le salon depuis lequel /setup a été lancé vient d'être supprimé.
            logging.info(
                "Réinitialisation terminée : %s salons et %s catégories supprimés",
                deleted_channels,
                deleted_categories,
            )
    except discord.Forbidden:
        await interaction.followup.send(
            "Je n'ai pas les permissions nécessaires. Place mon rôle au-dessus des "
            "rôles concernés et accorde-moi **Gérer les salons**.",
            ephemeral=True,
        )
    except discord.HTTPException as error:
        logging.exception("Discord a refusé une opération pendant /setup")
        await interaction.followup.send(
            f"Discord a refusé une opération (`{error.code}`) : `{error.text}`",
            ephemeral=True,
        )


async def ensure_discord_audit_log_channel(
    guild: discord.Guild,
) -> discord.TextChannel | None:
    channel = discord.utils.get(
        guild.text_channels, name=DISCORD_AUDIT_LOG_CHANNEL_NAME
    )
    if channel is not None:
        return channel
    bot_member = guild.me
    if bot_member is None:
        return None
    overwrites: dict[
        discord.Role | discord.Member, discord.PermissionOverwrite
    ] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
        ),
    }
    for role in guild.roles:
        if role.name in STAFF_ROLE_NAMES:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
    category = discord.utils.get(
        guild.categories, name=JOURNALS_CATEGORY_NAME
    )
    try:
        if category is None:
            category = await guild.create_category(
                JOURNALS_CATEGORY_NAME,
                overwrites=overwrites,
                reason="Création automatique de la catégorie des journaux",
            )
        return await guild.create_text_channel(
            DISCORD_AUDIT_LOG_CHANNEL_NAME,
            category=category,
            overwrites=overwrites,
            reason="Création automatique du journal d'audit Discord",
        )
    except discord.Forbidden:
        logging.warning(
            "Permissions insuffisantes pour créer les logs Discord sur %s",
            guild.id,
        )
    except discord.HTTPException:
        logging.exception(
            "Impossible de créer les logs Discord sur %s", guild.id
        )
    return None


AUDIT_ACTION_LABELS = {
    "guild_update": "Serveur modifié",
    "channel_create": "Salon créé",
    "channel_update": "Salon renommé ou modifié",
    "channel_delete": "Salon supprimé",
    "overwrite_create": "Permission de salon ajoutée",
    "overwrite_update": "Permission de salon modifiée",
    "overwrite_delete": "Permission de salon supprimée",
    "kick": "Membre expulsé",
    "ban": "Membre banni",
    "unban": "Membre débanni",
    "member_update": "Profil d'un membre modifié",
    "member_role_update": "Rôles d'un membre modifiés",
    "member_move": "Membre déplacé en vocal",
    "member_disconnect": "Membre déconnecté d'un vocal",
    "bot_add": "Bot ajouté",
    "role_create": "Rôle créé",
    "role_update": "Rôle modifié",
    "role_delete": "Rôle supprimé",
    "invite_create": "Invitation créée",
    "invite_update": "Invitation modifiée",
    "invite_delete": "Invitation supprimée",
    "webhook_create": "Webhook créé",
    "webhook_update": "Webhook modifié",
    "webhook_delete": "Webhook supprimé",
    "emoji_create": "Emoji créé",
    "emoji_update": "Emoji modifié",
    "emoji_delete": "Emoji supprimé",
    "sticker_create": "Sticker créé",
    "sticker_update": "Sticker modifié",
    "sticker_delete": "Sticker supprimé",
    "thread_create": "Fil créé",
    "thread_update": "Fil modifié",
    "thread_delete": "Fil supprimé",
    "message_delete": "Message supprimé par le staff",
    "message_bulk_delete": "Messages supprimés en masse",
    "message_pin": "Message épinglé",
    "message_unpin": "Message désépinglé",
}


def describe_audit_target(target: object) -> str:
    target_id = getattr(target, "id", None)
    mention = getattr(target, "mention", None)
    name = (
        getattr(target, "display_name", None)
        or getattr(target, "name", None)
        or str(target)
    )
    description = str(mention or name)
    if target_id is not None:
        description += f"\n`{target_id}`"
    return description[:1024]


def format_audit_value(value: object) -> str:
    if value is None:
        return "Aucun"
    if isinstance(value, (list, tuple, set)):
        labels = [
            getattr(item, "name", None) or str(item) for item in value
        ]
        return ", ".join(labels)[:300] or "Aucun"
    return str(getattr(value, "name", value))[:300]


def audit_changes_summary(entry: discord.AuditLogEntry) -> str | None:
    field_labels = {
        "name": "Nom",
        "nick": "Surnom",
        "topic": "Sujet",
        "position": "Position",
        "user_limit": "Limite utilisateurs",
        "roles": "Rôles",
        "permissions": "Permissions",
        "slowmode_delay": "Mode lent",
        "nsfw": "NSFW",
        "bitrate": "Débit",
        "communication_disabled_until": "Timeout",
    }
    lines: list[str] = []
    for attribute, label in field_labels.items():
        old_value = getattr(entry.before, attribute, None)
        new_value = getattr(entry.after, attribute, None)
        if old_value == new_value or (old_value is None and new_value is None):
            continue
        lines.append(
            f"**{label} :** `{format_audit_value(old_value)}` → "
            f"`{format_audit_value(new_value)}`"
        )
        if len(lines) >= 6:
            break
    return "\n".join(lines)[:1024] if lines else None


async def send_discord_audit_entry(
    guild: discord.Guild,
    channel: discord.TextChannel,
    entry: discord.AuditLogEntry,
) -> None:
    actor = entry.user
    if actor is None or actor.id == getattr(bot.user, "id", None):
        return
    actor_member = guild.get_member(actor.id)
    if actor_member is None or not is_ticket_staff(actor_member):
        return
    action_name = entry.action.name
    action_label = AUDIT_ACTION_LABELS.get(
        action_name, action_name.replace("_", " ").title()
    )
    embed = discord.Embed(
        title=f"🧾 {action_label}",
        colour=discord.Colour.dark_gold(),
        timestamp=entry.created_at,
    )
    embed.add_field(
        name="Action effectuée par",
        value=f"{actor_member.mention}\n`{actor_member.id}`",
        inline=True,
    )
    if entry.target is not None:
        embed.add_field(
            name="Élément concerné",
            value=describe_audit_target(entry.target),
            inline=True,
        )
    extra_channel = getattr(entry.extra, "channel", None)
    if extra_channel is not None:
        embed.add_field(
            name="Salon concerné",
            value=describe_audit_target(extra_channel),
            inline=True,
        )
    count = getattr(entry.extra, "count", None)
    if count is not None:
        embed.add_field(name="Nombre", value=str(count), inline=True)
    changes = audit_changes_summary(entry)
    if changes:
        embed.add_field(name="Modifications", value=changes, inline=False)
    embed.add_field(
        name="Date et heure exactes",
        value=f"<t:{int(entry.created_at.timestamp())}:F>",
        inline=False,
    )
    if entry.reason:
        embed.add_field(name="Raison", value=entry.reason[:1024], inline=False)
    embed.set_footer(text=f"ID audit : {entry.id}")
    await channel.send(embed=embed)


@tasks.loop(seconds=10)
async def discord_audit_log_loop() -> None:
    connection = require_database()
    for guild in bot.guilds:
        channel = await ensure_discord_audit_log_channel(guild)
        if channel is None:
            continue
        state = connection.execute(
            "SELECT last_entry_id FROM audit_log_state WHERE guild_id = ?",
            (guild.id,),
        ).fetchone()
        try:
            entries = [entry async for entry in guild.audit_logs(limit=100)]
        except discord.Forbidden:
            logging.warning(
                "Permission Voir le journal d'audit manquante sur %s", guild.id
            )
            continue
        except discord.HTTPException:
            logging.exception(
                "Impossible de lire le journal d'audit sur %s", guild.id
            )
            continue
        if not entries:
            continue
        newest_id = max(entry.id for entry in entries)
        if state is None:
            connection.execute(
                """
                INSERT INTO audit_log_state (guild_id, last_entry_id)
                VALUES (?, ?)
                """,
                (guild.id, newest_id),
            )
            connection.commit()
            continue
        last_entry_id = state[0]
        for entry in sorted(entries, key=lambda current: current.id):
            if entry.id <= last_entry_id:
                continue
            try:
                await send_discord_audit_entry(guild, channel, entry)
            except discord.HTTPException:
                logging.exception(
                    "Impossible d'envoyer l'entrée d'audit %s", entry.id
                )
        connection.execute(
            """
            UPDATE audit_log_state SET last_entry_id = ?
            WHERE guild_id = ?
            """,
            (newest_id, guild.id),
        )
        connection.commit()


@discord_audit_log_loop.before_loop
async def before_discord_audit_log_loop() -> None:
    await bot.wait_until_ready()


async def _setup_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        message = "Tu dois être administrateur pour utiliser `/setup`."
    else:
        original = (
            error.original
            if isinstance(error, app_commands.CommandInvokeError)
            else error
        )
        logging.error(
            "Erreur non gérée dans /setup",
            exc_info=(type(original), original, original.__traceback__),
        )
        message = (
            "Une erreur est survenue pendant `/setup` : "
            f"`{type(original).__name__}: {original}`"
        )
    if interaction.response.is_done():
        try:
            await interaction.followup.send(message, ephemeral=True)
        except discord.NotFound:
            logging.error("Impossible d'afficher l'erreur : le salon a été supprimé")
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def publish_bot_update(guild: discord.Guild) -> None:
    connection = require_database()
    if connection.execute(
        """
        SELECT 1 FROM bot_update_posts
        WHERE guild_id = ? AND version = ?
        """,
        (guild.id, BOT_UPDATE_VERSION),
    ).fetchone():
        return
    channel = guild.get_channel(BOT_UPDATE_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        logging.warning(
            "Salon de mises à jour %s introuvable sur %s",
            BOT_UPDATE_CHANNEL_ID,
            guild.id,
        )
        return
    embed = discord.Embed(
        title="📰 RadarokBot — Fonctionnalités complètes",
        description=(
            "Voici l'ensemble des systèmes actuellement disponibles sur le serveur, "
            "ainsi que les dernières nouveautés ajoutées à RadarokBot."
        ),
        colour=discord.Colour.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="🧱 Installation automatique du serveur",
        value=(
            "La structure prévoit les catégories, salons, rôles, permissions et "
            "panneaux. Les salons protégés sont conservés et les espaces officiels "
            "restent en lecture seule."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔐 Vérification et accueil",
        value=(
            "Règlement complet, bouton de vérification, autorôles Membre/Bot, message "
            "de bienvenue personnalisé, FAQ, changelog et choix des rôles."
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 Statistiques et activité",
        value=(
            "Compteurs Membres/Humains/Bots/Boosts, XP par messages et temps vocal, "
            "rôles de progression, carte `/niveau`, `/classement`, ajout et remise "
            "à zéro des niveaux."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔗 Invitations et boosters",
        value=(
            "Comptage des invitations, attribution automatique des quatre rôles de "
            "recrutement, `/invites`, `/invites-definir` et remerciement automatique "
            "des membres qui boostent."
        ),
        inline=False,
    )
    embed.add_field(
        name="🎉 Giveaways pondérés",
        value=(
            "Création, participation, liste des participants, durée exacte, chances "
            "supplémentaires selon les invitations et boosts, tirage, reroll, "
            "annulation et rappels à 24 h et 1 h."
        ),
        inline=False,
    )
    embed.add_field(
        name="🛡️ Protection automatique",
        value=(
            "Antispam, blocage des mentions massives, `@everyone`, liens frauduleux, "
            "domaines suspects et raccourcisseurs, avec suppression et timeout "
            "automatiques. Les comptes récents restent autorisés."
        ),
        inline=False,
    )
    embed.add_field(
        name="🌐 Réseaux et communauté",
        value=(
            "Rappels YouTube, Twitch, TikTok et réseaux, salons Blox Fruits, valeurs "
            "des trades, clips, CV joueurs, recrutements, partenariats, sondages, "
            "suggestions et contenus communautaires."
        ),
        inline=False,
    )
    embed.add_field(
        name="🏴‍☠️ Équipages permanents",
        value=(
            "Création à partir du niveau 10, rôle Capitaine, présentation publique, "
            "CV par formulaire, annonces avec bouton Postuler, candidature privée, "
            "acceptation/refus, salons privés, vice-capitaine, limite, invitations, "
            "exclusions, transfert, journal privé, classement d'activité et guide "
            "complet envoyé en MP au capitaine."
        ),
        inline=False,
    )
    embed.add_field(
        name="🤝 Marché des trades",
        value=(
            "Publication d'offres avec emojis, bouton d'intérêt, salon privé, "
            "transaction exclusive et réputation de 1 à 5 étoiles."
        ),
        inline=False,
    )
    embed.add_field(
        name="🆘 Helpers et tickets",
        value=(
            "Assistance, signalements, partenariats et recrutements privés, formulaires, "
            "claim exclusif, transmission au staff supérieur, fermeture confirmée, "
            "rôle automatique, permissions réparées au redémarrage, points Helpers, "
            "classement et transcriptions. Les tickets remontés sont déplacés dans "
            "une catégorie privée réservée au rôle Staff supérieur."
        ),
        inline=False,
    )
    embed.add_field(
        name="⚖️ Modération et journaux",
        value=(
            "Dossiers numérotés, annulation par bouton, notes internes, escalade "
            "automatique des warns, clear limité avec filtre par membre, statistiques "
            "mensuelles et journaux séparés pour "
            "les messages, vocaux, arrivées, départs et tickets. Le nouveau journal "
            "Discord identifie précisément les actions du staff, et chaque claim de "
            "ticket conserve son auteur, sa date et son heure."
        ),
        inline=False,
    )
    embed.add_field(
        name="💡 Suggestions communautaires",
        value=(
            "Formulaire `/suggestion`, votes Pour/Contre uniques et modifiables, "
            "statut officiel En attente/Acceptée/Refusée/Réalisée et réponse du staff."
        ),
        inline=False,
    )
    embed.add_field(
        name="🎪 Événements",
        value=(
            "Création par commande, inscriptions, limite de places, participants, "
            "liste d'attente, rappels à 24 h et 30 min, annulation, clôture et podium "
            "avec rôles de médailles."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔊 Vocaux temporaires",
        value=(
            "Création d'un équipage vocal, limite personnalisée, mode privé, invitation "
            "avec lien direct, expulsion, suppression à vide et transmission automatique "
            "au membre présent depuis le plus longtemps."
        ),
        inline=False,
    )
    embed.add_field(
        name="📢 Automatisations",
        value=(
            "Messages de bienvenue, règlement, FAQ, consignes des tickets, sécurité "
            "des trades, modèles de CV, règles quotidiennes des clips, rappels sociaux, "
            "giveaways, événements et publication versionnée des mises à jour."
        ),
        inline=False,
    )
    embed.set_footer(text=f"RadarokBot • Version {BOT_UPDATE_VERSION}")
    try:
        message = await channel.send(embed=embed)
    except discord.HTTPException:
        logging.exception("Impossible de publier la mise à jour du bot")
        return
    connection.execute(
        """
        INSERT INTO bot_update_posts (guild_id, version, message_id, posted_at)
        VALUES (?, ?, ?, ?)
        """,
        (guild.id, BOT_UPDATE_VERSION, message.id, int(time.time())),
    )
    connection.commit()


async def upsert_command_guide(
    channel: discord.TextChannel,
    *,
    title: str,
    embed: discord.Embed,
) -> None:
    try:
        async for message in channel.history(limit=100):
            if (
                message.author == bot.user
                and message.embeds
                and message.embeds[0].title == title
            ):
                await message.edit(embed=embed)
                return
        await channel.send(embed=embed)
    except discord.HTTPException:
        logging.exception("Impossible d'actualiser le guide %s", title)


async def refresh_command_guides(guild: discord.Guild) -> None:
    commands_channel = discord.utils.get(
        guild.text_channels, name=COMMANDS_CHANNEL_NAME
    )
    if commands_channel is not None:
        embed = discord.Embed(
            title="🤖 Commandes de RadarokBot",
            description=(
                "Toutes les commandes utilisent des **tirets**. Les commandes "
                "affichées par Discord avec un ancien nom ne doivent plus être utilisées."
            ),
            colour=discord.Colour.blue(),
        )
        embed.add_field(
            name="📊 Profil et communauté",
            value=(
                "`/niveau` • afficher ta carte\n"
                "`/classement` • classement d'activité\n"
                "`/invites` • consulter tes invitations\n"
                "`/cv-creer` • créer ou modifier ton CV\n"
                "`/suggestion` • proposer une idée"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔊 Vocal temporaire",
            value=(
                "`/vocal-limite`\n"
                "`/vocal-prive`\n"
                "`/vocal-inviter`\n"
                "`/vocal-expulser`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏴‍☠️ Équipages",
            value=(
                "`/equipage-creer`\n"
                "`/equipage-recrutement`\n"
                "`/equipage-commandes`\n"
                "`/equipage-inviter` • `/equipage-exclure`\n"
                "`/equipage-vice-capitaine` • `/equipage-limite`\n"
                "`/equipage-membres` • `/equipage-classement`\n"
                "`/equipage-transferer`\n"
                "`/equipage-quitter`\n"
                "`/equipage-supprimer`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🤝 Trades",
            value=(
                "`/trade-publier`\n"
                "`/trade-avis`\n"
                "`/trade-fermer`\n"
                "`/trade-profil`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🆘 Helpers",
            value=(
                "`/warns` et `/infos-joueur` sont les seules commandes staff "
                "disponibles au rôle Helper."
            ),
            inline=False,
        )
        embed.set_footer(
            text="Le staff peut publier son catalogue avec /admin-commandes"
        )
        await upsert_command_guide(
            commands_channel,
            title="🤖 Commandes de RadarokBot",
            embed=embed,
        )

    suggestions_channel = discord.utils.get(
        guild.text_channels, name=SUGGESTIONS_CHANNEL_NAME
    )
    if suggestions_channel is not None:
        embed = discord.Embed(
            title="💡 Proposer et voter une suggestion",
            description=(
                "Utilise **`/suggestion`** pour ouvrir le formulaire. Le bot publie "
                "ensuite ton idée avec les boutons **Pour** et **Contre**."
            ),
            colour=discord.Colour.gold(),
        )
        embed.add_field(
            name="Fonctionnement",
            value=(
                "Un seul vote par membre, modifiable à tout moment. Le staff indiquera "
                "ensuite si la suggestion est acceptée, refusée ou réalisée, avec une "
                "réponse officielle."
            ),
            inline=False,
        )
        await upsert_command_guide(
            suggestions_channel,
            title="💡 Proposer et voter une suggestion",
            embed=embed,
        )

    cv_channel = discord.utils.get(guild.text_channels, name=PLAYER_CV_CHANNEL_NAME)
    if cv_channel is not None:
        embed = discord.Embed(
            title="📄 Crée ton CV de joueur",
            description=(
                "Utilise uniquement **`/cv-creer`** dans ce salon. Le bot ouvre un "
                "formulaire privé puis publie ton CV. Relance la commande pour le modifier."
            ),
            colour=discord.Colour.teal(),
        )
        embed.add_field(
            name="Informations demandées",
            value=(
                "Pseudo Roblox, niveau et mer, profil Blox Fruits, disponibilités "
                "et type d'équipage recherché."
            ),
            inline=False,
        )
        await upsert_command_guide(
            cv_channel, title="📄 Crée ton CV de joueur", embed=embed
        )

    recruitment_channel = discord.utils.get(
        guild.text_channels, name=CREW_RECRUITMENT_CHANNEL_NAME
    )
    if recruitment_channel is not None:
        embed = discord.Embed(
            title="📢 Recrutements d'équipages",
            description=(
                "Les capitaines publient uniquement avec "
                "**`/equipage-recrutement`**. Le bot ouvre le formulaire et ajoute "
                "le bouton **Postuler**.\n\n"
                "Les candidats doivent d'abord utiliser `/cv-creer`."
            ),
            colour=discord.Colour.gold(),
        )
        await upsert_command_guide(
            recruitment_channel,
            title="📢 Recrutements d'équipages",
            embed=embed,
        )

    market_channel = discord.utils.get(
        guild.text_channels, name=TRADE_MARKET_CHANNEL_NAME
    )
    if market_channel is not None:
        embed = discord.Embed(
            title="🤝 Marché sécurisé des trades",
            description=(
                "Publie avec **`/trade-publier`**. Une personne intéressée utilise "
                "le bouton de l'annonce, puis les deux membres terminent avec "
                "`/trade-avis`. Utilise `/trade-fermer` si l'échange est annulé."
            ),
            colour=discord.Colour.teal(),
        )
        await upsert_command_guide(
            market_channel,
            title="🤝 Marché sécurisé des trades",
            embed=embed,
        )


@bot.event
async def setup_hook() -> None:
    initialize_database()
    bot.add_view(VerificationView())
    bot.add_view(RoleSelectionView())
    bot.add_view(TicketPanelView())
    bot.add_view(RecruitmentPanelView())
    bot.add_view(TicketControlView())
    bot.add_view(GiveawayView())
    bot.add_view(TradeOfferView())
    bot.add_view(CommunityEventView())
    bot.add_view(CrewRecruitmentView())
    bot.add_view(CrewApplicationView())
    bot.add_view(SuggestionVoteView())
    bot.add_view(SanctionUndoView())
    if not voice_xp_loop.is_running():
        voice_xp_loop.start()
    if not giveaway_end_loop.is_running():
        giveaway_end_loop.start()
    if not social_bump_loop.is_running():
        social_bump_loop.start()
    if not event_reminder_loop.is_running():
        event_reminder_loop.start()
    if not clip_rules_reminder_loop.is_running():
        clip_rules_reminder_loop.start()
    if not discord_audit_log_loop.is_running():
        discord_audit_log_loop.start()
    if GUILD_ID:
        guild_object = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild_object)
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.guild is None or message.author.bot:
        return
    if await moderate_message(message):
        return
    if award_message_xp(message.guild.id, message.author.id):
        if isinstance(message.author, discord.Member):
            await update_level_role(message.author)
    await bot.process_commands(message)


@tasks.loop(minutes=1)
async def voice_xp_loop() -> None:
    entries: list[tuple[int, int]] = []
    rewarded_members: list[discord.Member] = []

    for guild in bot.guilds:
        for channel in guild.voice_channels:
            if channel == guild.afk_channel or channel.name == TEMP_VOICE_TRIGGER_NAME:
                continue
            human_members = [member for member in channel.members if not member.bot]
            if len(human_members) < 2:
                continue
            for member in human_members:
                voice = member.voice
                if voice is None or voice.self_deaf or voice.deaf:
                    continue
                entries.append((guild.id, member.id))
                rewarded_members.append(member)

    award_voice_xp_batch(entries)
    for member in rewarded_members:
        await update_level_role(member)


@voice_xp_loop.before_loop
async def before_voice_xp_loop() -> None:
    await bot.wait_until_ready()


@tasks.loop(seconds=20)
async def giveaway_end_loop() -> None:
    connection = require_database()
    current_time = int(time.time())
    reminder_rows = connection.execute(
        """
        SELECT message_id, guild_id, channel_id, prize, ends_at, created_at,
               reminded_24h, reminded_1h
        FROM giveaways
        WHERE status = 'active' AND ends_at > ?
        """,
        (current_time,),
    ).fetchall()
    for (
        message_id,
        guild_id,
        channel_id,
        prize,
        ends_at,
        created_at,
        reminded_24h,
        reminded_1h,
    ) in reminder_rows:
        remaining = ends_at - current_time
        duration = ends_at - created_at
        reminder_kind: str | None = None
        if duration > 86400 and remaining <= 86400 and not reminded_24h:
            reminder_kind = "24h"
        elif duration > 3600 and remaining <= 3600 and not reminded_1h:
            reminder_kind = "1h"
        if reminder_kind is None:
            continue
        guild = bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild is not None else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    f"⏰ **Rappel giveaway — {reminder_kind} restante(s)**\n"
                    f"Le giveaway **{prize}** se termine <t:{ends_at}:R> ! "
                    f"[Accéder au giveaway]("
                    f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id})"
                )
            except discord.HTTPException:
                logging.exception(
                    "Impossible d'envoyer le rappel du giveaway %s", message_id
                )
                continue
        column = "reminded_24h" if reminder_kind == "24h" else "reminded_1h"
        connection.execute(
            f"UPDATE giveaways SET {column} = 1 WHERE message_id = ?",
            (message_id,),
        )
    connection.commit()

    rows = connection.execute(
        """
        SELECT message_id FROM giveaways
        WHERE status = 'active' AND ends_at <= ?
        """,
        (current_time,),
    ).fetchall()
    for (message_id,) in rows:
        try:
            await finish_giveaway(message_id)
        except Exception:
            logging.exception("Échec de clôture du giveaway %s", message_id)


@giveaway_end_loop.before_loop
async def before_giveaway_end_loop() -> None:
    await bot.wait_until_ready()


@tasks.loop(minutes=1)
async def event_reminder_loop() -> None:
    now = datetime.now(timezone.utc)
    connection = require_database()
    for guild in bot.guilds:
        channel = discord.utils.get(
            guild.text_channels, name=EVENT_ANNOUNCEMENT_CHANNEL_NAME
        )
        if channel is None:
            continue
        for event in guild.scheduled_events:
            if event.status is not discord.EventStatus.scheduled:
                continue
            remaining = (event.start_time - now).total_seconds()
            reminder_kind: str | None = None
            if 82800 < remaining <= 86400:
                reminder_kind = "24h"
            elif 1500 < remaining <= 1800:
                reminder_kind = "30m"
            if reminder_kind is None:
                continue
            exists = connection.execute(
                """
                SELECT 1 FROM event_reminders
                WHERE guild_id = ? AND event_id = ? AND reminder_kind = ?
                """,
                (guild.id, event.id, reminder_kind),
            ).fetchone()
            if exists is not None:
                continue
            timestamp = int(event.start_time.timestamp())
            try:
                await channel.send(
                    f"📅 **Rappel événement — {reminder_kind}**\n"
                    f"**{event.name}** commence <t:{timestamp}:R> "
                    f"(<t:{timestamp}:F>).\n{event.url}"
                )
            except discord.HTTPException:
                logging.exception("Impossible de rappeler l'événement %s", event.id)
                continue
            connection.execute(
                """
                INSERT INTO event_reminders (
                    guild_id, event_id, reminder_kind, sent_at
                ) VALUES (?, ?, ?, ?)
                """,
                (guild.id, event.id, reminder_kind, int(time.time())),
            )
        custom_events = connection.execute(
            """
            SELECT message_id, channel_id, name, starts_at,
                   reminded_24h, reminded_30m
            FROM community_events
            WHERE guild_id = ? AND status = 'scheduled'
            """,
            (guild.id,),
        ).fetchall()
        current_timestamp = int(now.timestamp())
        for (
            message_id,
            channel_id,
            event_name,
            starts_at,
            reminded_24h,
            reminded_30m,
        ) in custom_events:
            remaining = starts_at - current_timestamp
            if remaining <= 0:
                connection.execute(
                    """
                    UPDATE community_events SET status = 'started'
                    WHERE message_id = ?
                    """,
                    (message_id,),
                )
                continue
            reminder_kind = None
            if remaining <= 86400 and not reminded_24h:
                reminder_kind = "24h"
            if remaining <= 1800 and not reminded_30m:
                reminder_kind = "30m"
            if reminder_kind is None:
                continue
            event_channel = guild.get_channel(channel_id)
            if not isinstance(event_channel, discord.TextChannel):
                continue
            try:
                await event_channel.send(
                    f"📅 **Rappel événement — {reminder_kind}**\n"
                    f"**{event_name}** commence <t:{starts_at}:R>.\n"
                    f"https://discord.com/channels/{guild.id}/{channel_id}/{message_id}"
                )
            except discord.HTTPException:
                continue
            column = (
                "reminded_24h" if reminder_kind == "24h" else "reminded_30m"
            )
            connection.execute(
                f"UPDATE community_events SET {column} = 1 WHERE message_id = ?",
                (message_id,),
            )
    connection.commit()


@event_reminder_loop.before_loop
async def before_event_reminder_loop() -> None:
    await bot.wait_until_ready()


@tasks.loop(minutes=1)
async def clip_rules_reminder_loop() -> None:
    now = datetime.now(PARIS_TIMEZONE)
    if now.hour != 18:
        return
    slot = f"clips-{now.date().isoformat()}"
    connection = require_database()
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=CLIPS_CHANNEL_NAME)
        if channel is None:
            continue
        row = connection.execute(
            """
            SELECT last_slot, message_id FROM social_bumps
            WHERE guild_id = ? AND channel_id = ?
            """,
            (guild.id, channel.id),
        ).fetchone()
        if row is not None and row[0] == slot:
            continue
        if row is not None and row[1] is not None:
            try:
                previous = await channel.fetch_message(row[1])
                await previous.delete()
            except discord.HTTPException:
                pass
        try:
            message = await channel.send(
                "🎥 **Rappel clips**\n"
                "Publie uniquement ton contenu ou du contenu autorisé, crédite le "
                "créateur, ajoute une description et évite le spam. Les contenus "
                "volés, NSFW, humiliants, liés à la triche ou comportant des liens "
                "suspects seront supprimés."
            )
        except discord.HTTPException:
            logging.exception("Impossible d'envoyer le rappel des clips")
            continue
        connection.execute(
            """
            INSERT INTO social_bumps (guild_id, channel_id, last_slot, message_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                last_slot = excluded.last_slot,
                message_id = excluded.message_id
            """,
            (guild.id, channel.id, slot, message.id),
        )
    connection.commit()


@clip_rules_reminder_loop.before_loop
async def before_clip_rules_reminder_loop() -> None:
    await bot.wait_until_ready()


@tasks.loop(minutes=1)
async def social_bump_loop() -> None:
    now = datetime.now(PARIS_TIMEZONE)
    if now.hour not in SOCIAL_BUMP_HOURS:
        return
    slot = f"{now.date().isoformat()}-{now.hour:02d}"
    connection = require_database()
    for guild in bot.guilds:
        for channel_name, content in SOCIAL_BUMP_MESSAGES.items():
            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if channel is None:
                continue
            row = connection.execute(
                """
                SELECT last_slot, message_id FROM social_bumps
                WHERE guild_id = ? AND channel_id = ?
                """,
                (guild.id, channel.id),
            ).fetchone()
            if row is not None and row[0] == slot:
                continue
            if row is not None and row[1] is not None:
                try:
                    previous_message = await channel.fetch_message(row[1])
                    await previous_message.delete()
                except discord.HTTPException:
                    pass
            try:
                message = await channel.send(content)
            except discord.HTTPException:
                logging.exception("Impossible d'envoyer le rappel dans %s", channel.id)
                continue
            connection.execute(
                """
                INSERT INTO social_bumps (guild_id, channel_id, last_slot, message_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, channel_id) DO UPDATE SET
                    last_slot = excluded.last_slot,
                    message_id = excluded.message_id
                """,
                (guild.id, channel.id, slot, message.id),
            )
    connection.commit()


@social_bump_loop.before_loop
async def before_social_bump_loop() -> None:
    await bot.wait_until_ready()


@bot.event
async def on_message_delete(message: discord.Message) -> None:
    if message.guild is None or message.author.bot:
        return
    channel = discord.utils.get(
        message.guild.text_channels, name=DELETED_MESSAGE_LOG_CHANNEL_NAME
    )
    if channel is None:
        return
    embed = discord.Embed(
        title="🗑️ Message supprimé",
        colour=discord.Colour.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="Auteur",
        value=f"{message.author.mention} (`{message.author.id}`)",
        inline=False,
    )
    embed.add_field(
        name="Salon", value=f"{message.channel.mention} (`{message.channel.id}`)", inline=False
    )
    embed.add_field(
        name="Contenu",
        value=(message.content[:1000] or "*Aucun texte ou contenu non disponible*"),
        inline=False,
    )
    if message.attachments:
        embed.add_field(
            name="Pièces jointes",
            value="\n".join(item.url for item in message.attachments)[:1000],
            inline=False,
        )
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
    if (
        before.guild is None
        or before.author.bot
        or before.content == after.content
    ):
        return
    channel = discord.utils.get(
        before.guild.text_channels, name=EDITED_MESSAGE_LOG_CHANNEL_NAME
    )
    if channel is None:
        return
    embed = discord.Embed(
        title="✏️ Message modifié",
        description=f"[Accéder au message]({after.jump_url})",
        colour=discord.Colour.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="Auteur",
        value=f"{before.author.mention} (`{before.author.id}`)",
        inline=False,
    )
    embed.add_field(
        name="Avant", value=(before.content[:1000] or "*Vide*"), inline=False
    )
    embed.add_field(
        name="Après", value=(after.content[:1000] or "*Vide*"), inline=False
    )
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


@bot.event
async def on_member_join(member: discord.Member) -> None:
    await update_server_stats(member.guild)
    log_channel = discord.utils.get(
        member.guild.text_channels, name=JOIN_LEAVE_LOG_CHANNEL_NAME
    )
    if log_channel is not None:
        created_at = int(member.created_at.timestamp())
        try:
            await log_channel.send(
                embed=discord.Embed(
                    title="📥 Membre arrivé",
                    description=(
                        f"{member.mention} (`{member.id}`)\n"
                        f"Compte créé : <t:{created_at}:F> • <t:{created_at}:R>"
                    ),
                    colour=discord.Colour.green(),
                    timestamp=datetime.now(timezone.utc),
                ).set_thumbnail(url=member.display_avatar.url)
            )
        except discord.HTTPException:
            pass
    if member.bot:
        bot_role = discord.utils.get(member.guild.roles, name=BOT_ROLE_NAME)
        if bot_role is not None:
            try:
                await member.add_roles(bot_role, reason="Autorôle réservé aux bots")
            except discord.Forbidden:
                logging.warning("Impossible d'attribuer le rôle Bots à %s", member)
        return

    await process_member_invite(member)
    role = discord.utils.get(member.guild.roles, name=UNVERIFIED_ROLE_NAME)
    if role is not None:
        try:
            await member.add_roles(role, reason="Membre en attente de vérification")
        except discord.Forbidden:
            logging.warning(
                "Impossible d'attribuer %s à %s : hiérarchie des rôles incorrecte",
                UNVERIFIED_ROLE_NAME,
                member,
            )

    welcome_channel = discord.utils.get(
        member.guild.text_channels, name=WELCOME_CHANNEL_NAME
    )
    if welcome_channel is None:
        return

    embed = discord.Embed(
        title="🏴‍☠️ Bienvenue dans l'équipage de Radarok !",
        description=(
            f"Bienvenue à bord, {member.mention} ! 🌊\n\n"
            "Tu viens de rejoindre la communauté de **Radarok**, consacrée à "
            "**Blox Fruits**, aux vidéos, aux lives et aux aventures entre joueurs.\n\n"
            "**Pour accéder au serveur :**\n"
            f"1️⃣ Lis attentivement le règlement dans `{RULES_CHANNEL_NAME}`\n"
            f"2️⃣ Clique sur le bouton dans `{VERIFICATION_CHANNEL_NAME}`\n"
            "3️⃣ Choisis ensuite tes rôles, activités et ta race\n\n"
            "Une fois vérifié, tu pourras discuter, participer aux événements, "
            "trouver un équipage et créer ton propre vocal temporaire.\n\n"
            f"Tu es notre **{member.guild.member_count}ᵉ membre**. "
            "Prépare-toi à prendre la mer ! ⚓"
        ),
        colour=discord.Colour.orange(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Radarok Community • Bon voyage parmi nous !")
    try:
        await welcome_channel.send(embed=embed)
    except discord.Forbidden:
        logging.warning("Impossible d'envoyer le message de bienvenue")


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    await update_server_stats(member.guild)
    if is_helper(member):
        require_database().execute(
            """
            UPDATE tickets SET claimed_by = NULL
            WHERE guild_id = ? AND claimed_by = ? AND status = 'open'
            """,
            (member.guild.id, member.id),
        )
        require_database().commit()
        helper_role = discord.utils.get(
            member.guild.roles, name=HELPER_ROLE_NAME
        )
        if helper_role is not None:
            await reconcile_helper_ticket_permissions(member.guild, helper_role)
    log_channel = discord.utils.get(
        member.guild.text_channels, name=JOIN_LEAVE_LOG_CHANNEL_NAME
    )
    if log_channel is not None:
        try:
            await log_channel.send(
                embed=discord.Embed(
                    title="📤 Membre parti",
                    description=f"**{member}** (`{member.id}`)",
                    colour=discord.Colour.red(),
                    timestamp=datetime.now(timezone.utc),
                ).set_thumbnail(url=member.display_avatar.url)
            )
        except discord.HTTPException:
            pass


@bot.event
async def on_member_update(
    before: discord.Member, after: discord.Member
) -> None:
    if before.roles != after.roles:
        superior_role = discord.utils.get(
            after.guild.roles, name=SUPERIOR_STAFF_ROLE_NAME
        )
        has_superior_source = any(
            role.name in SUPERIOR_SOURCE_ROLE_NAMES for role in after.roles
        )
        if (
            superior_role is not None
            and has_superior_source
            and superior_role not in after.roles
        ):
            try:
                await after.add_roles(
                    superior_role,
                    reason="Accès automatique au Staff supérieur",
                )
            except discord.HTTPException:
                logging.exception(
                    "Impossible d'attribuer Staff supérieur à %s", after.id
                )
    if before.premium_since != after.premium_since:
        await update_server_stats(after.guild)
    if before.premium_since is None and after.premium_since is not None:
        channel = discord.utils.get(
            after.guild.text_channels, name=BOOST_THANKS_CHANNEL_NAME
        )
        if channel is not None:
            embed = discord.Embed(
                title="💎 Merci pour le boost !",
                description=(
                    f"Un immense merci à {after.mention} qui vient de booster le "
                    "serveur ! Ton soutien aide directement la communauté de Radarok "
                    "à profiter de meilleurs avantages Discord. 🧡"
                ),
                colour=discord.Colour.magenta(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.add_field(
                name="🎉 Avantage giveaway",
                value=(
                    "Tant que ton boost est actif, tu bénéficies automatiquement de "
                    "**+1 chance** dans les giveaways, cumulable avec ton meilleur "
                    "rôle d'invitations."
                ),
                inline=False,
            )
            embed.set_footer(
                text=f"Le serveur possède maintenant "
                f"{after.guild.premium_subscription_count} boost(s)"
            )
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                logging.exception("Impossible d'envoyer le remerciement de boost")


@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild) -> None:
    if before.premium_subscription_count != after.premium_subscription_count:
        await update_server_stats(after)


@bot.event
async def on_invite_create(invite: discord.Invite) -> None:
    if invite.guild is not None:
        await refresh_invite_cache(invite.guild)


@bot.event
async def on_invite_delete(invite: discord.Invite) -> None:
    if invite.guild is not None:
        await refresh_invite_cache(invite.guild)


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    if member.bot:
        return

    if before.channel != after.channel:
        log_channel = discord.utils.get(
            member.guild.text_channels, name=VOICE_LOG_CHANNEL_NAME
        )
        if log_channel is not None:
            if before.channel is None and after.channel is not None:
                action = "🔊 Connexion vocale"
                details = f"{member.mention} a rejoint {after.channel.mention}."
                colour = discord.Colour.green()
            elif before.channel is not None and after.channel is None:
                action = "🔇 Déconnexion vocale"
                details = f"{member.mention} a quitté **{before.channel.name}**."
                colour = discord.Colour.red()
            else:
                action = "🔁 Déplacement vocal"
                details = (
                    f"{member.mention} est passé de **{before.channel.name}** "
                    f"à {after.channel.mention}."
                )
                colour = discord.Colour.orange()
            try:
                await log_channel.send(
                    embed=discord.Embed(
                        title=action,
                        description=details,
                        colour=colour,
                        timestamp=datetime.now(timezone.utc),
                    ).set_footer(text=f"ID membre : {member.id}")
                )
            except discord.HTTPException:
                pass

    joined_channel = after.channel
    if (
        joined_channel is not None
        and joined_channel != before.channel
        and joined_channel.name != TEMP_VOICE_TRIGGER_NAME
        and joined_channel.category is not None
        and joined_channel.category.name == TEMP_VOICE_CATEGORY_NAME
    ):
        voice_join_times[(joined_channel.id, member.id)] = time.monotonic()

    if (
        joined_channel is not None
        and joined_channel.name == TEMP_VOICE_TRIGGER_NAME
        and joined_channel.category is not None
        and joined_channel.category.name == TEMP_VOICE_CATEGORY_NAME
    ):
        safe_name = member.display_name.strip()[:70] or "Membre"
        overwrites = dict(joined_channel.category.overwrites)
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            manage_channels=True,
            move_members=True,
        )
        try:
            temporary_channel = await member.guild.create_voice_channel(
                f"{TEMP_VOICE_PREFIX}{safe_name}",
                category=joined_channel.category,
                overwrites=overwrites,
                reason=f"Vocal temporaire créé pour {member} ({member.id})",
            )
            await member.move_to(
                temporary_channel, reason="Déplacement vers son vocal temporaire"
            )
            try:
                await temporary_channel.send(
                    content=member.mention,
                    embed=build_voice_help_embed(),
                )
            except discord.HTTPException:
                logging.exception(
                    "Impossible d'envoyer l'aide dans le chat du vocal %s",
                    temporary_channel.id,
                )
        except discord.HTTPException:
            logging.exception("Impossible de créer le vocal temporaire de %s", member)
            if "temporary_channel" in locals():
                await temporary_channel.delete(
                    reason="Échec du déplacement dans le vocal temporaire"
                )

    left_channel = before.channel
    if (
        left_channel is not None
        and left_channel.name != TEMP_VOICE_TRIGGER_NAME
        and left_channel.category is not None
        and left_channel.category.name == TEMP_VOICE_CATEGORY_NAME
    ):
        was_owner = (
            left_channel.overwrites_for(member).manage_channels is True
        )
        voice_join_times.pop((left_channel.id, member.id), None)

        if not left_channel.members:
            try:
                await left_channel.delete(reason="Vocal temporaire devenu vide")
            except discord.NotFound:
                pass
            except discord.Forbidden:
                logging.warning(
                    "Impossible de supprimer le vocal temporaire %s", left_channel.id
                )
            finally:
                stale_keys = [
                    key for key in voice_join_times if key[0] == left_channel.id
                ]
                for key in stale_keys:
                    voice_join_times.pop(key, None)
        elif was_owner:
            candidates = [
                candidate
                for candidate in left_channel.members
                if not candidate.bot
            ]
            if candidates:
                new_owner = min(
                    candidates,
                    key=lambda candidate: voice_join_times.get(
                        (left_channel.id, candidate.id), float("inf")
                    ),
                )
                old_permissions = left_channel.overwrites_for(member)
                old_permissions.manage_channels = None
                old_permissions.move_members = None
                new_permissions = left_channel.overwrites_for(new_owner)
                new_permissions.view_channel = True
                new_permissions.connect = True
                new_permissions.speak = True
                new_permissions.manage_channels = True
                new_permissions.move_members = True
                safe_name = new_owner.display_name.strip()[:70] or "Membre"
                try:
                    await left_channel.set_permissions(
                        member,
                        overwrite=old_permissions,
                        reason="Propriété du vocal temporaire transmise",
                    )
                    await left_channel.set_permissions(
                        new_owner,
                        overwrite=new_permissions,
                        reason="Nouveau propriétaire du vocal temporaire",
                    )
                    await left_channel.edit(
                        name=f"{TEMP_VOICE_PREFIX}{safe_name}",
                        reason=f"Vocal transmis automatiquement à {new_owner}",
                    )
                    await left_channel.send(
                        f"👑 {new_owner.mention} devient automatiquement propriétaire "
                        "du vocal, car il s'agit du membre présent depuis le plus "
                        "longtemps."
                    )
                except discord.HTTPException:
                    logging.exception(
                        "Impossible de transmettre le vocal temporaire %s",
                        left_channel.id,
                    )


@bot.event
async def on_ready() -> None:
    if bot.user is None:
        return

    for guild in bot.guilds:
        await ensure_superior_staff_area(guild)
        helper_role = await ensure_helper_role(guild)
        if helper_role is not None:
            await reconcile_helper_ticket_permissions(guild, helper_role)
        await refresh_command_guides(guild)
        await update_server_stats(guild)
        await refresh_invite_cache(guild)
        await restore_invite_roles(guild)
        await publish_bot_update(guild)
        category = discord.utils.get(
            guild.categories, name=TEMP_VOICE_CATEGORY_NAME
        )
        if category is None:
            continue
        for channel in category.voice_channels:
            if channel.name != TEMP_VOICE_TRIGGER_NAME and not channel.members:
                try:
                    await channel.delete(
                        reason="Nettoyage d'un vocal temporaire vide au démarrage"
                    )
                except discord.HTTPException:
                    logging.exception(
                        "Impossible de nettoyer le vocal temporaire %s", channel.id
                    )
            elif channel.name != TEMP_VOICE_TRIGGER_NAME:
                startup_time = time.monotonic()
                for position, current_member in enumerate(channel.members):
                    if not current_member.bot:
                        voice_join_times.setdefault(
                            (channel.id, current_member.id),
                            startup_time + (position / 1000),
                        )

    if GUILD_ID:
        guild_object = discord.Object(id=int(GUILD_ID))
        synced = await bot.tree.sync(guild=guild_object)
        scope = f"le serveur {GUILD_ID}"
    else:
        synced = []
        for guild in bot.guilds:
            guild_object = discord.Object(id=guild.id)
            bot.tree.copy_global_to(guild=guild_object)
            synced.extend(await bot.tree.sync(guild=guild_object))
        scope = f"{len(bot.guilds)} serveur(s)"

    logging.info(
        "Connecté en tant que %s (%s) — %s commande(s) synchronisée(s) sur %s",
        bot.user,
        bot.user.id,
        len(synced),
        scope,
    )


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    await refresh_invite_cache(guild)
    guild_object = discord.Object(id=guild.id)
    bot.tree.copy_global_to(guild=guild_object)
    synced = await bot.tree.sync(guild=guild_object)
    logging.info(
        "%s commande(s) synchronisée(s) sur le nouveau serveur %s",
        len(synced),
        guild.id,
    )


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN est absent. Copie .env.example vers .env et ajoute le token."
        )
    bot.run(TOKEN)
