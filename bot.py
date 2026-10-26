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
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = os.getenv('DISCORD_GUILD_ID') or None
DATABASE_PATH = Path(os.getenv('DATABASE_PATH', BASE_DIR / 'community_bot.db'))
RANK_ASSET_DIR = BASE_DIR / 'assets' / 'ranks'
PRESERVED_SETUP_CHANNEL_IDS = {int(channel_id.strip()) for channel_id in os.getenv('PRESERVED_SETUP_CHANNEL_IDS', '').split(',') if channel_id.strip().isdigit()}
BOT_UPDATE_VERSION = '2026.10.26-studio-roblox'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
)
ChannelKind = Literal['text', 'voice', 'stage']

def stylize_channel_name(name: str) -> str:
    """Puts the first letter of the name in bold mathematical capital."""
    bold_capitals = {chr(ord('a') + index): chr(119808 + index) for index in range(26)}
    bold_capitals.update({chr(ord('A') + index): chr(119808 + index) for index in range(26)})
    start = name.find('・') + 1 if '・' in name else 0
    characters = list(name)
    for index in range(start, len(characters)):
        character = characters[index]
        if character.isalpha():
            characters[index] = bold_capitals.get(character, character.upper())
            break
    return ''.join(characters)

def decorate_category_name(name: str) -> str:
    if name.startswith('○') and name.endswith('➤') or name.startswith('『'):
        return name
    return f'○─────{name}─────➤'

@dataclass(frozen=True)
class ChannelSpec:
    name: str
    kind: ChannelKind = 'text'
    user_limit: int = 0
    read_only: bool = False
    write_roles: tuple[str, ...] = ()
    member_connect: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'name', stylize_channel_name(self.name))

@dataclass(frozen=True)
class CategorySpec:
    name: str
    channels: tuple[ChannelSpec, ...]
    staff_only: bool = False
    verification_only: bool = False
    staff_voice: bool = False
    stats_only: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, 'name', decorate_category_name(self.name))

@dataclass(frozen=True)
class RoleSpec:
    name: str
    colour: int
    permissions: discord.Permissions = discord.Permissions.none()
    hoist: bool = False
ROLE_SPECS = (RoleSpec('👑・Founder', 15844367, discord.Permissions(administrator=True), True), RoleSpec('⚙️・Studio Manager', 15105570, discord.Permissions(manage_guild=True, manage_channels=True, manage_roles=True, manage_messages=True, kick_members=True, ban_members=True, moderate_members=True, view_audit_log=True), True), RoleSpec('🛡️・Administrator', 15158332, discord.Permissions(manage_channels=True, manage_roles=True, manage_messages=True, kick_members=True, ban_members=True, moderate_members=True, view_audit_log=True), True), RoleSpec('🔱・Senior Staff', 9323693, discord.Permissions.none(), True), RoleSpec('🔨・Moderator', 3447003, discord.Permissions(manage_messages=True, kick_members=True, moderate_members=True, view_audit_log=True), True), RoleSpec('🧪・Trial Moderator', 6139362, discord.Permissions(manage_messages=True, moderate_members=True), True), RoleSpec('💻・Developer', 5793266, hoist=True), RoleSpec('🧱・Builder', 15105570, hoist=True), RoleSpec('🎨・UI Designer', 10181046, hoist=True), RoleSpec('🖌️・3D Modeler', 1752220, hoist=True), RoleSpec('🎵・Sound Designer', 15277667, hoist=True), RoleSpec('📢・Community Manager', 15965202, hoist=True), RoleSpec('🤝・Partner', 1752220, hoist=True), RoleSpec('⭐・VIP', 15965202, hoist=True), RoleSpec('💎・Booster', 15418782, hoist=True), RoleSpec('🥉・Recruiter', 13467442, hoist=True), RoleSpec('🥈・Ambassador', 12436423, hoist=True), RoleSpec('🥇・Influencer', 15844367, hoist=True), RoleSpec('💎・Master Recruiter', 10181046, hoist=True), RoleSpec('🎥・Content Creator', 15277667, hoist=True), RoleSpec('🏆・Giveaway Winner', 16044095, hoist=True), RoleSpec('🧪・Beta Tester', 47252, hoist=True), RoleSpec('🥇・Event Champion', 15844367, hoist=True), RoleSpec('🥈・Event Finalist', 12436423, hoist=True), RoleSpec('🥉・Event Third Place', 13467442, hoist=True), RoleSpec('✅・Member', 3066993), RoleSpec('🔒・Unverified', 8359053), RoleSpec('🤖・Bots', 9807270), RoleSpec('🔴・YouTube Videos', 16711680), RoleSpec('🟣・Twitch Streams', 9520895), RoleSpec('🎉・Giveaways', 15844367), RoleSpec('📢・Announcements', 15105570), RoleSpec('🤝・Partnerships', 1752220), RoleSpec('📰・Updates', 3447003), RoleSpec('🚨・Admin Abuse', 12597547), RoleSpec('🎮・New Games', 9323693), RoleSpec('🧪・Test Sessions', 47252), RoleSpec('📅・Events', 2719929), RoleSpec('🆘・Helper', 2600544, hoist=True), RoleSpec('🎮・Player', 3447003), RoleSpec('💡・Creator', 15844367), RoleSpec('🐛・Bug Hunter', 15158332), RoleSpec('📱・Mobile', 3066993), RoleSpec('💻・PC', 5793266), RoleSpec('🎮・Console', 10181046), RoleSpec('💫・Legend', 15844367), RoleSpec('🥇・Veteran', 15105570), RoleSpec('🥈・Active', 12436423), RoleSpec('🥉・Regular', 13467442), RoleSpec('🌱・Newcomer', 8577194))
UNCATEGORIZED_CHANNELS: tuple[ChannelSpec, ...] = ()
SERVER_STRUCTURE = (CategorySpec('🔐・VERIFICATION', (ChannelSpec('📜・rules', read_only=True), ChannelSpec('👋・welcome', read_only=True), ChannelSpec('✅・verification', read_only=True)), verification_only=True), CategorySpec('📌・WELCOME', (ChannelSpec('📢・announcements', read_only=True), ChannelSpec('🎭・role-selection', read_only=True), ChannelSpec('❓・faq', read_only=True), ChannelSpec('🔗・official-links', read_only=True), ChannelSpec('📰・server-changelog', read_only=True), ChannelSpec('💎・boost-thanks', read_only=True))), CategorySpec('📢・STUDIO NEWS', (ChannelSpec('🛠️・progress', read_only=True), ChannelSpec('📰・updates', read_only=True), ChannelSpec('🚨・admin-abuse', read_only=True), ChannelSpec('🎮・new-games', read_only=True), ChannelSpec('🗺️・roadmap', read_only=True))), CategorySpec('🎮・OUR GAMES', (ChannelSpec('🎯・main-game', read_only=True), ChannelSpec('🧪・game-in-development', read_only=True), ChannelSpec('🗄️・legacy-games', read_only=True), ChannelSpec('🔗・game-links', read_only=True), ChannelSpec('📊・server-status', read_only=True))), CategorySpec('💬・COMMUNITY', (ChannelSpec('💬・general-chat'), ChannelSpec('🎮・game-discussion'), ChannelSpec('😂・memes'), ChannelSpec('📷・media'), ChannelSpec('🎥・clips'), ChannelSpec('💡・suggestions'), ChannelSpec('🐛・bug-reports'), ChannelSpec('🤖・bot-commands'), ChannelSpec('🎉・giveaways', read_only=True))), CategorySpec('🧪・TESTING AND FEEDBACK', (ChannelSpec('📋・become-a-tester', read_only=True), ChannelSpec('🧪・test-announcements', read_only=True), ChannelSpec('📝・tester-feedback', read_only=True, write_roles=('🧪・Beta Tester',)), ChannelSpec('🐞・test-bugs', read_only=True, write_roles=('🧪・Beta Tester',)), ChannelSpec('🔒・test-access', read_only=True))), CategorySpec('🎪・EVENTS', (ChannelSpec('📅・calendar', read_only=True), ChannelSpec('🎪・event-announcements', read_only=True), ChannelSpec('🚨・admin-abuse-schedule', read_only=True), ChannelSpec('🎁・contests', read_only=True), ChannelSpec('🏆・results', read_only=True))), CategorySpec('💻・ROBLOX CREATION', (ChannelSpec('💻・development'), ChannelSpec('🧱・building'), ChannelSpec('🎨・ui-and-design'), ChannelSpec('🖌️・modeling'), ChannelSpec('🎵・sounds-and-music'), ChannelSpec('💡・game-ideas'), ChannelSpec('📚・roblox-resources'))), CategorySpec('🌐・SOCIAL MEDIA', (ChannelSpec('🔴・youtube', read_only=True), ChannelSpec('🟣・twitch', read_only=True), ChannelSpec('🎵・tiktok', read_only=True), ChannelSpec('📱・social-media', read_only=True), ChannelSpec('🔔・notifications', read_only=True))), CategorySpec('🤝・PARTNERSHIPS', (ChannelSpec('🤝・partners', read_only=True), ChannelSpec('🗣️・partner-chat', read_only=True, write_roles=('🤝・Partner',)))), CategorySpec('🎟️・SUPPORT', (ChannelSpec('📜・ticket-rules', read_only=True), ChannelSpec('🎫・open-a-ticket', read_only=True))), CategorySpec('🎫・OPEN TICKETS', (), staff_only=True), CategorySpec('🔊・VOICE CHANNELS', (ChannelSpec('🔊・General', 'voice'), ChannelSpec('🎮・In Game', 'voice'), ChannelSpec('🧪・Beta Test', 'voice', 12), ChannelSpec('💻・Development', 'voice', 10), ChannelSpec('🎵・Chill', 'voice'), ChannelSpec('😴・AFK', 'voice'))), CategorySpec('➕・CREATE YOUR VOICE CHANNEL', (ChannelSpec('➕・Create a voice channel', 'voice'),)), CategorySpec('🔒・STAFF', (ChannelSpec('💬・staff-chat'), ChannelSpec('📋・organization'), ChannelSpec('🗺️・internal-roadmap'), ChannelSpec('🐛・bugs-to-fix'), ChannelSpec('🧪・internal-tests'), ChannelSpec('📢・announcement-prep'), ChannelSpec('📨・staff-tickets'), ChannelSpec('🔊・Studio Meeting', 'voice')), staff_only=True), CategorySpec('🛡️・LOGS', (ChannelSpec('📥・joins-leaves'), ChannelSpec('🔊・voice-logs'), ChannelSpec('🗑️・deleted-messages'), ChannelSpec('✏️・edited-messages'), ChannelSpec('⚖️・sanctions'), ChannelSpec('🧾・discord-logs'), ChannelSpec('📁・ticket-transcripts')), staff_only=True))
NOTIFICATION_ROLES = ('🔴・YouTube Videos', '🟣・Twitch Streams', '🎉・Giveaways', '📢・Announcements', '🤝・Partnerships', '📰・Updates', '🚨・Admin Abuse', '🎮・New Games', '🧪・Test Sessions', '📅・Events')
ACTIVITY_ROLES = ('🎮・Player',)
PLATFORM_ROLES = ('📱・Mobile', '💻・PC', '🎮・Console')
MEMBER_ROLE_NAME = '✅・Member'
UNVERIFIED_ROLE_NAME = '🔒・Unverified'
BOT_ROLE_NAME = '🤖・Bots'
WELCOME_CHANNEL_NAME = stylize_channel_name('👋・welcome')
VERIFICATION_CHANNEL_NAME = stylize_channel_name('✅・verification')
RULES_CHANNEL_NAME = stylize_channel_name('📜・rules')
ROLE_SELECTION_CHANNEL_NAME = stylize_channel_name('🎭・role-selection')
FAQ_CHANNEL_NAME = stylize_channel_name('❓・faq')
CHANGELOG_CHANNEL_NAME = stylize_channel_name('📰・server-changelog')
SUGGESTIONS_CHANNEL_NAME = stylize_channel_name('💡・suggestions')
TRADE_CHANNEL_NAME = stylize_channel_name('🤝・trades')
PLAYER_CV_CHANNEL_NAME = stylize_channel_name('📄・player-cvs')
CREW_PRESENTATION_CHANNEL_NAME = stylize_channel_name('📋・crew-presentations')
CREW_RECRUITMENT_CHANNEL_NAME = stylize_channel_name('📢・crew-recruitment')
CLIPS_CHANNEL_NAME = stylize_channel_name('🎥・clips')
BOOST_THANKS_CHANNEL_NAME = stylize_channel_name('💎・boost-thanks')
EVENT_ANNOUNCEMENT_CHANNEL_NAME = stylize_channel_name('🎪・event-announcements')
TRADE_MARKET_CHANNEL_NAME = stylize_channel_name('📢・trade-market')
PRIVATE_TRADE_CATEGORY_NAME = decorate_category_name('🤝・PRIVATE TRADES')
CREW_CATEGORY_NAME = decorate_category_name('🔒・PRIVATE CREWS')
CAPTAIN_ROLE_NAME = '👑・Crew Captain'
JOIN_LEAVE_LOG_CHANNEL_NAME = stylize_channel_name('📥・joins-leaves')
VOICE_LOG_CHANNEL_NAME = stylize_channel_name('🔊・voice-logs')
DELETED_MESSAGE_LOG_CHANNEL_NAME = stylize_channel_name('🗑️・deleted-messages')
EDITED_MESSAGE_LOG_CHANNEL_NAME = stylize_channel_name('✏️・edited-messages')
SANCTION_LOG_CHANNEL_NAME = stylize_channel_name('⚖️・sanctions')
DISCORD_AUDIT_LOG_CHANNEL_NAME = stylize_channel_name('🧾・discord-logs')
JOURNALS_CATEGORY_NAME = decorate_category_name('🛡️・LOGS')
COMMANDS_CHANNEL_NAME = stylize_channel_name('🤖・bot-commands')
TEMP_VOICE_CATEGORY_NAME = decorate_category_name('➕・CREATE YOUR VOICE CHANNEL')
TEMP_VOICE_TRIGGER_NAME = stylize_channel_name('➕・Create a voice channel')
TEMP_VOICE_PREFIX = '🎙️・𝐂rew of '
TICKET_PANEL_CHANNEL_NAME = stylize_channel_name('🎫・open-a-ticket')
TICKET_RULES_CHANNEL_NAME = stylize_channel_name('📜・ticket-rules')
RECRUITMENT_INFO_CHANNEL_NAME = stylize_channel_name('📋・recruitment-information')
RECRUITMENT_PANEL_CHANNEL_NAME = stylize_channel_name('📝・apply')
TICKET_CATEGORY_NAME = decorate_category_name('🎫・OPEN TICKETS')
ESCALATED_TICKET_CATEGORY_NAME = decorate_category_name('⬆️・ESCALATED TICKETS')
TICKET_LOG_CHANNEL_NAME = stylize_channel_name('📨・staff-tickets')
TICKET_TRANSCRIPT_CHANNEL_NAME = stylize_channel_name('📁・ticket-transcripts')
HELPER_LEADERBOARD_CHANNEL_NAME = stylize_channel_name('🏆・leaderboard-helpers')
HELPER_ROLE_NAME = '🆘・Helper'
SUPERIOR_STAFF_ROLE_NAME = '🔱・Senior Staff'
SUPERIOR_SOURCE_ROLE_NAMES = ('👑・Founder', '⚙️・Studio Manager', '🛡️・Administrator')
STAFF_VOICE_CATEGORY_NAME = decorate_category_name('『◉』 ╰⁺°✧・⚙(Staff Voice)⚙・✧°⁺╮')
SERVER_STATS_CATEGORY_NAME = decorate_category_name('📊・SERVER STATS')
STAFF_ROLE_NAMES = ('👑・Founder', '⚙️・Studio Manager', '🛡️・Administrator', '🔨・Moderator', '🧪・Trial Moderator', SUPERIOR_STAFF_ROLE_NAME, '💻・Developer', '📢・Community Manager')
MESSAGE_XP_COOLDOWN = 60
MESSAGE_XP_MIN = 15
MESSAGE_XP_MAX = 25
VOICE_XP_PER_MINUTE = 5
CREW_CREATION_LEVEL = 10
LEGACY_BLOX_COMMANDS = ('cv-create', 'crew-create', 'crew-create-for', 'crew-recruitment', 'crew-commands', 'crew-invite', 'crew-kick', 'crew-vice-captain', 'crew-limit', 'crew-members', 'crew-transfer', 'crew-leaderboard', 'crew-leave', 'crew-delete', 'trade-publish', 'trade-review', 'trade-close', 'trade-profile', 'helper-leaderboard')
LEVEL_ROLE_THRESHOLDS = ((35, '💫・Legend'), (20, '🥇・Veteran'), (10, '🥈・Active'), (5, '🥉・Regular'), (1, '🌱・Newcomer'))
RANK_CARD_TIERS = ((35, 'Legend', 'legende.png', (175, 92, 255)), (20, 'Veteran', 'veteran.png', (255, 190, 55)), (10, 'Active', 'actif.png', (72, 193, 255)), (5, 'Regular', 'habitue.png', (214, 130, 62)), (0, 'Newcomer', 'nouveau.png', (92, 220, 126)))
INVITE_ROLE_TIERS = ((20, '💎・Master Recruiter', 2.0), (15, '🥇・Influencer', 1.5), (10, '🥈・Ambassador', 1.0), (5, '🥉・Recruiter', 0.5))
SPAM_MESSAGE_LIMIT = 6
SPAM_WINDOW_SECONDS = 8
SPAM_TIMEOUT_MINUTES = 5
MASS_MENTION_LIMIT = 5
MASS_MENTION_TIMEOUT_MINUTES = 10
URL_PATTERN = re.compile('https?://[^\\s<>()]+', re.IGNORECASE)
SUSPICIOUS_DOMAIN_MARKERS = ('discord-gift', 'discordnitro', 'discord-app', 'steamcommunlty', 'steampowered-offer', 'roblox-gift', 'robux-generator', 'free-robux')
URL_SHORTENERS = {'bit.ly', 'tinyurl.com', 'cutt.ly', 't.co', 'is.gd', 'rb.gy'}
SOCIAL_BUMP_MESSAGES = {stylize_channel_name('🔴・youtube'): '** Official YouTube **\nThink about the latest videos, subscribe and activate the bell!', stylize_channel_name('🟣・twitch'): '** Official Twitch **\nFollow the channel to not miss any live and join the community live!', stylize_channel_name('🎵・tiktok'): '** Official TikTok **\nDiscover the new excerpts and think about following the community account!', stylize_channel_name('📱・social-media'): '** Official networks **\nFind here all the official news and platforms of the server.'}
SOCIAL_BUMP_HOURS = (9, 15, 21)
PARIS_TIMEZONE = ZoneInfo('Europe/Paris')
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
database: sqlite3.Connection | None = None
message_timestamps: defaultdict[tuple[int, int], deque[float]] = defaultdict(deque)
invite_cache: dict[int, dict[str, int]] = {}
voice_join_times: dict[tuple[int, int], float] = {}
setup_in_progress_guilds: set[int] = set()

def managed_guilds() -> list[discord.Guild]:
    return list(bot.guilds)

def initialize_database() -> None:
    global database
    database = sqlite3.connect(DATABASE_PATH)
    database.execute('PRAGMA journal_mode=WAL')
    database.execute('PRAGMA synchronous=NORMAL')
    database.execute('\n        CREATE TABLE IF NOT EXISTS member_stats (\n            guild_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            message_xp INTEGER NOT NULL DEFAULT 0,\n            voice_xp INTEGER NOT NULL DEFAULT 0,\n            bonus_xp INTEGER NOT NULL DEFAULT 0,\n            voice_seconds INTEGER NOT NULL DEFAULT 0,\n            total_messages INTEGER NOT NULL DEFAULT 0,\n            last_message_xp INTEGER NOT NULL DEFAULT 0,\n            PRIMARY KEY (guild_id, user_id)\n        )\n        ')
    columns = {row[1] for row in database.execute('PRAGMA table_info(member_stats)')}
    if 'bonus_xp' not in columns:
        database.execute('ALTER TABLE member_stats ADD COLUMN bonus_xp INTEGER NOT NULL DEFAULT 0')
    database.execute("\n        CREATE TABLE IF NOT EXISTS tickets (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            guild_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            ticket_type TEXT NOT NULL,\n            channel_id INTEGER NOT NULL UNIQUE,\n            claimed_by INTEGER,\n            status TEXT NOT NULL DEFAULT 'open',\n            created_at INTEGER NOT NULL\n        )\n        ")
    database.execute('\n        CREATE INDEX IF NOT EXISTS idx_open_tickets\n        ON tickets (guild_id, user_id, ticket_type, status)\n        ')
    ticket_columns = {row[1] for row in database.execute('PRAGMA table_info(tickets)')}
    if 'escalated' not in ticket_columns:
        database.execute('ALTER TABLE tickets ADD COLUMN escalated INTEGER NOT NULL DEFAULT 0')
    database.execute('\n        CREATE TABLE IF NOT EXISTS helper_stats (\n            guild_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            resolved_tickets INTEGER NOT NULL DEFAULT 0,\n            points INTEGER NOT NULL DEFAULT 0,\n            PRIMARY KEY (guild_id, user_id)\n        )\n        ')
    database.execute('\n        CREATE TABLE IF NOT EXISTS invite_stats (\n            guild_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            invite_count INTEGER NOT NULL DEFAULT 0,\n            PRIMARY KEY (guild_id, user_id)\n        )\n        ')
    database.execute("\n        CREATE TABLE IF NOT EXISTS giveaways (\n            message_id INTEGER PRIMARY KEY,\n            guild_id INTEGER NOT NULL,\n            channel_id INTEGER NOT NULL,\n            host_id INTEGER NOT NULL,\n            prize TEXT NOT NULL,\n            winners_count INTEGER NOT NULL DEFAULT 1,\n            ends_at INTEGER NOT NULL,\n            status TEXT NOT NULL DEFAULT 'active',\n            created_at INTEGER NOT NULL\n        )\n        ")
    giveaway_columns = {row[1] for row in database.execute('PRAGMA table_info(giveaways)')}
    if 'reminded_24h' not in giveaway_columns:
        database.execute('ALTER TABLE giveaways ADD COLUMN reminded_24h INTEGER NOT NULL DEFAULT 0')
    if 'reminded_1h' not in giveaway_columns:
        database.execute('ALTER TABLE giveaways ADD COLUMN reminded_1h INTEGER NOT NULL DEFAULT 0')
    database.execute('\n        CREATE TABLE IF NOT EXISTS giveaway_entries (\n            message_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            joined_at INTEGER NOT NULL,\n            PRIMARY KEY (message_id, user_id),\n            FOREIGN KEY (message_id) REFERENCES giveaways(message_id)\n        )\n        ')
    database.execute('\n        CREATE TABLE IF NOT EXISTS social_bumps (\n            guild_id INTEGER NOT NULL,\n            channel_id INTEGER NOT NULL,\n            last_slot TEXT NOT NULL,\n            message_id INTEGER,\n            PRIMARY KEY (guild_id, channel_id)\n        )\n        ')
    database.execute('\n        CREATE TABLE IF NOT EXISTS event_reminders (\n            guild_id INTEGER NOT NULL,\n            event_id INTEGER NOT NULL,\n            reminder_kind TEXT NOT NULL,\n            sent_at INTEGER NOT NULL,\n            PRIMARY KEY (guild_id, event_id, reminder_kind)\n        )\n        ')
    database.executescript("\n        CREATE TABLE IF NOT EXISTS crews (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            guild_id INTEGER NOT NULL,\n            owner_id INTEGER NOT NULL,\n            name TEXT NOT NULL,\n            role_id INTEGER NOT NULL,\n            text_channel_id INTEGER NOT NULL,\n            voice_channel_id INTEGER NOT NULL,\n            created_at INTEGER NOT NULL,\n            UNIQUE (guild_id, owner_id)\n        );\n        CREATE TABLE IF NOT EXISTS crew_members (\n            crew_id INTEGER NOT NULL,\n            guild_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            joined_at INTEGER NOT NULL,\n            PRIMARY KEY (guild_id, user_id)\n        );\n        CREATE TABLE IF NOT EXISTS trade_posts (\n            message_id INTEGER PRIMARY KEY,\n            guild_id INTEGER NOT NULL,\n            channel_id INTEGER NOT NULL,\n            author_id INTEGER NOT NULL,\n            offered TEXT NOT NULL,\n            wanted TEXT NOT NULL,\n            status TEXT NOT NULL DEFAULT 'open',\n            created_at INTEGER NOT NULL\n        );\n        CREATE TABLE IF NOT EXISTS trade_deals (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            guild_id INTEGER NOT NULL,\n            post_message_id INTEGER NOT NULL,\n            seller_id INTEGER NOT NULL,\n            buyer_id INTEGER NOT NULL,\n            channel_id INTEGER NOT NULL UNIQUE,\n            status TEXT NOT NULL DEFAULT 'active',\n            created_at INTEGER NOT NULL\n        );\n        CREATE TABLE IF NOT EXISTS trade_reviews (\n            deal_id INTEGER NOT NULL,\n            reviewer_id INTEGER NOT NULL,\n            target_id INTEGER NOT NULL,\n            stars INTEGER NOT NULL,\n            comment TEXT,\n            created_at INTEGER NOT NULL,\n            PRIMARY KEY (deal_id, reviewer_id)\n        );\n        CREATE TABLE IF NOT EXISTS warnings (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            guild_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            moderator_id INTEGER NOT NULL,\n            reason TEXT NOT NULL,\n            active INTEGER NOT NULL DEFAULT 1,\n            created_at INTEGER NOT NULL,\n            removed_by INTEGER,\n            removed_at INTEGER\n        );\n        CREATE TABLE IF NOT EXISTS sanctions (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            guild_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            moderator_id INTEGER,\n            action TEXT NOT NULL,\n            reason TEXT NOT NULL,\n            created_at INTEGER NOT NULL\n        );\n        CREATE TABLE IF NOT EXISTS community_events (\n            message_id INTEGER PRIMARY KEY,\n            guild_id INTEGER NOT NULL,\n            channel_id INTEGER NOT NULL,\n            host_id INTEGER NOT NULL,\n            name TEXT NOT NULL,\n            description TEXT NOT NULL,\n            starts_at INTEGER NOT NULL,\n            capacity INTEGER NOT NULL,\n            status TEXT NOT NULL DEFAULT 'scheduled',\n            reminded_24h INTEGER NOT NULL DEFAULT 0,\n            reminded_30m INTEGER NOT NULL DEFAULT 0,\n            created_at INTEGER NOT NULL\n        );\n        CREATE TABLE IF NOT EXISTS community_event_entries (\n            message_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            joined_at INTEGER NOT NULL,\n            PRIMARY KEY (message_id, user_id)\n        );\n        CREATE TABLE IF NOT EXISTS player_cvs (\n            guild_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            message_id INTEGER NOT NULL,\n            channel_id INTEGER NOT NULL,\n            roblox_name TEXT NOT NULL,\n            level TEXT NOT NULL,\n            sea TEXT NOT NULL,\n            profile TEXT NOT NULL,\n            availability TEXT NOT NULL,\n            looking_for TEXT NOT NULL,\n            updated_at INTEGER NOT NULL,\n            PRIMARY KEY (guild_id, user_id)\n        );\n        CREATE TABLE IF NOT EXISTS crew_recruitments (\n            message_id INTEGER PRIMARY KEY,\n            guild_id INTEGER NOT NULL,\n            crew_id INTEGER NOT NULL,\n            captain_id INTEGER NOT NULL,\n            description TEXT NOT NULL,\n            requirements TEXT NOT NULL,\n            sought_profiles TEXT NOT NULL,\n            status TEXT NOT NULL DEFAULT 'open',\n            created_at INTEGER NOT NULL\n        );\n        CREATE TABLE IF NOT EXISTS crew_applications (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            guild_id INTEGER NOT NULL,\n            recruitment_message_id INTEGER NOT NULL,\n            crew_id INTEGER NOT NULL,\n            captain_id INTEGER NOT NULL,\n            applicant_id INTEGER NOT NULL,\n            channel_id INTEGER NOT NULL UNIQUE,\n            status TEXT NOT NULL DEFAULT 'open',\n            created_at INTEGER NOT NULL\n        );\n        CREATE TABLE IF NOT EXISTS bot_update_posts (\n            guild_id INTEGER NOT NULL,\n            version TEXT NOT NULL,\n            message_id INTEGER NOT NULL,\n            posted_at INTEGER NOT NULL,\n            PRIMARY KEY (guild_id, version)\n        );\n        CREATE TABLE IF NOT EXISTS audit_log_state (\n            guild_id INTEGER PRIMARY KEY,\n            last_entry_id INTEGER NOT NULL DEFAULT 0\n        );\n        CREATE TABLE IF NOT EXISTS moderation_notes (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            guild_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            moderator_id INTEGER NOT NULL,\n            note TEXT NOT NULL,\n            active INTEGER NOT NULL DEFAULT 1,\n            created_at INTEGER NOT NULL,\n            removed_by INTEGER,\n            removed_at INTEGER\n        );\n        CREATE TABLE IF NOT EXISTS suggestions (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            guild_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            channel_id INTEGER NOT NULL,\n            message_id INTEGER,\n            title TEXT NOT NULL,\n            description TEXT NOT NULL,\n            status TEXT NOT NULL DEFAULT 'pending',\n            staff_id INTEGER,\n            staff_response TEXT,\n            created_at INTEGER NOT NULL,\n            updated_at INTEGER NOT NULL\n        );\n        CREATE TABLE IF NOT EXISTS suggestion_votes (\n            suggestion_id INTEGER NOT NULL,\n            user_id INTEGER NOT NULL,\n            vote INTEGER NOT NULL,\n            voted_at INTEGER NOT NULL,\n            PRIMARY KEY (suggestion_id, user_id)\n        );\n        CREATE TABLE IF NOT EXISTS crew_logs (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            guild_id INTEGER NOT NULL,\n            crew_id INTEGER NOT NULL,\n            actor_id INTEGER NOT NULL,\n            action TEXT NOT NULL,\n            target_id INTEGER,\n            created_at INTEGER NOT NULL\n        );\n        ")
    crew_columns = {row[1] for row in database.execute('PRAGMA table_info(crews)')}
    if 'presentation_message_id' not in crew_columns:
        database.execute('ALTER TABLE crews ADD COLUMN presentation_message_id INTEGER')
    if 'vice_captain_id' not in crew_columns:
        database.execute('ALTER TABLE crews ADD COLUMN vice_captain_id INTEGER')
    if 'max_members' not in crew_columns:
        database.execute('ALTER TABLE crews ADD COLUMN max_members INTEGER NOT NULL DEFAULT 20')
    ticket_columns = {row[1] for row in database.execute('PRAGMA table_info(tickets)')}
    for column_name in ('claimed_at', 'closed_by', 'closed_at'):
        if column_name not in ticket_columns:
            database.execute(f'ALTER TABLE tickets ADD COLUMN {column_name} INTEGER')
    sanction_columns = {row[1] for row in database.execute('PRAGMA table_info(sanctions)')}
    for column_name in ('cancelled_by', 'cancelled_at'):
        if column_name not in sanction_columns:
            database.execute(f'ALTER TABLE sanctions ADD COLUMN {column_name} INTEGER')
    database.commit()

def require_database() -> sqlite3.Connection:
    if database is None:
        raise RuntimeError('Database not initialized')
    return database

def calculate_level(total_xp: int) -> int:
    return math.isqrt(max(total_xp, 0) // 100)

def format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f'{hours} h {minutes:02d} min'

def load_card_font(size: int, *, bold: bool=False) -> ImageFont.FreeTypeFont:
    filenames = ('DejaVuSans-Bold.ttf', 'arialbd.ttf') if bold else ('DejaVuSans.ttf', 'arial.ttf')
    candidates = [*(RANK_ASSET_DIR / filename for filename in filenames), *(Path('C:/Windows/Fonts') / filename for filename in filenames), *(Path('/usr/share/fonts/truetype/dejavu') / filename for filename in filenames)]
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
            return (name, RANK_ASSET_DIR / filename, colour)
    raise RuntimeError('No rank matches the level')

def generate_level_card(*, username: str, level: int, total_xp: int, progress: int, required: int, total_messages: int, voice_seconds: int, leaderboard_position: int) -> io.BytesIO:
    width, height = (1100, 430)
    card = Image.new('RGBA', (width, height), (8, 16, 32, 255))
    draw = ImageDraw.Draw(card)
    rank_name, emblem_path, accent = get_rank_tier(level)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        colour = (int(8 + accent[0] * 0.07 * ratio), int(16 + accent[1] * 0.08 * ratio), int(32 + accent[2] * 0.12 * ratio), 255)
        draw.line((0, y, width, y), fill=colour)
    draw.rounded_rectangle((14, 14, width - 14, height - 14), radius=34, outline=(*accent, 210), width=3)
    draw.ellipse((35, 55, 355, 375), fill=(*accent, 25))
    emblem = Image.open(emblem_path).convert('RGBA')
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
    draw.text((392, 101), f'{rank_name.upper()}  • LEVEL {level}', font=rank_font, fill=accent)
    bar_left, bar_top, bar_right, bar_bottom = (392, 158, 1035, 190)
    draw.rounded_rectangle((bar_left, bar_top, bar_right, bar_bottom), radius=16, fill=(26, 38, 58))
    ratio = min(max(progress / required if required else 1, 0), 1)
    filled_right = bar_left + int((bar_right - bar_left) * ratio)
    if filled_right > bar_left:
        draw.rounded_rectangle((bar_left, bar_top, filled_right, bar_bottom), radius=16, fill=accent)
    draw.text((392, 201), f'{progress:,} / {required:,} XP to the next level', font=small_font, fill=(185, 198, 218))
    stats = ((392, 265, 'XP TOTAL', f'{total_xp:,}'), (620, 265, 'MESSAGES', f'{total_messages:,}'), (840, 265, 'VOCAL TIME', format_duration(voice_seconds)), (392, 346, 'CLASSEMENT', f'#{leaderboard_position}'))
    for x, y, label, value in stats:
        draw.text((x, y), label, font=small_font, fill=(145, 160, 184))
        draw.text((x, y + 27), value, font=stat_font, fill=(245, 248, 255))
    output = io.BytesIO()
    card.convert('RGB').save(output, format='PNG', optimize=True)
    output.seek(0)
    return output

def get_member_stats(guild_id: int, user_id: int) -> tuple[int, int, int, int, int]:
    row = require_database().execute('\n        SELECT message_xp, voice_xp, bonus_xp, voice_seconds, total_messages\n        FROM member_stats\n        WHERE guild_id = ? AND user_id = ?\n        ', (guild_id, user_id)).fetchone()
    return tuple(row) if row is not None else (0, 0, 0, 0, 0)

def award_message_xp(guild_id: int, user_id: int) -> bool:
    now = int(time.time())
    xp = random.randint(MESSAGE_XP_MIN, MESSAGE_XP_MAX)
    connection = require_database()
    previous = connection.execute('\n        SELECT last_message_xp\n        FROM member_stats\n        WHERE guild_id = ? AND user_id = ?\n        ', (guild_id, user_id)).fetchone()
    awarded = previous is None or previous[0] <= now - MESSAGE_XP_COOLDOWN
    connection.execute('\n        INSERT INTO member_stats (\n            guild_id, user_id, message_xp, total_messages, last_message_xp\n        )\n        VALUES (?, ?, ?, 1, ?)\n        ON CONFLICT(guild_id, user_id) DO UPDATE SET\n            total_messages = total_messages + 1,\n            message_xp = message_xp + CASE\n                WHEN last_message_xp <= ? THEN excluded.message_xp\n                ELSE 0\n            END,\n            last_message_xp = CASE\n                WHEN last_message_xp <= ? THEN excluded.last_message_xp\n                ELSE last_message_xp\n            END\n        ', (guild_id, user_id, xp, now, now - MESSAGE_XP_COOLDOWN, now - MESSAGE_XP_COOLDOWN))
    connection.commit()
    return awarded

def award_voice_xp_batch(entries: list[tuple[int, int]]) -> None:
    if not entries:
        return
    connection = require_database()
    connection.executemany('\n        INSERT INTO member_stats (\n            guild_id, user_id, voice_xp, voice_seconds\n        )\n        VALUES (?, ?, ?, 60)\n        ON CONFLICT(guild_id, user_id) DO UPDATE SET\n            voice_xp = voice_xp + excluded.voice_xp,\n            voice_seconds = voice_seconds + 60\n        ', [(guild_id, user_id, VOICE_XP_PER_MINUTE) for guild_id, user_id in entries])
    connection.commit()

async def update_level_role(member: discord.Member) -> None:
    message_xp, voice_xp, bonus_xp, _, _ = get_member_stats(member.guild.id, member.id)
    level = calculate_level(message_xp + voice_xp + bonus_xp)
    progression_names = {role_name for _, role_name in LEVEL_ROLE_THRESHOLDS}
    target_name = next((role_name for required_level, role_name in LEVEL_ROLE_THRESHOLDS if level >= required_level), None)
    current_progression = [role for role in member.roles if role.name in progression_names]
    target_role = discord.utils.get(member.guild.roles, name=target_name) if target_name is not None else None
    roles_to_remove = [role for role in current_progression if role != target_role]
    try:
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason=f'Automatic Progression Level {level}')
        if target_role is not None and target_role not in member.roles:
            await member.add_roles(target_role, reason=f'Automatic Progression Level {level}')
    except discord.Forbidden:
        logging.warning('Could not update %s level role', member)

def contains_suspicious_link(content: str) -> bool:
    for raw_url in URL_PATTERN.findall(content):
        try:
            parsed = urlparse(raw_url)
            hostname = (parsed.hostname or '').lower().removeprefix('www.')
        except ValueError:
            return True
        if not hostname or hostname in URL_SHORTENERS or '@' in parsed.netloc or any((part.startswith('xn--') for part in hostname.split('.'))) or re.fullmatch('\\d{1,3}(?:\\.\\d{1,3}){3}', hostname) or any((marker in raw_url.lower() for marker in SUSPICIOUS_DOMAIN_MARKERS)):
            return True
    return False

async def punish_message(message: discord.Message, *, reason: str, timeout_minutes: int) -> None:
    try:
        await message.delete()
    except discord.HTTPException:
        pass
    if isinstance(message.author, discord.Member):
        try:
            await message.author.timeout(timedelta(minutes=timeout_minutes), reason=reason)
            if message.guild is not None:
                await send_sanction_log(message.guild, action=f'Automatic timeout for {timeout_minutes} min', target=message.author, moderator=None, reason=reason)
        except discord.HTTPException:
            logging.warning('Could not timeout %s', message.author)
    try:
        await message.channel.send(f'⚠️ {message.author.mention} : {reason}.', delete_after=10)
    except discord.HTTPException:
        pass

async def moderate_message(message: discord.Message) -> bool:
    if message.guild is None or not isinstance(message.author, discord.Member) or is_ticket_staff(message.author):
        return False
    raw_lower = message.content.lower()
    mention_count = len({member.id for member in message.mentions}) + len({role.id for role in message.role_mentions})
    if '@everyone' in raw_lower or '@here' in raw_lower or mention_count >= MASS_MENTION_LIMIT:
        await punish_message(message, reason='mass mentions are prohibited', timeout_minutes=MASS_MENTION_TIMEOUT_MINUTES)
        return True
    if contains_suspicious_link(message.content):
        await punish_message(message, reason='potentially fraudulent link detected', timeout_minutes=30)
        return True
    key = (message.guild.id, message.author.id)
    now = time.monotonic()
    timestamps = message_timestamps[key]
    timestamps.append(now)
    while timestamps and timestamps[0] < now - SPAM_WINDOW_SECONDS:
        timestamps.popleft()
    if len(timestamps) >= SPAM_MESSAGE_LIMIT:
        timestamps.clear()
        await punish_message(message, reason='spam detected', timeout_minutes=SPAM_TIMEOUT_MINUTES)
        return True
    return False

class SelfRoleSelect(discord.ui.Select):

    def __init__(self, *, role_names: tuple[str, ...], placeholder: str, custom_id: str, max_values: int) -> None:
        self.role_names = role_names
        super().__init__(placeholder=placeholder, min_values=0, max_values=max_values, options=[discord.SelectOption(label=role_name, value=role_name) for role_name in role_names], custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message('This menu only works in the server.', ephemeral=True)
            return
        group_roles = [role for role_name in self.role_names if (role := discord.utils.get(interaction.guild.roles, name=role_name)) is not None]
        selected_roles = [role for role in group_roles if role.name in self.values]
        roles_to_remove = [role for role in group_roles if role in interaction.user.roles and role not in selected_roles]
        roles_to_add = [role for role in selected_roles if role not in interaction.user.roles]
        try:
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove, reason='Selection of roles by the member')
            if roles_to_add:
                await interaction.user.add_roles(*roles_to_add, reason='Selection of roles by the member')
        except discord.Forbidden:
            await interaction.response.send_message("I can't assign these roles. Put my role above community roles.", ephemeral=True)
            return
        await interaction.response.send_message('Your roles have been updated.', ephemeral=True)

class VerificationView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label='I validate the rules', emoji='✅', style=discord.ButtonStyle.success, custom_id='community:verification:accept')
    async def verify(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message('This check works only in the server.', ephemeral=True)
            return
        member_role = discord.utils.get(interaction.guild.roles, name=MEMBER_ROLE_NAME)
        unverified_role = discord.utils.get(interaction.guild.roles, name=UNVERIFIED_ROLE_NAME)
        if member_role is None or unverified_role is None:
            await interaction.response.send_message('Audit roles are absent. Contact an administrator.', ephemeral=True)
            return
        if member_role in interaction.user.roles:
            await interaction.response.send_message("You're already checked.", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(member_role, reason='Settlement accepted via panel')
            if unverified_role in interaction.user.roles:
                await interaction.user.remove_roles(unverified_role, reason='Verification completed')
        except discord.Forbidden:
            await interaction.response.send_message("I can't change your roles. Put my role above the audit roles.", ephemeral=True)
            return
        await interaction.response.send_message('You now have access to the community.', ephemeral=True)

class RoleSelectionView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(SelfRoleSelect(role_names=NOTIFICATION_ROLES, placeholder='Choose your notifications', custom_id='community:roles:notifications', max_values=len(NOTIFICATION_ROLES)))
        self.add_item(SelfRoleSelect(role_names=ACTIVITY_ROLES, placeholder='Choose your community profile', custom_id='community:roles:activities', max_values=len(ACTIVITY_ROLES)))
        self.add_item(SelfRoleSelect(role_names=PLATFORM_ROLES, placeholder='Choose your Roblox platforms', custom_id='community:roles:platforms', max_values=len(PLATFORM_ROLES)))

def is_ticket_staff(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any((role.name in STAFF_ROLE_NAMES for role in member.roles))

def is_helper(member: discord.Member) -> bool:
    return any((role.name == HELPER_ROLE_NAME for role in member.roles))

async def update_helper_leaderboard(guild: discord.Guild) -> None:
    channel = discord.utils.get(guild.text_channels, name=HELPER_LEADERBOARD_CHANNEL_NAME)
    if channel is None:
        return
    rows = require_database().execute('\n        SELECT user_id, points, resolved_tickets\n        FROM helper_stats WHERE guild_id = ?\n        ORDER BY points DESC, resolved_tickets DESC LIMIT 15\n        ', (guild.id,)).fetchall()
    lines = []
    for position, (user_id, points, resolved) in enumerate(rows, start=1):
        member = guild.get_member(user_id)
        label = member.mention if member is not None else f'<@{user_id}>'
        lines.append(f'`#{position}` {label} — **{points} point(s)** • {resolved} ticket(s)')
    embed = discord.Embed(title='Classification of helpers', description='\n'.join(lines) if lines else 'No ticket solved yet.', colour=discord.Colour.gold())
    try:
        await channel.purge(limit=10, check=lambda message: message.author == bot.user)
        await channel.send(embed=embed)
    except discord.HTTPException:
        logging.exception('Cannot update helper ranking')

async def create_ticket(interaction: discord.Interaction, ticket_type: str, subject: str, details: str) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    guild = interaction.guild
    connection = require_database()
    existing = connection.execute("\n        SELECT channel_id FROM tickets\n        WHERE guild_id = ? AND user_id = ? AND ticket_type = ? AND status = 'open'\n        ", (guild.id, interaction.user.id, ticket_type)).fetchone()
    if existing is not None:
        existing_channel = guild.get_channel(existing[0])
        if existing_channel is not None:
            await interaction.response.send_message(f'You already have a ticket from this guy: {existing_channel.mention}', ephemeral=True)
            return
        connection.execute("UPDATE tickets SET status = 'closed' WHERE channel_id = ?", (existing[0],))
        connection.commit()
    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
    if category is None:
        await interaction.response.send_message('The ticket category is missing. Contact an administrator.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    overwrites = dict(category.overwrites)
    overwrites[interaction.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
    helper_role = discord.utils.get(guild.roles, name=HELPER_ROLE_NAME)
    if helper_role is not None:
        overwrites[helper_role] = discord.PermissionOverwrite(view_channel=ticket_type in {'assistance', 'signalement'}, send_messages=ticket_type in {'assistance', 'signalement'}, read_message_history=ticket_type in {'assistance', 'signalement'}, attach_files=ticket_type in {'assistance', 'signalement'})
    safe_user = ''.join((character for character in interaction.user.name.lower() if character.isalnum() or character == '-'))[:30] or str(interaction.user.id)
    channel = await guild.create_text_channel(stylize_channel_name(f'🎫・{ticket_type}-{safe_user}'), category=category, overwrites=overwrites, reason=f'Ticket {ticket_type} opened by {interaction.user}')
    cursor = connection.execute('\n        INSERT INTO tickets (\n            guild_id, user_id, ticket_type, channel_id, created_at\n        )\n        VALUES (?, ?, ?, ?, ?)\n        ', (guild.id, interaction.user.id, ticket_type, channel.id, int(time.time())))
    connection.commit()
    embed = discord.Embed(title=f'Ticket #{cursor.lastrowid} • {ticket_type.title()}', description=f'Ticket opened by {interaction.user.mention}.\nA member of the team will soon take over the application.', colour=discord.Colour.orange())
    embed.add_field(name='Subject', value=subject[:1024], inline=False)
    embed.add_field(name='Details', value=details[:1024], inline=False)
    embed.set_footer(text='Use the buttons below to manage the ticket')
    await channel.send(content=interaction.user.mention, embed=embed, view=TicketControlView())
    await interaction.followup.send(f'Your ticket was created: {channel.mention}', ephemeral=True)

class TicketModal(discord.ui.Modal):

    def __init__(self, ticket_type: str, title: str) -> None:
        super().__init__(title=title, timeout=300)
        self.ticket_type = ticket_type
        self.subject = discord.ui.TextInput(label='Subject of the application', placeholder='Summarize your request in a few words', max_length=100)
        self.details = discord.ui.TextInput(label='Explain your request', placeholder='Give all relevant information to the staff', style=discord.TextStyle.paragraph, min_length=10, max_length=1000)
        self.add_item(self.subject)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await create_ticket(interaction, self.ticket_type, str(self.subject), str(self.details))

class TicketPanelView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label='Assistance', emoji='🆘', style=discord.ButtonStyle.primary, custom_id='community:ticket:assistance', row=0)
    async def assistance(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketModal('assistance', "🆘 Demande d'assistance"))

    @discord.ui.button(label='Partenariat', emoji='🤝', style=discord.ButtonStyle.secondary, custom_id='community:ticket:partenariat', row=0)
    async def partnership(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketModal('partenariat', '🤝 Demande de partenariat'))

    @discord.ui.button(label='Signalement', emoji='🛡️', style=discord.ButtonStyle.danger, custom_id='community:ticket:signalement', row=0)
    async def report(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketModal('signalement', 'Report a problem'))

    @discord.ui.button(label='Bug', emoji='🐛', style=discord.ButtonStyle.secondary, custom_id='community:ticket:bug', row=1)
    async def bug(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketModal('bug', 'Report bug'))

    @discord.ui.button(label='Procurement problem', emoji='💳', style=discord.ButtonStyle.secondary, custom_id='community:ticket:purchase', row=1)
    async def purchase(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketModal('achat', 'Purchase problem'))

    @discord.ui.button(label='Appel de sanction', emoji='🔐', style=discord.ButtonStyle.secondary, custom_id='community:ticket:appeal', row=1)
    async def appeal(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketModal('appel-sanction', 'Challenge a sanction'))

class RecruitmentModal(discord.ui.Modal):

    def __init__(self) -> None:
        super().__init__(title='', timeout=600)
        self.age = discord.ui.TextInput(label='Your age', placeholder='Indicate your real age', max_length=3)
        self.availability = discord.ui.TextInput(label='Your availability', placeholder='Exemple : semaine 18h-22h, week-end...', max_length=150)
        self.experience = discord.ui.TextInput(label='Your experience', placeholder='Moderation, Discord, communities...', style=discord.TextStyle.paragraph, required=False, max_length=250)
        self.motivation = discord.ui.TextInput(label='Why join the team?', placeholder='Present your motivations and what you can bring', style=discord.TextStyle.paragraph, min_length=30, max_length=500)
        self.add_item(self.age)
        self.add_item(self.availability)
        self.add_item(self.experience)
        self.add_item(self.motivation)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        subject = f'Application staff • {self.age} ans'
        details = f"** Age: ** {self.age}\n** Availability: ** {self.availability}\n** Experience: ** {self.experience or 'None'}\n\n**Motivation :**\n{self.motivation}"
        await create_ticket(interaction, 'recrutement', subject, details)

class RecruitmentPanelView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label='Apply', emoji='📝', style=discord.ButtonStyle.success, custom_id='community:recruitment:apply')
    async def apply(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(RecruitmentModal())

async def close_ticket(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    connection = require_database()
    row = connection.execute("\n        SELECT id, user_id, ticket_type, claimed_by, escalated FROM tickets\n        WHERE channel_id = ? AND status = 'open'\n        ", (channel.id,)).fetchone()
    if row is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message('This channel is not an active ticket.', ephemeral=True)
        return
    ticket_id, opener_id, ticket_type, claimed_by, escalated = row
    helper_can_close = is_helper(interaction.user) and claimed_by == interaction.user.id and (not escalated)
    if interaction.user.id == opener_id and claimed_by is not None and (not is_ticket_staff(interaction.user)):
        await interaction.response.send_message('This ticket is supported. Only the assigned helper or the top staff can now close it.', ephemeral=True)
        return
    if interaction.user.id != opener_id and (not is_ticket_staff(interaction.user)) and (not helper_can_close):
        await interaction.response.send_message('Only the ticket owner or staff can close it.', ephemeral=True)
        return
    await interaction.response.send_message('The ticket will be closed and archived.', ephemeral=True)
    transcript_lines = [f'Ticket #{ticket_id} — {ticket_type}', f'Server: {channel.guild.name} ({channel.guild.id})', f'Channel: {channel.name} ({channel.id})', '']
    async for message in channel.history(limit=None, oldest_first=True):
        content = message.clean_content or '[message without text]'
        attachments = ' '.join((attachment.url for attachment in message.attachments))
        transcript_lines.append(f'[{message.created_at.isoformat()}] {message.author} ({message.author.id}): {content} {attachments}'.rstrip())
    transcript_directory = Path('transcripts')
    transcript_directory.mkdir(exist_ok=True)
    transcript_path = transcript_directory / f'ticket-{ticket_id}.txt'
    transcript_path.write_text('\n'.join(transcript_lines), encoding='utf-8')
    log_channel = discord.utils.get(channel.guild.text_channels, name=TICKET_TRANSCRIPT_CHANNEL_NAME)
    if log_channel is not None:
        embed = discord.Embed(title=f'Ticket #{ticket_id} closed', description=f'Type : **{ticket_type}**\nAuthor : <@{opener_id}>\nClosed by: {interaction.user.mention}', colour=discord.Colour.red())
        await log_channel.send(embed=embed, file=discord.File(transcript_path))
    if claimed_by is not None and (not escalated) and (ticket_type in {'assistance', 'signalement'}):
        assigned_helper = channel.guild.get_member(claimed_by)
        if assigned_helper is None or not is_helper(assigned_helper):
            assigned_helper = None
    else:
        assigned_helper = None
    if assigned_helper is not None:
        connection.execute('\n            INSERT INTO helper_stats (guild_id, user_id, resolved_tickets, points)\n            VALUES (?, ?, 1, 1)\n            ON CONFLICT(guild_id, user_id) DO UPDATE SET\n                resolved_tickets = resolved_tickets + 1,\n                points = points + 1\n            ', (channel.guild.id, assigned_helper.id))
    connection.execute("\n        UPDATE tickets\n        SET status = 'closed', closed_by = ?, closed_at = ?\n        WHERE channel_id = ?\n        ", (interaction.user.id, int(time.time()), channel.id))
    connection.commit()
    await update_helper_leaderboard(channel.guild)
    await channel.delete(reason=f'Ticket #{ticket_id} closed by {interaction.user}')

class TicketCloseConfirmationView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=60)

    @discord.ui.button(label='Confirmer', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if isinstance(interaction.channel, discord.TextChannel):
            await close_ticket(interaction, interaction.channel)

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content='Closed off.', view=None)

class TicketControlView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label='Prendre en charge', emoji='🙋', style=discord.ButtonStyle.primary, custom_id='community:ticket:claim')
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or (not is_ticket_staff(interaction.user) and (not is_helper(interaction.user))) or (not isinstance(interaction.channel, discord.TextChannel)):
            await interaction.response.send_message('This action is reserved for staff.', ephemeral=True)
            return
        connection = require_database()
        row = connection.execute("\n            SELECT id, user_id, claimed_by, ticket_type, escalated FROM tickets\n            WHERE channel_id = ? AND status = 'open'\n            ", (interaction.channel.id,)).fetchone()
        if row is None:
            await interaction.response.send_message('This ticket is no longer active.', ephemeral=True)
            return
        ticket_id, opener_id, claimed_by, ticket_type, escalated = row
        if claimed_by is not None and claimed_by != interaction.user.id:
            await interaction.response.send_message(f'This ticket is already supported by <@{claimed_by}>.', ephemeral=True)
            return
        if claimed_by == interaction.user.id:
            await interaction.response.send_message('You already took care of that ticket.', ephemeral=True)
            return
        if is_helper(interaction.user) and (not is_ticket_staff(interaction.user)):
            if ticket_type not in {'assistance', 'signalement'} or escalated:
                await interaction.response.send_message('This ticket is reserved for the top staff.', ephemeral=True)
                return
        connection.execute('\n            UPDATE tickets SET claimed_by = ?, claimed_at = ?\n            WHERE channel_id = ?\n            ', (interaction.user.id, int(time.time()), interaction.channel.id))
        connection.commit()
        helper_role = discord.utils.get(interaction.guild.roles, name=HELPER_ROLE_NAME)
        if helper_role is not None and is_helper(interaction.user) and (not is_ticket_staff(interaction.user)):
            await interaction.channel.set_permissions(helper_role, view_channel=False, reason=f'Ticket claim by {interaction.user}')
            await interaction.channel.set_permissions(interaction.user, view_channel=True, send_messages=True, read_message_history=True, attach_files=True, reason='Helper assigned to the ticket')
        await interaction.response.send_message(f'• Ticket supported by {interaction.user.mention}.')
        log_channel = discord.utils.get(interaction.guild.text_channels, name=TICKET_LOG_CHANNEL_NAME)
        if log_channel is not None:
            claimed_at = datetime.now(timezone.utc)
            claimed_timestamp = int(claimed_at.timestamp())
            embed = discord.Embed(title=f'Ticket #{ticket_id} pris en charge', colour=discord.Colour.blurple(), timestamp=claimed_at)
            embed.add_field(name='Ticket', value=f"{interaction.channel.mention}\nType : **{ticket_type.replace('-', ' ').title()}**", inline=True)
            embed.add_field(name='Member concerned', value=f'<@{opener_id}>\n`{opener_id}`', inline=True)
            embed.add_field(name='Pris en charge par', value=f'{interaction.user.mention}\n`{interaction.user.id}`', inline=True)
            embed.add_field(name='Exact date and time', value=f'<t:{claimed_timestamp}:F>\n(<t:{claimed_timestamp}:R>)', inline=False)
            try:
                await log_channel.send(embed=embed)
            except discord.HTTPException:
                logging.exception('Could not log ticket claim %s', ticket_id)

    @discord.ui.button(label='Close', emoji='🔒', style=discord.ButtonStyle.danger, custom_id='community:ticket:close')
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message('Confirm the final closure of this ticket?', view=TicketCloseConfirmationView(), ephemeral=True)

def parse_duration(value: str) -> int | None:
    cleaned = value.lower().replace(' ', '')
    matches = re.findall('(\\d+)([smhdw])', cleaned)
    if not matches or ''.join((f'{number}{unit}' for number, unit in matches)) != cleaned:
        return None
    multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
    seconds = sum((int(number) * multipliers[unit] for number, unit in matches))
    return seconds if 10 <= seconds <= 31536000 else None

def format_remaining(seconds: int) -> str:
    if seconds <= 0:
        return 'Completed'
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f'{days} j')
    if hours:
        parts.append(f'{hours} h')
    if minutes:
        parts.append(f'{minutes} min')
    if secs or not parts:
        parts.append(f'{secs} s')
    return ' '.join(parts)

def giveaway_chance(member: discord.Member) -> tuple[float, float, float]:
    invite_count = get_invite_count(member.guild.id, member.id)
    invite_bonus = next((bonus for required, _, bonus in INVITE_ROLE_TIERS if invite_count >= required), 0.0)
    booster_bonus = 1.0 if member.premium_since is not None else 0.0
    return (1.0 + invite_bonus + booster_bonus, invite_bonus, booster_bonus)

def get_giveaway(message_id: int) -> tuple | None:
    return require_database().execute('\n        SELECT guild_id, channel_id, host_id, prize, winners_count, ends_at, status\n        FROM giveaways WHERE message_id = ?\n        ', (message_id,)).fetchone()

async def select_giveaway_winners(guild: discord.Guild, message_id: int, winners_count: int) -> list[discord.Member]:
    rows = require_database().execute('SELECT user_id FROM giveaway_entries WHERE message_id = ?', (message_id,)).fetchall()
    pool = [member for user_id, in rows if (member := guild.get_member(user_id)) is not None and (not member.bot)]
    winners: list[discord.Member] = []
    while pool and len(winners) < winners_count:
        weights = [giveaway_chance(member)[0] for member in pool]
        selected_index = random.choices(range(len(pool)), weights=weights, k=1)[0]
        winners.append(pool.pop(selected_index))
    return winners

async def finish_giveaway(message_id: int, *, reroll: bool=False) -> list[discord.Member]:
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
    mentions = ', '.join((winner.mention for winner in winners))
    if reroll:
        await channel.send(f"** Reissued for {prize}** : {mentions or 'no valid participant'}")
        return winners
    require_database().execute("UPDATE giveaways SET status = 'ended' WHERE message_id = ?", (message_id,))
    require_database().commit()
    try:
        message = await channel.fetch_message(message_id)
        embed = message.embeds[0] if message.embeds else discord.Embed()
        embed.colour = discord.Colour.dark_grey()
        embed.title = f'Giveaway completed • {prize}'
        embed.description = f"Completed <t:{ends_at}:R>\nWinner(s): {mentions or '** No valid participant **'}"
        await message.edit(embed=embed, view=GiveawayView())
    except discord.HTTPException:
        logging.exception('Cannot modify Giveaway %s', message_id)
    await channel.send(f'Congratulations {mentions} Hey! You win **{prize}**.' if winners else f'The ** Giveaway{prize}** is completed without valid participant.')
    return winners

class GiveawayView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label='Participer', emoji='🎉', style=discord.ButtonStyle.success, custom_id='community:giveaway:join')
    async def participate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.message is None or interaction.guild is None or (not isinstance(interaction.user, discord.Member)):
            return
        giveaway = get_giveaway(interaction.message.id)
        if giveaway is None or giveaway[6] != 'active' or giveaway[5] <= int(time.time()):
            await interaction.response.send_message('This giveaway is over.', ephemeral=True)
            return
        connection = require_database()
        existing = connection.execute('\n            SELECT 1 FROM giveaway_entries\n            WHERE message_id = ? AND user_id = ?\n            ', (interaction.message.id, interaction.user.id)).fetchone()
        if existing:
            connection.execute('DELETE FROM giveaway_entries WHERE message_id = ? AND user_id = ?', (interaction.message.id, interaction.user.id))
            connection.commit()
            await interaction.response.send_message('Your participation has been withdrawn.', ephemeral=True)
            return
        connection.execute('\n            INSERT INTO giveaway_entries (message_id, user_id, joined_at)\n            VALUES (?, ?, ?)\n            ', (interaction.message.id, interaction.user.id, int(time.time())))
        connection.commit()
        chance, _, _ = giveaway_chance(interaction.user)
        await interaction.response.send_message(f'Registered participation with **{chance:g} chance(s)**.', ephemeral=True)

    @discord.ui.button(label='Participants', emoji='👥', style=discord.ButtonStyle.secondary, custom_id='community:giveaway:participants')
    async def participants(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.message is None or interaction.guild is None:
            return
        rows = require_database().execute('SELECT user_id FROM giveaway_entries WHERE message_id = ?', (interaction.message.id,)).fetchall()
        names = [member.mention for user_id, in rows[:40] if (member := interaction.guild.get_member(user_id)) is not None]
        suffix = f'\n… et {len(rows) - 40} autre(s).' if len(rows) > 40 else ''
        await interaction.response.send_message(f"**{len(rows)} participant(s)**\n{(', '.join(names) if names else 'No participants.')}{suffix}", ephemeral=True)

    @discord.ui.button(label='Duration', emoji='⏳', style=discord.ButtonStyle.primary, custom_id='community:giveaway:duration')
    async def duration(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.message is None:
            return
        giveaway = get_giveaway(interaction.message.id)
        if giveaway is None:
            await interaction.response.send_message('Giveaway introuvable.', ephemeral=True)
            return
        remaining = max(giveaway[5] - int(time.time()), 0)
        await interaction.response.send_message(f'Temps restant exact : **{format_remaining(remaining)}**.', ephemeral=True)

    @discord.ui.button(label='Mes chances', emoji='🍀', style=discord.ButtonStyle.primary, custom_id='community:giveaway:chance')
    async def chances(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return
        total, invite_bonus, booster_bonus = giveaway_chance(interaction.user)
        await interaction.response.send_message(f'Chance de base : **1**\nBonus invitations : **+{invite_bonus:g}**\nBonus Booster : **+{booster_bonus:g}**\nTotal : **{total:g} chance(s)**', ephemeral=True)

async def ensure_roles(guild: discord.Guild, reason: str) -> tuple[dict[str, discord.Role], int]:
    roles: dict[str, discord.Role] = {}
    created_count = 0
    for spec in ROLE_SPECS:
        role = discord.utils.get(guild.roles, name=spec.name)
        if role is None:
            role = await guild.create_role(name=spec.name, colour=discord.Colour(spec.colour), permissions=spec.permissions, hoist=spec.hoist, mentionable=False, reason=reason)
            created_count += 1
        roles[spec.name] = role
    founder_role = roles['👑・Founder']
    owner = guild.owner
    if owner is None:
        owner = await guild.fetch_member(guild.owner_id)
    if founder_role not in owner.roles:
        await owner.add_roles(founder_role, reason=reason)
    return (roles, created_count)

async def ensure_helper_role(guild: discord.Guild) -> discord.Role | None:
    role = discord.utils.get(guild.roles, name=HELPER_ROLE_NAME)
    if role is not None:
        if role.permissions != discord.Permissions.none():
            try:
                await role.edit(permissions=discord.Permissions.none(), reason='Secure role Helper')
            except discord.HTTPException:
                logging.exception('Cannot secure Helper role')
        return role
    legacy_role = discord.utils.get(guild.roles, name='🆘・Helper Blox Fruits')
    try:
        if legacy_role is not None:
            await legacy_role.edit(name=HELPER_ROLE_NAME, permissions=discord.Permissions.none(), reason='Migration of Helper Role')
            return legacy_role
        return await guild.create_role(name=HELPER_ROLE_NAME, colour=discord.Colour(2600544), permissions=discord.Permissions.none(), hoist=True, mentionable=False, reason='Automatic creation of the Helper role')
    except discord.HTTPException:
        logging.exception('Cannot create or migrate Helper role')
        return None

async def ensure_superior_staff_area(guild: discord.Guild) -> tuple[discord.Role | None, discord.CategoryChannel | None]:
    role = discord.utils.get(guild.roles, name=SUPERIOR_STAFF_ROLE_NAME)
    try:
        if role is None:
            role = await guild.create_role(name=SUPERIOR_STAFF_ROLE_NAME, colour=discord.Colour(9323693), permissions=discord.Permissions.none(), hoist=True, mentionable=False, reason='Automatic creation of the Senior Staff role')
        elif role.permissions != discord.Permissions.none():
            await role.edit(permissions=discord.Permissions.none(), reason='Securing the role of senior staff')
    except discord.HTTPException:
        logging.exception('Could not create top staff role')
        return (None, None)
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
                await member.add_roles(role, reason='Automatic access to reassembled tickets')
            except discord.HTTPException:
                logging.exception('Could not assign Staff greater than %s', member.id)
    bot_member = guild.me
    if bot_member is None:
        return (role, None)
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {guild.default_role: discord.PermissionOverwrite(view_channel=False), role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True), bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True, manage_messages=True)}
    category = discord.utils.get(guild.categories, name=ESCALATED_TICKET_CATEGORY_NAME)
    try:
        if category is None:
            category = await guild.create_category(ESCALATED_TICKET_CATEGORY_NAME, overwrites=overwrites, reason='Automatic creation of reassembled tickets')
        else:
            await category.edit(overwrites=overwrites, reason='Secured tickets')
        open_ticket_category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
        if open_ticket_category is not None and category.position != open_ticket_category.position + 1:
            await category.edit(position=open_ticket_category.position + 1, reason='Placement of reassembled tickets')
    except discord.HTTPException:
        logging.exception('Cannot create or secure top staff category')
        return (role, None)
    return (role, category)

async def secure_escalated_ticket(channel: discord.TextChannel, opener_id: int, superior_role: discord.Role, category: discord.CategoryChannel) -> None:
    guild = channel.guild
    opener = guild.get_member(opener_id)
    bot_member = guild.me
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {guild.default_role: discord.PermissionOverwrite(view_channel=False), superior_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)}
    if bot_member is not None:
        overwrites[bot_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, manage_channels=True, manage_messages=True)
    if opener is not None:
        overwrites[opener] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
    await channel.edit(category=category, overwrites=overwrites, reason='Ticket moved to the top staff')

async def reconcile_helper_ticket_permissions(guild: discord.Guild, helper_role: discord.Role) -> None:
    connection = require_database()
    rows = connection.execute("\n        SELECT channel_id, user_id, ticket_type, claimed_by, escalated\n        FROM tickets WHERE guild_id = ? AND status = 'open'\n        ", (guild.id,)).fetchall()
    database_changed = False
    for channel_id, opener_id, ticket_type, claimed_by, escalated in rows:
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            connection.execute("UPDATE tickets SET status = 'closed' WHERE channel_id = ?", (channel_id,))
            database_changed = True
            continue
        helper_ticket = ticket_type in {'assistance', 'signalement'} and (not escalated)
        assigned_helper = guild.get_member(claimed_by) if claimed_by is not None else None
        valid_assignment = assigned_helper is not None and is_helper(assigned_helper)
        try:
            if helper_ticket and valid_assignment:
                await channel.set_permissions(helper_role, view_channel=False, reason='Restoration of the exclusive claim Helper')
                await channel.set_permissions(assigned_helper, view_channel=True, send_messages=True, read_message_history=True, attach_files=True, reason='Restoring the assigned Helper')
            elif helper_ticket:
                if claimed_by is not None:
                    connection.execute('\n                        UPDATE tickets SET claimed_by = NULL\n                        WHERE channel_id = ?\n                        ', (channel_id,))
                    database_changed = True
                    former_helper = guild.get_member(claimed_by)
                    if former_helper is not None and former_helper.id != opener_id:
                        await channel.set_permissions(former_helper, view_channel=False, reason='Former Helper removed from ticket')
                await channel.set_permissions(helper_role, view_channel=True, send_messages=True, read_message_history=True, attach_files=True, reason='Ticket available for Helpers')
            else:
                await channel.set_permissions(helper_role, view_channel=False, reason='Type of ticket reserved for the top staff')
                if escalated:
                    superior_role = discord.utils.get(guild.roles, name=SUPERIOR_STAFF_ROLE_NAME)
                    escalated_category = discord.utils.get(guild.categories, name=ESCALATED_TICKET_CATEGORY_NAME)
                    if superior_role is not None and escalated_category is not None:
                        await secure_escalated_ticket(channel, opener_id, superior_role, escalated_category)
        except discord.HTTPException:
            logging.exception('Could not repair ticket Helper permissions %s', channel_id)
    if database_changed:
        connection.commit()

def staff_overwrites(guild: discord.Guild, roles: dict[str, discord.Role]) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True, manage_channels=True)}
    for role_name in ('👑・Founder', '⚙️・Studio Manager', '🛡️・Administrator', '🔨・Moderator', '🧪・Trial Moderator'):
        overwrites[roles[role_name]] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, connect=True, speak=True)
    return overwrites

def member_overwrites(guild: discord.Guild, roles: dict[str, discord.Role]) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {guild.default_role: discord.PermissionOverwrite(view_channel=False), roles[MEMBER_ROLE_NAME]: discord.PermissionOverwrite(view_channel=True, read_message_history=True), guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True, manage_channels=True)}
    for role_name in STAFF_ROLE_NAMES:
        overwrites[roles[role_name]] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, connect=True, speak=True)
    return overwrites

def verification_overwrites(guild: discord.Guild, roles: dict[str, discord.Role]) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    return {guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False), roles[UNVERIFIED_ROLE_NAME]: discord.PermissionOverwrite(view_channel=True, read_message_history=True), guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)}

def staff_voice_overwrites(guild: discord.Guild, roles: dict[str, discord.Role]) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {guild.default_role: discord.PermissionOverwrite(view_channel=False), roles[MEMBER_ROLE_NAME]: discord.PermissionOverwrite(view_channel=True, connect=False, speak=False), guild.me: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, move_members=True, manage_channels=True)}
    for role_name in STAFF_ROLE_NAMES:
        overwrites[roles[role_name]] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, stream=True, move_members=True)
    return overwrites

def server_stats_overwrites(guild: discord.Guild, roles: dict[str, discord.Role]) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {guild.default_role: discord.PermissionOverwrite(view_channel=False), roles[MEMBER_ROLE_NAME]: discord.PermissionOverwrite(view_channel=True, connect=False, speak=False), guild.me: discord.PermissionOverwrite(view_channel=True, connect=False, speak=False, manage_channels=True)}
    for role_name in STAFF_ROLE_NAMES:
        overwrites[roles[role_name]] = discord.PermissionOverwrite(view_channel=True, connect=False, speak=False)
    return overwrites

def find_category(guild: discord.Guild, name: str) -> discord.CategoryChannel | None:
    return discord.utils.get(guild.categories, name=name)

def find_channel(guild: discord.Guild, name: str, category: discord.CategoryChannel | None, kind: ChannelKind) -> discord.abc.GuildChannel | None:
    expected_type = {'text': discord.ChannelType.text, 'voice': discord.ChannelType.voice, 'stage': discord.ChannelType.stage_voice}[kind]
    return discord.utils.find(lambda channel: channel.name == name and channel.category == category and (channel.type == expected_type), guild.channels)

async def ensure_channel(guild: discord.Guild, spec: ChannelSpec, category: discord.CategoryChannel | None, reason: str, *, reuse_existing: bool=True) -> tuple[discord.abc.GuildChannel, bool, bool]:
    existing = find_channel(guild, spec.name, category, spec.kind) if reuse_existing else None
    used_stage_fallback = False
    if reuse_existing and existing is None and (spec.kind == 'stage'):
        existing = find_channel(guild, spec.name, category, 'voice')
        used_stage_fallback = existing is not None
    if existing is not None:
        if isinstance(existing, discord.VoiceChannel) and existing.user_limit != spec.user_limit:
            await existing.edit(user_limit=spec.user_limit, reason=reason)
        return (existing, False, used_stage_fallback)
    if spec.kind == 'text':
        channel = await guild.create_text_channel(spec.name, category=category, reason=reason)
    elif spec.kind == 'voice':
        channel = await guild.create_voice_channel(spec.name, category=category, user_limit=spec.user_limit, reason=reason)
    else:
        try:
            channel = await guild.create_stage_channel(spec.name, category=category, reason=reason)
        except discord.HTTPException as error:
            if error.code != 50024:
                raise
            channel = await guild.create_voice_channel(spec.name, category=category, reason=reason)
            return (channel, True, True)
    return (channel, True, False)

async def delete_all_channels(guild: discord.Guild, reason: str) -> tuple[int, int]:
    """Removes channels and categories, except protected identifiers."""
    channels = list(guild.channels)
    regular_channels = [channel for channel in channels if not isinstance(channel, discord.CategoryChannel) and channel.id not in PRESERVED_SETUP_CHANNEL_IDS]
    categories = [channel for channel in channels if isinstance(channel, discord.CategoryChannel) and channel.id not in PRESERVED_SETUP_CHANNEL_IDS]
    deleted_channels = 0
    deleted_categories = 0
    for channel in regular_channels:
        try:
            await channel.delete(reason=reason)
            deleted_channels += 1
        except discord.HTTPException as error:
            logging.warning('Channel %s (%s) kept during /setup: %s', channel.name, channel.id, error)
    for category in categories:
        try:
            await category.delete(reason=reason)
            deleted_categories += 1
        except discord.HTTPException as error:
            logging.warning('Category %s (%s) kept during /setup: %s', category.name, category.id, error)
    return (deleted_channels, deleted_categories)

async def update_server_stats(guild: discord.Guild) -> None:
    category = discord.utils.get(guild.categories, name=SERVER_STATS_CATEGORY_NAME)
    if category is None:
        return
    total_members = guild.member_count or len(guild.members)
    bot_count = sum((member.bot for member in guild.members))
    human_count = max(total_members - bot_count, 0)
    boost_count = guild.premium_subscription_count or 0
    desired_names = {'👥・': stylize_channel_name(f'👥・Members: {total_members}'), '✅・': stylize_channel_name(f'✅・Humans: {human_count}'), '🤖・': stylize_channel_name(f'🤖・Bots : {bot_count}'), '💎・': stylize_channel_name(f'💎・Boosts : {boost_count}')}
    for channel in category.voice_channels:
        desired_name = next((name for prefix, name in desired_names.items() if channel.name.startswith(prefix)), None)
        if desired_name is not None and channel.name != desired_name:
            try:
                await channel.edit(name=desired_name, reason='Automatic updating of server statistics')
            except discord.HTTPException:
                logging.exception('Could not update meter %s', channel.id)

def get_invite_count(guild_id: int, user_id: int) -> int:
    row = require_database().execute('\n        SELECT invite_count FROM invite_stats\n        WHERE guild_id = ? AND user_id = ?\n        ', (guild_id, user_id)).fetchone()
    return int(row[0]) if row is not None else 0

async def update_invite_role(member: discord.Member) -> None:
    count = get_invite_count(member.guild.id, member.id)
    tier_names = {role_name for _, role_name, _ in INVITE_ROLE_TIERS}
    target_name = next((role_name for required, role_name, _ in INVITE_ROLE_TIERS if count >= required), None)
    target_role = discord.utils.get(member.guild.roles, name=target_name) if target_name is not None else None
    roles_to_remove = [role for role in member.roles if role.name in tier_names and role != target_role]
    try:
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason=f'Automatic update after {count} invitations')
        if target_role is not None and target_role not in member.roles:
            await member.add_roles(target_role, reason=f'Automatic scale reached with {count} invitations')
    except discord.Forbidden:
        logging.warning('Could not update invitation role of %s', member)

async def refresh_invite_cache(guild: discord.Guild) -> list[discord.Invite]:
    try:
        invites = await guild.invites()
    except discord.Forbidden:
        logging.warning('Permission Manage the server required to track invitations on %s', guild.id)
        return []
    invite_cache[guild.id] = {invite.code: invite.uses or 0 for invite in invites}
    return invites

async def restore_invite_roles(guild: discord.Guild) -> None:
    rows = require_database().execute('SELECT user_id FROM invite_stats WHERE guild_id = ? AND invite_count > 0', (guild.id,)).fetchall()
    for user_id, in rows:
        member = guild.get_member(user_id)
        if member is not None:
            await update_invite_role(member)

async def process_member_invite(member: discord.Member) -> None:
    previous = invite_cache.get(member.guild.id, {})
    try:
        current_invites = await member.guild.invites()
    except discord.Forbidden:
        return
    used_invite = next((invite for invite in current_invites if (invite.uses or 0) > previous.get(invite.code, 0)), None)
    invite_cache[member.guild.id] = {invite.code: invite.uses or 0 for invite in current_invites}
    if used_invite is None or used_invite.inviter is None:
        return
    inviter_id = used_invite.inviter.id
    connection = require_database()
    connection.execute('\n        INSERT INTO invite_stats (guild_id, user_id, invite_count)\n        VALUES (?, ?, 1)\n        ON CONFLICT(guild_id, user_id) DO UPDATE SET\n            invite_count = invite_count + 1\n        ', (member.guild.id, inviter_id))
    connection.commit()
    inviter = member.guild.get_member(inviter_id)
    if inviter is not None:
        await update_invite_role(inviter)

def build_voice_help_embed() -> discord.Embed:
    return discord.Embed(title='Manage your temporary voice channel', description=f'Join **{TEMP_VOICE_TRIGGER_NAME}** to automatically create a channel named `{TEMP_VOICE_PREFIX}your username`.\n\n`/voice-limit` — choose the maximum number of members\n`/voice-private` — lock or reopen the channel\n`/voice-invite` — allow a member into a private channel\n`/voice-kick` — disconnect a member from the channel\n\nThe channel is automatically deleted when it becomes empty.', colour=discord.Colour.blue())

def owned_temporary_channel(interaction: discord.Interaction) -> discord.VoiceChannel | None:
    if not isinstance(interaction.user, discord.Member):
        return None
    voice = interaction.user.voice
    if voice is None or not isinstance(voice.channel, discord.VoiceChannel):
        return None
    channel = voice.channel
    if channel.name == TEMP_VOICE_TRIGGER_NAME or channel.category is None or channel.category.name != TEMP_VOICE_CATEGORY_NAME:
        return None
    overwrite = channel.overwrites_for(interaction.user)
    return channel if overwrite.manage_channels is True else None

@bot.tree.command(name='voice-limit', description='Change your voice channel limit.')
@app_commands.rename(nombre='limit')
@app_commands.describe(nombre='Maximum number of members, or 0 for no limit')
async def voice_limit(interaction: discord.Interaction, nombre: int) -> None:
    channel = owned_temporary_channel(interaction)
    if channel is None:
        await interaction.response.send_message('You must be in the temporary voice you own.', ephemeral=True)
        return
    if not 0 <= nombre <= 99:
        await interaction.response.send_message('The limit must be between 0 and 99.', ephemeral=True)
        return
    await channel.edit(user_limit=nombre, reason=f'Limit chosen by the owner {interaction.user}')
    label = 'Unlimited' if nombre == 0 else f'fixed at **{nombre}**'
    await interaction.response.send_message(f'The voice capacity is now {label}.', ephemeral=True)

@bot.tree.command(name='voice-private', description='Make your voice channel private or public again.')
@app_commands.describe(active='Yes to lock the voice, no to reopen it')
async def voice_private(interaction: discord.Interaction, active: bool) -> None:
    channel = owned_temporary_channel(interaction)
    if channel is None or interaction.guild is None:
        await interaction.response.send_message('You must be in the temporary voice you own.', ephemeral=True)
        return
    member_role = discord.utils.get(interaction.guild.roles, name=MEMBER_ROLE_NAME)
    if member_role is None:
        await interaction.response.send_message('The Member role cannot be found.', ephemeral=True)
        return
    await channel.set_permissions(member_role, view_channel=True, connect=not active, reason=f'Private mode modified by {interaction.user}')
    state = 'Private' if active else 'public 🔓'
    await interaction.response.send_message(f'Your voice is now **{state}**.', ephemeral=True)

@bot.tree.command(name='voice-invite', description='Authorizes a member to join your private voice.')
@app_commands.rename(membre='member')
@app_commands.describe(membre='Member to allow in your voice')
async def voice_invite(interaction: discord.Interaction, membre: discord.Member) -> None:
    channel = owned_temporary_channel(interaction)
    if channel is None:
        await interaction.response.send_message('You must be in the temporary voice you own.', ephemeral=True)
        return
    await channel.set_permissions(membre, view_channel=True, connect=True, reason=f'Invitation by the owner {interaction.user}')
    invite_sent = False
    invite_view = discord.ui.View(timeout=3600)
    invite_view.add_item(discord.ui.Button(label='Join the voice channel', emoji='🔊', style=discord.ButtonStyle.link, url=channel.jump_url))
    invite_embed = discord.Embed(title='Temporary voice channel invitation', description=f'**{interaction.user.display_name}** invites you to join **{channel.name}** on **{interaction.guild.name}**.\n\nClick on the button below to open the voice channel directly.', colour=discord.Colour.blue())
    try:
        await membre.send(embed=invite_embed, view=invite_view)
        invite_sent = True
    except discord.HTTPException:
        logging.info('Private voice invitation message impossible for %s', membre.id)
    confirmation = f'{membre.mention} can now join {channel.mention}.'
    if invite_sent:
        confirmation += ' An invitation with a direct link was sent to him in private.'
    else:
        confirmation += " I couldn't send him a private message, probably because his private messages are closed."
    await interaction.response.send_message(confirmation, ephemeral=True)

@bot.tree.command(name='voice-kick', description='Disconnect a member from your voice channel.')
@app_commands.rename(membre='member')
@app_commands.describe(membre='Member to disconnect from your voice')
async def voice_kick(interaction: discord.Interaction, membre: discord.Member) -> None:
    channel = owned_temporary_channel(interaction)
    if channel is None:
        await interaction.response.send_message('You must be in the temporary voice you own.', ephemeral=True)
        return
    if membre == interaction.user:
        await interaction.response.send_message("You can't expel yourself.", ephemeral=True)
        return
    if membre.voice is None or membre.voice.channel != channel:
        await interaction.response.send_message('This member is not in your voice.', ephemeral=True)
        return
    await membre.move_to(None, reason=f'Expelled from the temporary voice by {interaction.user}')
    await interaction.response.send_message(f'{membre.mention} was expelled from the voice channels.', ephemeral=True)

class PlayerCVModal(discord.ui.Modal):

    def __init__(self) -> None:
        super().__init__(title='Create or edit my CV', timeout=600)
        self.roblox_name = discord.ui.TextInput(label='Roblox username', placeholder='Your exact nickname on Roblox', max_length=50)
        self.level_and_sea = discord.ui.TextInput(label='Current level and progression', placeholder='Example: level 2550, third sea', max_length=100)
        self.profile = discord.ui.TextInput(label='Fruit, race, V4, bonus and activities', placeholder='Present your profile and what you like to do', style=discord.TextStyle.paragraph, max_length=600)
        self.availability = discord.ui.TextInput(label='Availability, platform and region', placeholder='Example: evenings, PC, Europe, microphone available', max_length=200)
        self.looking_for = discord.ui.TextInput(label='What you are looking for', placeholder='Describe the crew you want to join', style=discord.TextStyle.paragraph, max_length=500)
        for item in (self.roblox_name, self.level_and_sea, self.profile, self.availability, self.looking_for):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member) or (not isinstance(interaction.channel, discord.TextChannel)) or (interaction.channel.name != PLAYER_CV_CHANNEL_NAME):
            await interaction.response.send_message(f'Use this form in `{PLAYER_CV_CHANNEL_NAME}`.', ephemeral=True)
            return
        connection = require_database()
        previous = connection.execute('\n            SELECT channel_id, message_id FROM player_cvs\n            WHERE guild_id = ? AND user_id = ?\n            ', (interaction.guild.id, interaction.user.id)).fetchone()
        embed = discord.Embed(title=f'📄 CV de {interaction.user.display_name}', colour=discord.Colour.teal(), timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name='🎮 Roblox username', value=str(self.roblox_name), inline=False)
        embed.add_field(name='Level and progression', value=str(self.level_and_sea), inline=False)
        embed.add_field(name='🍈 Profil Blox Fruits', value=str(self.profile), inline=False)
        embed.add_field(name='Availability', value=str(self.availability), inline=False)
        embed.add_field(name='🔎 Recherche', value=str(self.looking_for), inline=False)
        embed.set_footer(text=f'ID Discord : {interaction.user.id} • CV required to apply')
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
        connection.execute('\n            INSERT INTO player_cvs (\n                guild_id, user_id, message_id, channel_id, roblox_name,\n                level, sea, profile, availability, looking_for, updated_at\n            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n            ON CONFLICT(guild_id, user_id) DO UPDATE SET\n                message_id = excluded.message_id,\n                channel_id = excluded.channel_id,\n                roblox_name = excluded.roblox_name,\n                level = excluded.level,\n                sea = excluded.sea,\n                profile = excluded.profile,\n                availability = excluded.availability,\n                looking_for = excluded.looking_for,\n                updated_at = excluded.updated_at\n            ', (interaction.guild.id, interaction.user.id, message.id, interaction.channel.id, str(self.roblox_name), str(self.level_and_sea), '', str(self.profile), str(self.availability), str(self.looking_for), int(time.time())))
        connection.commit()
        await interaction.response.send_message(f'Your CV is published: {message.jump_url}', ephemeral=True)

@bot.tree.command(name='cv-create', description='Open the player CV form.')
async def cv_create(interaction: discord.Interaction) -> None:
    if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name != PLAYER_CV_CHANNEL_NAME:
        await interaction.response.send_message(f'This command is only available in `{PLAYER_CV_CHANNEL_NAME}`.', ephemeral=True)
        return
    await interaction.response.send_modal(PlayerCVModal())

def member_level(guild_id: int, user_id: int) -> int:
    row = require_database().execute('\n        SELECT message_xp + voice_xp + bonus_xp\n        FROM member_stats WHERE guild_id = ? AND user_id = ?\n        ', (guild_id, user_id)).fetchone()
    return calculate_level(row[0] if row is not None else 0)

async def reset_dynamic_server_data(guild: discord.Guild) -> None:
    connection = require_database()
    captain_role = discord.utils.get(guild.roles, name=CAPTAIN_ROLE_NAME)
    if captain_role is not None and captain_role.members:
        for captain in tuple(captain_role.members):
            try:
                await captain.remove_roles(captain_role, reason='Reset crews')
            except discord.HTTPException:
                pass
    crew_rows = connection.execute('SELECT id, role_id FROM crews WHERE guild_id = ?', (guild.id,)).fetchall()
    for _, role_id in crew_rows:
        role = guild.get_role(role_id)
        if role is not None:
            try:
                await role.delete(reason='Full server reset')
            except discord.HTTPException:
                pass
    for crew_id, _ in crew_rows:
        connection.execute('DELETE FROM crew_members WHERE crew_id = ?', (crew_id,))
    connection.execute('DELETE FROM crews WHERE guild_id = ?', (guild.id,))
    connection.execute('DELETE FROM player_cvs WHERE guild_id = ?', (guild.id,))
    connection.execute('DELETE FROM crew_applications WHERE guild_id = ?', (guild.id,))
    connection.execute('DELETE FROM crew_recruitments WHERE guild_id = ?', (guild.id,))
    connection.execute("UPDATE trade_deals SET status = 'closed' WHERE guild_id = ?", (guild.id,))
    connection.execute("UPDATE trade_posts SET status = 'closed' WHERE guild_id = ?", (guild.id,))
    connection.execute("UPDATE community_events SET status = 'cancelled' WHERE guild_id = ?", (guild.id,))
    connection.execute("\n        UPDATE tickets\n        SET status = 'closed', claimed_by = NULL, claimed_at = NULL,\n            closed_at = COALESCE(closed_at, ?)\n        WHERE guild_id = ? AND status = 'open'\n        ", (int(time.time()), guild.id))
    connection.execute("UPDATE giveaways SET status = 'cancelled' WHERE guild_id = ?", (guild.id,))
    suggestion_ids = connection.execute('SELECT id FROM suggestions WHERE guild_id = ?', (guild.id,)).fetchall()
    for suggestion_id, in suggestion_ids:
        connection.execute('DELETE FROM suggestion_votes WHERE suggestion_id = ?', (suggestion_id,))
    connection.execute('DELETE FROM suggestions WHERE guild_id = ?', (guild.id,))
    connection.commit()

async def update_crew_presentation(guild: discord.Guild, crew_id: int) -> None:
    connection = require_database()
    row = connection.execute('\n        SELECT owner_id, name, text_channel_id, presentation_message_id,\n               vice_captain_id, max_members\n        FROM crews WHERE id = ? AND guild_id = ?\n        ', (crew_id, guild.id)).fetchone()
    if row is None:
        return
    member_count = connection.execute('SELECT COUNT(*) FROM crew_members WHERE crew_id = ?', (crew_id,)).fetchone()[0]
    channel = discord.utils.get(guild.text_channels, name=CREW_PRESENTATION_CHANNEL_NAME)
    if channel is None:
        return
    private_channel = guild.get_channel(row[2])
    embed = discord.Embed(title=f'🏴\u200d☠️ {row[1]}', description=f'**Captain:** <@{row[0]}>\n' + (f'**Vice-captain:** <@{row[4]}>\n' if row[4] is not None else '') + f'**Members:** {member_count}/{row[5]}\n** Created on {guild.name}**', colour=discord.Colour.gold())
    if isinstance(private_channel, discord.TextChannel):
        embed.set_footer(text=f'Private channel: {private_channel.name}')
    message = None
    if row[3] is not None:
        try:
            message = await channel.fetch_message(row[3])
            await message.edit(embed=embed)
        except discord.HTTPException:
            message = None
    if message is None:
        message = await channel.send(embed=embed)
        connection.execute('UPDATE crews SET presentation_message_id = ? WHERE id = ?', (message.id, crew_id))
        connection.commit()

def crew_captain_guide_embed(crew_name: str) -> discord.Embed:
    embed = discord.Embed(title=f'🏴\u200d☠️ Captain commands • {crew_name}', description='Keep this message: it contains all the controls to manage your crew.', colour=discord.Colour.gold())
    embed.add_field(name='Management of members', value='`/crew-invite` — add member\n`/crew-kick` — Remove Member\n`/crew-members` — show crew\n`/crew-vice-captain` — name or replace second\n`/crew-limit` — set capacity between 2 and 50', inline=False)
    embed.add_field(name='Leadership and recruitment', value='`/crew-recruitment` — publish the official announcement\n`/crew-transfer` — permanently transmit crew\n`/crew-leaderboard` — Compare Crew Activity\n`/crew-commands` — receive this guide again\n`/crew-delete` — permanently delete the crew', inline=False)
    embed.add_field(name="Members' orders", value='`/crew-leave` — leave the crew voluntarily.', inline=False)
    embed.set_footer(text='A person can only belong to one crew.')
    return embed

async def send_crew_captain_guide(captain: discord.Member, crew_name: str) -> bool:
    try:
        await captain.send(embed=crew_captain_guide_embed(crew_name))
        return True
    except discord.HTTPException:
        return False

async def log_crew_action(guild: discord.Guild, crew_id: int, actor_id: int, action: str, target_id: int | None=None) -> None:
    connection = require_database()
    connection.execute('\n        INSERT INTO crew_logs (\n            guild_id, crew_id, actor_id, action, target_id, created_at\n        ) VALUES (?, ?, ?, ?, ?, ?)\n        ', (guild.id, crew_id, actor_id, action[:500], target_id, int(time.time())))
    connection.commit()
    row = connection.execute('SELECT text_channel_id FROM crews WHERE id = ? AND guild_id = ?', (crew_id, guild.id)).fetchone()
    if row is None:
        return
    channel = guild.get_channel(row[0])
    if isinstance(channel, discord.TextChannel):
        target = f' • <@{target_id}>' if target_id is not None else ''
        try:
            await channel.send(f'📒 <t:{int(time.time())}:F> • <@{actor_id}> — **{action}**{target}')
        except discord.HTTPException:
            pass

async def create_crew_for_member(guild: discord.Guild, owner: discord.Member, clean_name: str, *, reason: str) -> discord.TextChannel:
    category = discord.utils.get(guild.categories, name=CREW_CATEGORY_NAME)
    if category is None:
        raise RuntimeError('The private category of crews is absent.')
    connection = require_database()
    role = await guild.create_role(name=f'🏴\u200d☠️・{clean_name}', colour=discord.Colour.random(), reason=reason)
    overwrites = dict(category.overwrites)
    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, connect=True, speak=True)
    text_channel: discord.TextChannel | None = None
    voice_channel: discord.VoiceChannel | None = None
    try:
        text_channel = await guild.create_text_channel(stylize_channel_name(f'🏴\u200d☠️・{clean_name}'), category=category, overwrites=overwrites, reason=reason)
        voice_channel = await guild.create_voice_channel(stylize_channel_name(f'🔊・{clean_name}'), category=category, overwrites=overwrites, reason=reason)
        cursor = connection.execute('\n            INSERT INTO crews (\n                guild_id, owner_id, name, role_id, text_channel_id,\n                voice_channel_id, created_at\n            ) VALUES (?, ?, ?, ?, ?, ?, ?)\n            ', (guild.id, owner.id, clean_name, role.id, text_channel.id, voice_channel.id, int(time.time())))
        connection.execute('\n            INSERT INTO crew_members (crew_id, guild_id, user_id, joined_at)\n            VALUES (?, ?, ?, ?)\n            ', (cursor.lastrowid, guild.id, owner.id, int(time.time())))
        connection.commit()
        captain_role = discord.utils.get(guild.roles, name=CAPTAIN_ROLE_NAME)
        roles_to_add = [role]
        if captain_role is not None:
            roles_to_add.append(captain_role)
        await owner.add_roles(*roles_to_add, reason='Crew Creator and Captain')
        await text_channel.send(f'Welcome to crew **{clean_name}** de {owner.mention} !')
        guide_sent = await send_crew_captain_guide(owner, clean_name)
        if not guide_sent:
            await text_channel.send(f'{owner.mention}Your private messages are closed. Use `/crew-commands` after opening them to receive the guide.')
        await log_crew_action(guild, cursor.lastrowid, owner.id, 'Crew created')
        await update_crew_presentation(guild, cursor.lastrowid)
        return text_channel
    except Exception:
        logging.exception('Crew creation failure %s', clean_name)
        connection.rollback()
        for channel in (text_channel, voice_channel):
            if channel is not None:
                try:
                    await channel.delete(reason='Crew creation failed')
                except discord.HTTPException:
                    pass
        try:
            await role.delete(reason='Crew creation failed')
        except discord.HTTPException:
            pass
        raise

@bot.tree.command(name='crew-create', description='Create your permanent crew.')
@app_commands.describe(nom='Name of crew')
async def crew_create(interaction: discord.Interaction, nom: str) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    level = member_level(interaction.guild.id, interaction.user.id)
    if level < CREW_CREATION_LEVEL:
        await interaction.response.send_message(f'You have to be level **{CREW_CREATION_LEVEL}** to create a crew. You are level **{level}**.', ephemeral=True)
        return
    connection = require_database()
    if connection.execute('SELECT 1 FROM crew_members WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, interaction.user.id)).fetchone():
        await interaction.response.send_message('You already belong to a crew. A person can only have one crew.', ephemeral=True)
        return
    clean_name = ' '.join(nom.split())[:40]
    if len(clean_name) < 2:
        await interaction.response.send_message('The name must contain at least two characters.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        text_channel = await create_crew_for_member(interaction.guild, interaction.user, clean_name, reason=f'Crew created by {interaction.user}')
    except Exception:
        await interaction.followup.send('Crew creation failed. Verifies that the private category of crews exists and that the bot can manage roles and channels.', ephemeral=True)
        return
    await interaction.followup.send(f'Crew **{clean_name}** created: {text_channel.mention}', ephemeral=True)

@bot.tree.command(name='crew-create-for', description='Creates a crew and directs its captain.')
@app_commands.describe(membre='Member to become captain', nom='Name of new crew')
async def crew_create_for_command(interaction: discord.Interaction, membre: discord.Member, nom: str) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    if not is_ticket_staff(interaction.user) or is_helper(interaction.user):
        await interaction.response.send_message('This order is reserved for the top staff.', ephemeral=True)
        return
    if membre.bot:
        await interaction.response.send_message('A bot cannot become a captain.', ephemeral=True)
        return
    if require_database().execute('SELECT 1 FROM crew_members WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, membre.id)).fetchone():
        await interaction.response.send_message('This member already belongs to a crew.', ephemeral=True)
        return
    clean_name = ' '.join(nom.split())[:40]
    if len(clean_name) < 2:
        await interaction.response.send_message('The name must contain at least two characters.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        text_channel = await create_crew_for_member(interaction.guild, membre, clean_name, reason=f'Crew created for {membre} by {interaction.user}')
    except Exception:
        await interaction.followup.send('Creation failed. Checks permissions and the private category of crews.', ephemeral=True)
        return
    await interaction.followup.send(f'✅ {membre.mention} is now captain of **{clean_name}** : {text_channel.mention}', ephemeral=True)

class CrewRecruitmentModal(discord.ui.Modal):

    def __init__(self, crew_id: int) -> None:
        super().__init__(title='Recruitment of my crew', timeout=600)
        self.crew_id = crew_id
        self.description_input = discord.ui.TextInput(label='Crew presentation', placeholder='Atmosphere, objectives and main activities', style=discord.TextStyle.paragraph, min_length=30, max_length=800)
        self.requirements = discord.ui.TextInput(label='Conditions for joining', placeholder='Level, sea, activity, micro, age...', style=discord.TextStyle.paragraph, max_length=600)
        self.sought_profiles = discord.ui.TextInput(label='Searched profiles', placeholder='PvP, raids, sea events, farm, fruits sought...', style=discord.TextStyle.paragraph, max_length=600)
        self.add_item(self.description_input)
        self.add_item(self.requirements)
        self.add_item(self.sought_profiles)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name != CREW_RECRUITMENT_CHANNEL_NAME:
            await interaction.response.send_message(f'Use this form in `{CREW_RECRUITMENT_CHANNEL_NAME}`.', ephemeral=True)
            return
        connection = require_database()
        crew = connection.execute('\n            SELECT name FROM crews\n            WHERE id = ? AND guild_id = ? AND owner_id = ?\n            ', (self.crew_id, interaction.guild.id, interaction.user.id)).fetchone()
        if crew is None:
            await interaction.response.send_message("You don't own this crew anymore.", ephemeral=True)
            return
        previous_rows = connection.execute("\n            SELECT message_id FROM crew_recruitments\n            WHERE crew_id = ? AND status = 'open'\n            ", (self.crew_id,)).fetchall()
        for message_id, in previous_rows:
            try:
                old_message = await interaction.channel.fetch_message(message_id)
                await old_message.delete()
            except discord.HTTPException:
                pass
        connection.execute("\n            UPDATE crew_recruitments SET status = 'replaced'\n            WHERE crew_id = ? AND status = 'open'\n            ", (self.crew_id,))
        embed = discord.Embed(title=f'🏴\u200d☠️ {crew[0]} recrute !', description=str(self.description_input), colour=discord.Colour.gold(), timestamp=datetime.now(timezone.utc))
        embed.add_field(name='📋 Conditions', value=str(self.requirements), inline=False)
        embed.add_field(name='Searched profiles', value=str(self.sought_profiles), inline=False)
        embed.add_field(name='👑 Capitaine', value=interaction.user.mention, inline=False)
        embed.set_footer(text='A player CV is required to apply')
        message = await interaction.channel.send(embed=embed, view=CrewRecruitmentView())
        connection.execute('\n            INSERT INTO crew_recruitments (\n                message_id, guild_id, crew_id, captain_id, description,\n                requirements, sought_profiles, created_at\n            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)\n            ', (message.id, interaction.guild.id, self.crew_id, interaction.user.id, str(self.description_input), str(self.requirements), str(self.sought_profiles), int(time.time())))
        connection.commit()
        await interaction.response.send_message(f'Your recruitment is published: {message.jump_url}', ephemeral=True)

@bot.tree.command(name='crew-recruitment', description="Publish your crew's recruitment announcement.")
async def crew_recruitment(interaction: discord.Interaction) -> None:
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name != CREW_RECRUITMENT_CHANNEL_NAME:
        await interaction.response.send_message(f'This command is only available in `{CREW_RECRUITMENT_CHANNEL_NAME}`.', ephemeral=True)
        return
    crew = require_database().execute('\n        SELECT id FROM crews WHERE guild_id = ? AND owner_id = ?\n        ', (interaction.guild.id, interaction.user.id)).fetchone()
    if crew is None:
        await interaction.response.send_message('Only captains with crews can publish here.', ephemeral=True)
        return
    await interaction.response.send_modal(CrewRecruitmentModal(crew[0]))

async def finish_crew_application(interaction: discord.Interaction, *, accepted: bool) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member) or (not isinstance(interaction.channel, discord.TextChannel)):
        return
    connection = require_database()
    application = connection.execute("\n        SELECT id, crew_id, captain_id, applicant_id FROM crew_applications\n        WHERE channel_id = ? AND status = 'open'\n        ", (interaction.channel.id,)).fetchone()
    if application is None:
        await interaction.response.send_message('This application has already been completed.', ephemeral=True)
        return
    if interaction.user.id != application[2] and (not is_ticket_staff(interaction.user)):
        await interaction.response.send_message('Only the captain or the staff can decide.', ephemeral=True)
        return
    applicant = interaction.guild.get_member(application[3])
    crew = connection.execute('SELECT name, role_id FROM crews WHERE id = ?', (application[1],)).fetchone()
    if applicant is None or crew is None:
        await interaction.response.send_message('The member or crew cannot be found.', ephemeral=True)
        return
    if accepted:
        already_member = connection.execute('SELECT 1 FROM crew_members WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, applicant.id)).fetchone()
        if already_member:
            await interaction.response.send_message('This member has already joined a crew.', ephemeral=True)
            return
        role = interaction.guild.get_role(crew[1])
        if role is None:
            await interaction.response.send_message("The crew's role could not be found.", ephemeral=True)
            return
        connection.execute('\n            INSERT INTO crew_members (crew_id, guild_id, user_id, joined_at)\n            VALUES (?, ?, ?, ?)\n            ', (application[1], interaction.guild.id, applicant.id, int(time.time())))
        await applicant.add_roles(role, reason=f'Accepted in {crew[0]}')
        status = 'accepted'
        announcement = f'✅ {applicant.mention} is accepted in crew **{crew[0]}** !'
    else:
        status = 'rejected'
        announcement = f'The application for {applicant.mention} is refused.'
    connection.execute('UPDATE crew_applications SET status = ? WHERE id = ?', (status, application[0]))
    connection.commit()
    await interaction.response.send_message(announcement)
    await update_crew_presentation(interaction.guild, application[1])
    await asyncio.sleep(10)
    try:
        await interaction.channel.delete(reason=f'Crew application {status}')
    except discord.HTTPException:
        pass

class CrewApplicationView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label='Accepter', emoji='✅', style=discord.ButtonStyle.success, custom_id='community:crew:application:accept')
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await finish_crew_application(interaction, accepted=True)

    @discord.ui.button(label='Refuser', emoji='❌', style=discord.ButtonStyle.danger, custom_id='community:crew:application:reject')
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await finish_crew_application(interaction, accepted=False)

class CrewRecruitmentView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label='Postuler', emoji='📨', style=discord.ButtonStyle.primary, custom_id='community:crew:apply')
    async def apply(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or interaction.message is None or (not isinstance(interaction.user, discord.Member)):
            return
        connection = require_database()
        recruitment = connection.execute('\n            SELECT crew_id, captain_id, status FROM crew_recruitments\n            WHERE message_id = ?\n            ', (interaction.message.id,)).fetchone()
        if recruitment is None or recruitment[2] != 'open':
            await interaction.response.send_message('This recruitment is no longer open.', ephemeral=True)
            return
        if interaction.user.id == recruitment[1]:
            await interaction.response.send_message("You can't apply to your own crew.", ephemeral=True)
            return
        if connection.execute('SELECT 1 FROM crew_members WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, interaction.user.id)).fetchone():
            await interaction.response.send_message('You already belong to a crew.', ephemeral=True)
            return
        cv = connection.execute('\n            SELECT roblox_name, level, profile, availability, looking_for,\n                   message_id, channel_id\n            FROM player_cvs WHERE guild_id = ? AND user_id = ?\n            ', (interaction.guild.id, interaction.user.id)).fetchone()
        if cv is None:
            await interaction.response.send_message(f'You must first create your CV with `/cv-create` in `{PLAYER_CV_CHANNEL_NAME}`.', ephemeral=True)
            return
        if connection.execute("\n            SELECT 1 FROM crew_applications\n            WHERE guild_id = ? AND applicant_id = ? AND status = 'open'\n            ", (interaction.guild.id, interaction.user.id)).fetchone():
            await interaction.response.send_message('You already have a crew application in progress.', ephemeral=True)
            return
        captain = interaction.guild.get_member(recruitment[1])
        crew = connection.execute('SELECT name FROM crews WHERE id = ?', (recruitment[0],)).fetchone()
        category = discord.utils.get(interaction.guild.categories, name=CREW_CATEGORY_NAME)
        if captain is None or crew is None or category is None:
            await interaction.response.send_message('This crew is no longer available.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        overwrites = dict(category.overwrites)
        for participant in (captain, interaction.user):
            overwrites[participant] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
        channel = await interaction.guild.create_text_channel(stylize_channel_name(f'📨・candidature-{interaction.user.display_name[:25]}'), category=category, overwrites=overwrites, reason=f'Candidate for crew {crew[0]}')
        cursor = connection.execute('\n            INSERT INTO crew_applications (\n                guild_id, recruitment_message_id, crew_id, captain_id,\n                applicant_id, channel_id, created_at\n            ) VALUES (?, ?, ?, ?, ?, ?, ?)\n            ', (interaction.guild.id, interaction.message.id, recruitment[0], captain.id, interaction.user.id, channel.id, int(time.time())))
        connection.commit()
        cv_link = f'https://discord.com/channels/{interaction.guild.id}/{cv[6]}/{cv[5]}'
        embed = discord.Embed(title=f'📨 Candidature #{cursor.lastrowid} • {crew[0]}', description=f'Candidat : {interaction.user.mention}\nCaptain: {captain.mention}\n[See CV published]({cv_link})', colour=discord.Colour.blue())
        embed.add_field(name='🎮 Roblox', value=cv[0], inline=False)
        embed.add_field(name='Level', value=cv[1], inline=False)
        embed.add_field(name='🍈 Profil', value=cv[2], inline=False)
        embed.add_field(name='Availability', value=cv[3], inline=False)
        embed.add_field(name='🔎 Recherche', value=cv[4], inline=False)
        await channel.send(content=f'{captain.mention} {interaction.user.mention}', embed=embed, view=CrewApplicationView())
        await interaction.followup.send(f'Your application is open: {channel.mention}', ephemeral=True)

def get_managed_crew(guild_id: int, user_id: int) -> tuple | None:
    return require_database().execute('\n        SELECT id, owner_id, vice_captain_id, name, role_id, text_channel_id,\n               voice_channel_id, max_members\n        FROM crews\n        WHERE guild_id = ? AND (owner_id = ? OR vice_captain_id = ?)\n        ', (guild_id, user_id, user_id)).fetchone()

@bot.tree.command(name='crew-commands', description='Receive in private the complete guide of his crew.')
async def crew_commands(interaction: discord.Interaction) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    crew = get_managed_crew(interaction.guild.id, interaction.user.id)
    if crew is None:
        await interaction.response.send_message("You don't run any crew.", ephemeral=True)
        return
    if await send_crew_captain_guide(interaction.user, crew[3]):
        await interaction.response.send_message('The full guide just sent you a private message.', ephemeral=True)
    else:
        await interaction.response.send_message("I can't send you an MP. Authorizes private messages from server members and then tries again.", ephemeral=True)

@bot.tree.command(name='crew-invite', description='Add a member to your crew.')
async def crew_invite(interaction: discord.Interaction, membre: discord.Member) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    crew = get_managed_crew(interaction.guild.id, interaction.user.id)
    if crew is None:
        await interaction.response.send_message('You must be a captain or vice captain.', ephemeral=True)
        return
    if membre.bot or membre.id == interaction.user.id:
        await interaction.response.send_message('This member cannot be added.', ephemeral=True)
        return
    connection = require_database()
    if connection.execute('SELECT 1 FROM crew_members WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, membre.id)).fetchone():
        await interaction.response.send_message('This member already belongs to a crew.', ephemeral=True)
        return
    member_count = connection.execute('SELECT COUNT(*) FROM crew_members WHERE crew_id = ?', (crew[0],)).fetchone()[0]
    if member_count >= crew[7]:
        await interaction.response.send_message(f'The crew has reached its limit of **{crew[7]} members**.', ephemeral=True)
        return
    role = interaction.guild.get_role(crew[4])
    if role is None:
        await interaction.response.send_message("The crew's role could not be found.", ephemeral=True)
        return
    connection.execute('\n        INSERT INTO crew_members (crew_id, guild_id, user_id, joined_at)\n        VALUES (?, ?, ?, ?)\n        ', (crew[0], interaction.guild.id, membre.id, int(time.time())))
    connection.commit()
    try:
        await membre.add_roles(role, reason=f'Guest in {crew[3]} by {interaction.user}')
    except discord.HTTPException:
        connection.execute('DELETE FROM crew_members WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, membre.id))
        connection.commit()
        await interaction.response.send_message('I could not assign the role to this member.', ephemeral=True)
        return
    await log_crew_action(interaction.guild, crew[0], interaction.user.id, 'Member added', membre.id)
    await update_crew_presentation(interaction.guild, crew[0])
    await interaction.response.send_message(f'✅ {membre.mention} joined **{crew[3]}**.', ephemeral=True)
    try:
        await membre.send(f'You joined the crew **{crew[3]}** on **{interaction.guild.name}**.')
    except discord.HTTPException:
        pass

@bot.tree.command(name='crew-kick', description='Excludes a member of your crew.')
async def crew_exclude(interaction: discord.Interaction, membre: discord.Member, raison: str) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    crew = get_managed_crew(interaction.guild.id, interaction.user.id)
    if crew is None:
        await interaction.response.send_message('You must be a captain or vice captain.', ephemeral=True)
        return
    if membre.id == crew[1]:
        await interaction.response.send_message('The captain cannot be excluded.', ephemeral=True)
        return
    if interaction.user.id == crew[2] and membre.id == crew[2]:
        await interaction.response.send_message('The vice captain cannot exclude himself with this order.', ephemeral=True)
        return
    connection = require_database()
    membership = connection.execute('\n        SELECT 1 FROM crew_members\n        WHERE crew_id = ? AND guild_id = ? AND user_id = ?\n        ', (crew[0], interaction.guild.id, membre.id)).fetchone()
    if membership is None:
        await interaction.response.send_message('This member is not part of your crew.', ephemeral=True)
        return
    connection.execute('DELETE FROM crew_members WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, membre.id))
    if membre.id == crew[2]:
        connection.execute('UPDATE crews SET vice_captain_id = NULL WHERE id = ?', (crew[0],))
    connection.commit()
    role = interaction.guild.get_role(crew[4])
    if role is not None:
        await membre.remove_roles(role, reason=f'Removed from {crew[3]} : {raison[:200]}')
    await log_crew_action(interaction.guild, crew[0], interaction.user.id, f'Excluded member • {raison[:300]}', membre.id)
    await update_crew_presentation(interaction.guild, crew[0])
    await interaction.response.send_message(f'✅ {membre.mention} has been excluded from **{crew[3]}**.', ephemeral=True)

@bot.tree.command(name='crew-vice-captain', description='Name or replace the vice captain.')
async def crew_vice_captain(interaction: discord.Interaction, membre: discord.Member) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    crew = require_database().execute('\n        SELECT id, name, text_channel_id, voice_channel_id, vice_captain_id\n        FROM crews WHERE guild_id = ? AND owner_id = ?\n        ', (interaction.guild.id, interaction.user.id)).fetchone()
    if crew is None:
        await interaction.response.send_message('Only the captain can appoint his vice captain.', ephemeral=True)
        return
    if membre.id == interaction.user.id:
        await interaction.response.send_message("You're already a captain.", ephemeral=True)
        return
    membership = require_database().execute('SELECT 1 FROM crew_members WHERE crew_id = ? AND user_id = ?', (crew[0], membre.id)).fetchone()
    if membership is None:
        await interaction.response.send_message('This member must first belong to your crew.', ephemeral=True)
        return
    require_database().execute('UPDATE crews SET vice_captain_id = ? WHERE id = ?', (membre.id, crew[0]))
    require_database().commit()
    former_vice = interaction.guild.get_member(crew[4]) if crew[4] is not None else None
    for channel_id in crew[2:4]:
        channel = interaction.guild.get_channel(channel_id)
        if channel is not None:
            if former_vice is not None and former_vice.id != membre.id:
                await channel.set_permissions(former_vice, overwrite=None, reason='Replacement of Vice-Captain')
            await channel.set_permissions(membre, view_channel=True, send_messages=True, read_message_history=True, connect=True, speak=True, manage_messages=True, move_members=True, reason='Vice-Captain of the crew')
    await log_crew_action(interaction.guild, crew[0], interaction.user.id, 'Vice-Captain appointed', membre.id)
    await send_crew_captain_guide(membre, crew[1])
    await interaction.response.send_message(f'✅ {membre.mention} is vice-captain of **{crew[1]}**.', ephemeral=True)

@bot.tree.command(name='crew-limit', description='Sets the maximum number of members.')
async def crew_limit(interaction: discord.Interaction, limite: int) -> None:
    if interaction.guild is None:
        return
    crew = require_database().execute('SELECT id, name FROM crews WHERE guild_id = ? AND owner_id = ?', (interaction.guild.id, interaction.user.id)).fetchone()
    if crew is None:
        await interaction.response.send_message('Only the master can change the limit.', ephemeral=True)
        return
    count = require_database().execute('SELECT COUNT(*) FROM crew_members WHERE crew_id = ?', (crew[0],)).fetchone()[0]
    if limite < max(2, count) or limite > 50:
        await interaction.response.send_message(f'The limit must be between **{max(2, count)}** and **50**.', ephemeral=True)
        return
    require_database().execute('UPDATE crews SET max_members = ? WHERE id = ?', (limite, crew[0]))
    require_database().commit()
    await log_crew_action(interaction.guild, crew[0], interaction.user.id, f'Limit set to {limite} members')
    await interaction.response.send_message(f'✅ **{crew[1]}** now accepts up to **{limite} members**.', ephemeral=True)

@bot.tree.command(name='crew-members', description='Display your crew members.')
async def crew_members_command(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    row = require_database().execute('\n        SELECT c.id, c.name, c.owner_id, c.vice_captain_id, c.max_members\n        FROM crew_members cm JOIN crews c ON c.id = cm.crew_id\n        WHERE cm.guild_id = ? AND cm.user_id = ?\n        ', (interaction.guild.id, interaction.user.id)).fetchone()
    if row is None:
        await interaction.response.send_message("You don't belong to any crew.", ephemeral=True)
        return
    member_rows = require_database().execute('\n        SELECT user_id, joined_at FROM crew_members\n        WHERE crew_id = ? ORDER BY joined_at\n        ', (row[0],)).fetchall()
    lines = []
    for user_id, joined_at in member_rows:
        badge = '👑' if user_id == row[2] else '⚔️' if user_id == row[3] else '•'
        lines.append(f'{badge} <@{user_id}> • from <t:{joined_at}:d>')
    await interaction.response.send_message(embed=discord.Embed(title=f'🏴\u200d☠️ {row[1]} • {len(lines)}/{row[4]}', description='\n'.join(lines)[:4000], colour=discord.Colour.gold()), ephemeral=True)

@bot.tree.command(name='crew-transfer', description='Definitely transfer your crew to a member.')
async def crew_transfer(interaction: discord.Interaction, nouveau_capitaine: discord.Member) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    connection = require_database()
    crew = connection.execute('\n        SELECT id, name, vice_captain_id, text_channel_id, voice_channel_id\n        FROM crews WHERE guild_id = ? AND owner_id = ?\n        ', (interaction.guild.id, interaction.user.id)).fetchone()
    if crew is None:
        await interaction.response.send_message("You're not captain of any crew.", ephemeral=True)
        return
    if connection.execute('SELECT 1 FROM crew_members WHERE crew_id = ? AND user_id = ?', (crew[0], nouveau_capitaine.id)).fetchone() is None:
        await interaction.response.send_message('The new captain must belong to your crew.', ephemeral=True)
        return
    connection.execute('\n        UPDATE crews SET owner_id = ?, vice_captain_id = NULL WHERE id = ?\n        ', (nouveau_capitaine.id, crew[0]))
    connection.commit()
    former_vice = interaction.guild.get_member(crew[2]) if crew[2] is not None else None
    if former_vice is not None:
        for channel_id in crew[3:5]:
            channel = interaction.guild.get_channel(channel_id)
            if channel is not None:
                await channel.set_permissions(former_vice, overwrite=None, reason="Transfer from the captain's office")
    captain_role = discord.utils.get(interaction.guild.roles, name=CAPTAIN_ROLE_NAME)
    if captain_role is not None:
        await interaction.user.remove_roles(captain_role, reason='Transfer of crew')
        await nouveau_capitaine.add_roles(captain_role, reason='New captain of the crew')
    await log_crew_action(interaction.guild, crew[0], interaction.user.id, 'Captainship transferred', nouveau_capitaine.id)
    await send_crew_captain_guide(nouveau_capitaine, crew[1])
    await update_crew_presentation(interaction.guild, crew[0])
    await interaction.response.send_message(f'✅ {nouveau_capitaine.mention} is now captain of **{crew[1]}**.', ephemeral=True)

@bot.tree.command(name='crew-leaderboard', description='Shows crew activity ranking.')
async def crew_ranking(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    rows = require_database().execute('\n        SELECT c.name, COUNT(cm.user_id),\n               COALESCE(SUM(ms.message_xp + ms.voice_xp + ms.bonus_xp), 0)\n        FROM crews c\n        LEFT JOIN crew_members cm ON cm.crew_id = c.id\n        LEFT JOIN member_stats ms\n          ON ms.guild_id = c.guild_id AND ms.user_id = cm.user_id\n        WHERE c.guild_id = ?\n        GROUP BY c.id ORDER BY 3 DESC LIMIT 15\n        ', (interaction.guild.id,)).fetchall()
    lines = [f'`#{position}` **{name}** • {members} member(s) • **{xp:,} XP**' for position, (name, members, xp) in enumerate(rows, start=1)]
    await interaction.response.send_message(embed=discord.Embed(title='Classification of crews', description='\n'.join(lines) or 'No crew.', colour=discord.Colour.gold()))

@bot.tree.command(name='crew-leave', description='Leave your crew.')
async def crew_leave(interaction: discord.Interaction) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    connection = require_database()
    row = connection.execute('\n        SELECT c.id, c.owner_id, c.name, c.role_id, c.text_channel_id,\n               c.voice_channel_id, c.vice_captain_id\n        FROM crew_members cm JOIN crews c ON c.id = cm.crew_id\n        WHERE cm.guild_id = ? AND cm.user_id = ?\n        ', (interaction.guild.id, interaction.user.id)).fetchone()
    if row is None:
        await interaction.response.send_message("You don't belong to any crew.", ephemeral=True)
        return
    if row[1] == interaction.user.id:
        await interaction.response.send_message('The owner must use `/crew-delete`.', ephemeral=True)
        return
    connection.execute('DELETE FROM crew_members WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, interaction.user.id))
    connection.execute('\n        UPDATE crews SET vice_captain_id = NULL\n        WHERE id = ? AND vice_captain_id = ?\n        ', (row[0], interaction.user.id))
    connection.commit()
    role = interaction.guild.get_role(row[3])
    if role is not None:
        await interaction.user.remove_roles(role, reason='Departure of crew')
    if row[6] == interaction.user.id:
        for channel_id in row[4:6]:
            channel = interaction.guild.get_channel(channel_id)
            if channel is not None:
                await channel.set_permissions(interaction.user, overwrite=None, reason='Departure of Vice-Captain')
    await update_crew_presentation(interaction.guild, row[0])
    await log_crew_action(interaction.guild, row[0], interaction.user.id, 'Member voluntarily left', interaction.user.id)
    await interaction.response.send_message(f'You left **{row[2]}**.', ephemeral=True)

@bot.tree.command(name='crew-delete', description='Remove your crew.')
async def crew_delete(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    connection = require_database()
    row = connection.execute('\n        SELECT id, name, role_id, text_channel_id, voice_channel_id,\n               presentation_message_id\n        FROM crews WHERE guild_id = ? AND owner_id = ?\n        ', (interaction.guild.id, interaction.user.id)).fetchone()
    if row is None:
        await interaction.response.send_message("You don't own any crew.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    recruitment_messages = connection.execute('SELECT message_id FROM crew_recruitments WHERE crew_id = ?', (row[0],)).fetchall()
    application_channels = connection.execute("\n        SELECT channel_id FROM crew_applications\n        WHERE crew_id = ? AND status = 'open'\n        ", (row[0],)).fetchall()
    connection.execute("UPDATE crew_recruitments SET status = 'closed' WHERE crew_id = ?", (row[0],))
    connection.execute("UPDATE crew_applications SET status = 'closed' WHERE crew_id = ?", (row[0],))
    connection.execute('DELETE FROM crew_members WHERE crew_id = ?', (row[0],))
    connection.execute('DELETE FROM crews WHERE id = ?', (row[0],))
    connection.commit()
    for channel_id in row[3:5]:
        channel = interaction.guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.delete(reason=f'Crew {row[1]} deleted')
            except discord.HTTPException:
                pass
    for channel_id, in application_channels:
        channel = interaction.guild.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.delete(reason=f'Crew {row[1]} deleted')
            except discord.HTTPException:
                pass
    role = interaction.guild.get_role(row[2])
    if role is not None:
        try:
            await role.delete(reason=f'Crew {row[1]} deleted')
        except discord.HTTPException:
            pass
    captain_role = discord.utils.get(interaction.guild.roles, name=CAPTAIN_ROLE_NAME)
    if captain_role is not None and isinstance(interaction.user, discord.Member):
        await interaction.user.remove_roles(captain_role, reason='Crew deleted')
    presentation_channel = discord.utils.get(interaction.guild.text_channels, name=CREW_PRESENTATION_CHANNEL_NAME)
    if presentation_channel is not None and row[5] is not None:
        try:
            presentation = await presentation_channel.fetch_message(row[5])
            await presentation.delete()
        except discord.HTTPException:
            pass
    recruitment_channel = discord.utils.get(interaction.guild.text_channels, name=CREW_RECRUITMENT_CHANNEL_NAME)
    if recruitment_channel is not None:
        for message_id, in recruitment_messages:
            try:
                recruitment = await recruitment_channel.fetch_message(message_id)
                await recruitment.delete()
            except discord.HTTPException:
                pass
    await interaction.followup.send(f'The crew **{row[1]}** has been deleted.', ephemeral=True)

def active_trade_for(guild_id: int, user_id: int) -> tuple | None:
    return require_database().execute("\n        SELECT id, channel_id FROM trade_deals\n        WHERE guild_id = ? AND status = 'active'\n          AND (seller_id = ? OR buyer_id = ?)\n        ", (guild_id, user_id, user_id)).fetchone()

async def close_trade_deal(channel: discord.TextChannel, status: str, closed_by: discord.Member) -> None:
    connection = require_database()
    row = connection.execute("\n        SELECT id, post_message_id FROM trade_deals\n        WHERE channel_id = ? AND status = 'active'\n        ", (channel.id,)).fetchone()
    if row is None:
        return
    connection.execute('UPDATE trade_deals SET status = ? WHERE id = ?', (status, row[0]))
    connection.execute('UPDATE trade_posts SET status = ? WHERE message_id = ?', ('completed' if status == 'completed' else 'closed', row[1]))
    connection.commit()
    await channel.send(f'🔒 Trade **{status}** by {closed_by.mention}. The channel will be deleted in 10 seconds.')
    await asyncio.sleep(10)
    try:
        await channel.delete(reason=f'Trade {status} by {closed_by}')
    except discord.HTTPException:
        pass

class TradeOfferView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="I'm interested.", emoji='🤝', style=discord.ButtonStyle.success, custom_id='community:trade:interested')
    async def interested(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or interaction.message is None or (not isinstance(interaction.user, discord.Member)):
            return
        connection = require_database()
        post = connection.execute('\n            SELECT author_id, offered, wanted, status FROM trade_posts\n            WHERE message_id = ?\n            ', (interaction.message.id,)).fetchone()
        if post is None or post[3] != 'open':
            await interaction.response.send_message('This offer is no longer available.', ephemeral=True)
            return
        if post[0] == interaction.user.id:
            await interaction.response.send_message("You can't accept your own offer.", ephemeral=True)
            return
        if active_trade_for(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message('You have to finish your current trade before you start another.', ephemeral=True)
            return
        if active_trade_for(interaction.guild.id, post[0]):
            await interaction.response.send_message('The author is already engaged in another trade.', ephemeral=True)
            return
        seller = interaction.guild.get_member(post[0])
        if seller is None:
            await interaction.response.send_message('The offer author left the server.', ephemeral=True)
            return
        category = discord.utils.get(interaction.guild.categories, name=PRIVATE_TRADE_CATEGORY_NAME)
        if category is None:
            await interaction.response.send_message('The private trade category is absent. Contact an administrator.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        overwrites = dict(category.overwrites)
        for participant in (seller, interaction.user):
            overwrites[participant] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
        channel = await interaction.guild.create_text_channel(stylize_channel_name(f'🤝・trade-{seller.display_name[:15]}-{interaction.user.display_name[:15]}'), category=category, overwrites=overwrites, reason='Private Discussion for a Trade')
        cursor = connection.execute('\n            INSERT INTO trade_deals (\n                guild_id, post_message_id, seller_id, buyer_id,\n                channel_id, created_at\n            ) VALUES (?, ?, ?, ?, ?, ?)\n            ', (interaction.guild.id, interaction.message.id, seller.id, interaction.user.id, channel.id, int(time.time())))
        connection.execute("UPDATE trade_posts SET status = 'matched' WHERE message_id = ?", (interaction.message.id,))
        connection.commit()
        await channel.send(embed=discord.Embed(title=f'🤝 Trade #{cursor.lastrowid}', description=f"Participants : {seller.mention} et {interaction.user.mention}\n\n**Proposition :** {post[1]}\n**Recherche :** {post[2]}\n\nDiscuss here without sharing identifiers or accepting a promise out of the game's official window.\n\nAt the end, everyone uses `/trade-review`. After both reviews, the channel closes. Use `/trade-close` if the trade is cancelled.", colour=discord.Colour.teal()))
        await interaction.followup.send(f'Trade Channel Created: {channel.mention}', ephemeral=True)

@bot.tree.command(name='trade-publish', description='Publish an offer on the market.')
@app_commands.describe(proposition='What you propose, custom emojis accepted', recherche="What you're looking for, custom emojis accepted")
async def trade_publish(interaction: discord.Interaction, proposition: str, recherche: str) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    if active_trade_for(interaction.guild.id, interaction.user.id):
        await interaction.response.send_message('Finish your current trade before publishing a new offer.', ephemeral=True)
        return
    channel = discord.utils.get(interaction.guild.text_channels, name=TRADE_MARKET_CHANNEL_NAME)
    if channel is None:
        await interaction.response.send_message('The trade market is missing. Contact an administrator.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(title='🤝 Nouvelle offre de trade', description=f'** Proposed by: ** {interaction.user.mention}\n\n📦 **Je propose**\n{proposition[:1000]}\n\n🔎 **Je recherche**\n{recherche[:1000]}', colour=discord.Colour.teal(), timestamp=datetime.now(timezone.utc))
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(text='No exchange between different games or promise of payment after')
    message = await channel.send(embed=embed, view=TradeOfferView())
    require_database().execute('\n        INSERT INTO trade_posts (\n            message_id, guild_id, channel_id, author_id,\n            offered, wanted, created_at\n        ) VALUES (?, ?, ?, ?, ?, ?, ?)\n        ', (message.id, interaction.guild.id, channel.id, interaction.user.id, proposition[:1000], recherche[:1000], int(time.time())))
    require_database().commit()
    await interaction.followup.send(f'Published offer: {message.jump_url}', ephemeral=True)

@bot.tree.command(name='trade-review', description='Assess the other participant in the trade.')
@app_commands.describe(etoiles='Note from 1 to 5', commentaire='Trade Comment')
async def trade_review(interaction: discord.Interaction, etoiles: app_commands.Range[int, 1, 5], commentaire: str='No comment') -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member) or (not isinstance(interaction.channel, discord.TextChannel)):
        return
    connection = require_database()
    deal = connection.execute("\n        SELECT id, seller_id, buyer_id FROM trade_deals\n        WHERE channel_id = ? AND status = 'active'\n        ", (interaction.channel.id,)).fetchone()
    if deal is None or interaction.user.id not in deal[1:3]:
        await interaction.response.send_message('This command must be used in your active trade.', ephemeral=True)
        return
    target_id = deal[2] if interaction.user.id == deal[1] else deal[1]
    try:
        connection.execute('\n            INSERT INTO trade_reviews (\n                deal_id, reviewer_id, target_id, stars, comment, created_at\n            ) VALUES (?, ?, ?, ?, ?, ?)\n            ', (deal[0], interaction.user.id, target_id, etoiles, commentaire[:500], int(time.time())))
        connection.commit()
    except sqlite3.IntegrityError:
        await interaction.response.send_message('You already gave your opinion on this trade.', ephemeral=True)
        return
    await interaction.response.send_message(f'Registered opinion for <@{target_id}> : **{etoiles}/5**.')
    review_count = connection.execute('SELECT COUNT(*) FROM trade_reviews WHERE deal_id = ?', (deal[0],)).fetchone()[0]
    if review_count >= 2:
        await close_trade_deal(interaction.channel, 'completed', interaction.user)

@bot.tree.command(name='trade-close', description='Close an unfinished trade.')
@app_commands.describe(raison="Why the trade hasn't been completed")
async def trade_close(interaction: discord.Interaction, raison: str='Trade cancelled') -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member) or (not isinstance(interaction.channel, discord.TextChannel)):
        return
    deal = require_database().execute("\n        SELECT seller_id, buyer_id FROM trade_deals\n        WHERE channel_id = ? AND status = 'active'\n        ", (interaction.channel.id,)).fetchone()
    if deal is None or (interaction.user.id not in deal and (not is_ticket_staff(interaction.user))):
        await interaction.response.send_message("You can't close this trade.", ephemeral=True)
        return
    await interaction.response.send_message(f'Trade not completed: {raison[:500]}')
    await close_trade_deal(interaction.channel, 'cancelled', interaction.user)

@bot.tree.command(name='trade-profile', description='Shows trade reputation.')
async def trade_profile(interaction: discord.Interaction, membre: discord.Member | None=None) -> None:
    if interaction.guild is None:
        return
    target = membre or interaction.user
    rows = require_database().execute('\n        SELECT stars FROM trade_reviews tr\n        JOIN trade_deals td ON td.id = tr.deal_id\n        WHERE td.guild_id = ? AND tr.target_id = ?\n        ', (interaction.guild.id, target.id)).fetchall()
    average = sum((row[0] for row in rows)) / len(rows) if rows else 0
    await interaction.response.send_message(embed=discord.Embed(title=f'Reputation of {target.display_name}', description=f'**{average:.1f}/5 ** on **{len(rows)} avis**.' if rows else 'No trade rated at the moment.', colour=discord.Colour.gold()))

class SanctionUndoView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label='Cancel sanction', emoji='↩️', style=discord.ButtonStyle.secondary, custom_id='community:moderation:undo')
    async def undo(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member) or (not is_ticket_staff(interaction.user)) or is_helper(interaction.user) or (interaction.message is None) or (not interaction.message.embeds):
            await interaction.response.send_message('This action is reserved for the top staff.', ephemeral=True)
            return
        footer = interaction.message.embeds[0].footer.text or ''
        match = re.search('#(\\d+)', footer)
        if match is None:
            await interaction.response.send_message('File number not found.', ephemeral=True)
            return
        case_id = int(match.group(1))
        connection = require_database()
        row = connection.execute('\n            SELECT user_id, action, cancelled_at FROM sanctions\n            WHERE id = ? AND guild_id = ?\n            ', (case_id, interaction.guild.id)).fetchone()
        if row is None or row[2] is not None:
            await interaction.response.send_message('This file cannot be found or already cancelled.', ephemeral=True)
            return
        target = interaction.guild.get_member(row[0])
        if target is None:
            await interaction.response.send_message('The member is no longer on the server.', ephemeral=True)
            return
        action = row[1]
        if action.startswith('Warning #'):
            warning_match = re.search('#(\\d+)', action)
            if warning_match is None:
                await interaction.response.send_message('Associated warning not found.', ephemeral=True)
                return
            connection.execute('\n                UPDATE warnings SET active = 0, removed_by = ?, removed_at = ?\n                WHERE id = ? AND guild_id = ? AND active = 1\n                ', (interaction.user.id, int(time.time()), int(warning_match.group(1)), interaction.guild.id))
        elif action.startswith('Timeout') or action.startswith('Automatic escalation'):
            try:
                await target.timeout(None, reason=f'Dossier #{case_id} cancelled by {interaction.user}')
            except discord.HTTPException:
                await interaction.response.send_message('Discord refused to withdraw the timeout.', ephemeral=True)
                return
        else:
            await interaction.response.send_message('This type of folder cannot be automatically cancelled.', ephemeral=True)
            return
        connection.execute('\n            UPDATE sanctions SET cancelled_by = ?, cancelled_at = ?\n            WHERE id = ?\n            ', (interaction.user.id, int(time.time()), case_id))
        connection.commit()
        embed = interaction.message.embeds[0]
        embed.colour = discord.Colour.green()
        embed.title = f'↩️ Dossier #{case_id} cancelled'
        embed.add_field(name='Cancellation', value=f'By {interaction.user.mention} • <t:{int(time.time())}:F>', inline=False)
        await interaction.response.edit_message(embed=embed, view=None)

@bot.tree.command(name='clear', description='Removes a specific number of recent messages.')
@app_commands.rename(nombre='count', membre='member')
@app_commands.describe(nombre='Number of messages to delete, between 1 and 500', membre='Delete only messages from this member')
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
async def clear_messages_command(interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 500], membre: discord.Member | None=None) -> None:
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel) or (not isinstance(interaction.user, discord.Member)) or (not is_ticket_staff(interaction.user)) or is_helper(interaction.user):
        await interaction.response.send_message('This order is reserved for the moderation staff.', ephemeral=True)
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
    scan_limit = min(2500, max(500, nombre * 5)) if membre is None else min(5000, max(500, nombre * 20))
    try:
        deleted = await interaction.channel.purge(limit=scan_limit, check=message_matches, bulk=True, reason=f'Clear of {nombre} message(s) by {interaction.user}' + (f' for {membre}' if membre is not None else ''))
    except discord.Forbidden:
        await interaction.followup.send('Discord refuses deletion. Checks ** permission Manage bot ** messages.', ephemeral=True)
        return
    except discord.HTTPException:
        logging.exception('Could not clear messages in channel %s', interaction.channel.id)
        await interaction.followup.send('Discord encountered an error during deletion.', ephemeral=True)
        return
    target_text = f' from {membre.mention}' if membre is not None else ''
    await interaction.followup.send(f'🧹 **{len(deleted)} message(s) **{target_text} deleted in {interaction.channel.mention}. The pinned messages have been kept.', ephemeral=True)
    log_channel = discord.utils.get(interaction.guild.text_channels, name=DISCORD_AUDIT_LOG_CHANNEL_NAME)
    if log_channel is not None:
        embed = discord.Embed(title='Messages deleted by command', colour=discord.Colour.orange(), timestamp=datetime.now(timezone.utc))
        embed.add_field(name='Performed by', value=f'{interaction.user.mention}\n`{interaction.user.id}`', inline=True)
        embed.add_field(name='Channel', value=interaction.channel.mention, inline=True)
        embed.add_field(name='Result', value=f'Requested: **{nombre}**\nDeleted: **{len(deleted)}**', inline=True)
        if membre is not None:
            embed.add_field(name='Targeted member', value=f'{membre.mention}\n`{membre.id}`', inline=False)
        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            logging.exception('Could not log command clear')

async def send_sanction_log(guild: discord.Guild, *, action: str, target: discord.abc.User, moderator: discord.abc.User | None, reason: str, colour: discord.Colour=discord.Colour.red()) -> int | None:
    case_id: int | None = None
    if database is not None:
        cursor = require_database().execute('\n            INSERT INTO sanctions (\n                guild_id, user_id, moderator_id, action, reason, created_at\n            ) VALUES (?, ?, ?, ?, ?, ?)\n            ', (guild.id, target.id, moderator.id if moderator is not None else None, action[:100], reason[:1000], int(time.time())))
        case_id = cursor.lastrowid
        require_database().commit()
    channel = discord.utils.get(guild.text_channels, name=SANCTION_LOG_CHANNEL_NAME)
    if channel is None:
        return case_id
    embed = discord.Embed(title=f'⚖️ Dossier #{case_id} • {action}', colour=colour, timestamp=datetime.now(timezone.utc))
    embed.add_field(name='Member', value=f'{target} (`{target.id}`)', inline=False)
    embed.add_field(name='Moderator', value=f'{moderator} (`{moderator.id}`)' if moderator is not None else 'Automod', inline=False)
    embed.add_field(name='Reason', value=reason[:1024], inline=False)
    embed.set_footer(text=f'Moderation folder #{case_id}')
    try:
        reversible = action.startswith('Warning #') or action.startswith('Timeout') or action.startswith('Automatic escalation')
        await channel.send(embed=embed, view=SanctionUndoView() if reversible else None)
    except discord.HTTPException:
        logging.exception('Cannot send penalty log')
    return case_id

@bot.tree.command(name='warn', description='Warn a member.')
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.rename(membre='member', raison='reason')
async def warn_command(interaction: discord.Interaction, membre: discord.Member, raison: str) -> None:
    if interaction.guild is None:
        return
    cursor = require_database().execute('\n        INSERT INTO warnings (\n            guild_id, user_id, moderator_id, reason, created_at\n        ) VALUES (?, ?, ?, ?, ?)\n        ', (interaction.guild.id, membre.id, interaction.user.id, raison[:1000], int(time.time())))
    require_database().commit()
    await interaction.response.send_message(f'⚠️ Warning **#{cursor.lastrowid}** added to {membre.mention}.', ephemeral=True)
    await send_sanction_log(interaction.guild, action=f'Warning #{cursor.lastrowid}', target=membre, moderator=interaction.user, reason=raison, colour=discord.Colour.orange())
    try:
        await membre.send(f'You received a warning on **{interaction.guild.name}**.\nReason: {raison}')
    except discord.HTTPException:
        pass
    active_warns = require_database().execute('\n        SELECT COUNT(*) FROM warnings\n        WHERE guild_id = ? AND user_id = ? AND active = 1\n        ', (interaction.guild.id, membre.id)).fetchone()[0]
    escalation_seconds = {3: 3600, 5: 86400, 7: 604800}.get(active_warns)
    if escalation_seconds is not None:
        until = datetime.now(timezone.utc) + timedelta(seconds=escalation_seconds)
        try:
            await membre.timeout(until, reason=f'Automatic climb after {active_warns} active warnings')
            await send_sanction_log(interaction.guild, action=f'Automatic escalation • timeout {format_remaining(escalation_seconds)}', target=membre, moderator=interaction.user, reason=f'Threshold of {active_warns} active warnings reached')
        except discord.HTTPException:
            logging.exception('Cannot apply automatic climbing to %s', membre.id)

@bot.tree.command(name='warns', description="Display a member's warnings.")
@app_commands.rename(membre='member')
async def warnings_command(interaction: discord.Interaction, membre: discord.Member) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    if not is_ticket_staff(interaction.user) and (not is_helper(interaction.user)):
        await interaction.response.send_message('This order is reserved for helpers and staff.', ephemeral=True)
        return
    rows = require_database().execute('\n        SELECT id, moderator_id, reason, created_at FROM warnings\n        WHERE guild_id = ? AND user_id = ? AND active = 1\n        ORDER BY created_at DESC LIMIT 20\n        ', (interaction.guild.id, membre.id)).fetchall()
    description = '\n\n'.join((f'**#{warning_id}** • <t:{created_at}:f> • by <@{moderator_id}>\n{reason}' for warning_id, moderator_id, reason, created_at in rows))[:4000]
    await interaction.response.send_message(embed=discord.Embed(title=f'⚠️ Warnings for {membre.display_name}', description=description or 'No active warnings.', colour=discord.Colour.orange()), ephemeral=True)

@bot.tree.command(name='warn-remove', description='Remove a warning by its ID.')
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.rename(identifiant='warning-id')
async def unwarn_command(interaction: discord.Interaction, identifiant: int) -> None:
    if interaction.guild is None:
        return
    row = require_database().execute('\n        SELECT user_id, reason FROM warnings\n        WHERE id = ? AND guild_id = ? AND active = 1\n        ', (identifiant, interaction.guild.id)).fetchone()
    if row is None:
        await interaction.response.send_message('Warning actif introuvable.', ephemeral=True)
        return
    require_database().execute('\n        UPDATE warnings SET active = 0, removed_by = ?, removed_at = ?\n        WHERE id = ?\n        ', (interaction.user.id, int(time.time()), identifiant))
    require_database().commit()
    target = interaction.guild.get_member(row[0]) or await bot.fetch_user(row[0])
    await interaction.response.send_message(f'✅ Warning **#{identifiant}** removed.', ephemeral=True)
    await send_sanction_log(interaction.guild, action=f"Retrait de l'avertissement #{identifiant}", target=target, moderator=interaction.user, reason=row[1], colour=discord.Colour.green())

@bot.tree.command(name='timeout', description='Place a member in timeout.')
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.rename(membre='member', duree='duration', raison='reason')
async def timeout_command(interaction: discord.Interaction, membre: discord.Member, duree: str, raison: str) -> None:
    seconds = parse_duration(duree)
    if interaction.guild is None or seconds is None or seconds > 2419200:
        await interaction.response.send_message('Duration not valid or longer than 28 days. Example: `30m`, `2h`, `7d`.', ephemeral=True)
        return
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    await membre.timeout(until, reason=raison)
    await interaction.response.send_message(f'🔇 {membre.mention} is in timeout until <t:{int(until.timestamp())}:F>.', ephemeral=True)
    await send_sanction_log(interaction.guild, action=f'Timeout for {format_remaining(seconds)}', target=membre, moderator=interaction.user, reason=raison)

@bot.tree.command(name='timeout-remove', description='Remove the timeout from a member.')
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.rename(membre='member', raison='reason')
async def untimeout_command(interaction: discord.Interaction, membre: discord.Member, raison: str='Early termination') -> None:
    if interaction.guild is None:
        return
    await membre.timeout(None, reason=raison)
    await interaction.response.send_message(f'Timeout removed for {membre.mention}.', ephemeral=True)
    await send_sanction_log(interaction.guild, action='Timeout ended', target=membre, moderator=interaction.user, reason=raison, colour=discord.Colour.green())

@bot.tree.command(name='sanctions', description="Shows the full history of a member's sanctions.")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.rename(membre='member')
async def sanctions_command(interaction: discord.Interaction, membre: discord.Member) -> None:
    if interaction.guild is None:
        return
    rows = require_database().execute('\n        SELECT action, moderator_id, reason, created_at FROM sanctions\n        WHERE guild_id = ? AND user_id = ?\n        ORDER BY created_at DESC LIMIT 25\n        ', (interaction.guild.id, membre.id)).fetchall()
    description = '\n\n'.join((f"**{action}** • <t:{created_at}:f>\nBy {(f'<@{moderator_id}>' if moderator_id else 'Automod')} — {reason}" for action, moderator_id, reason, created_at in rows))[:4000]
    await interaction.response.send_message(embed=discord.Embed(title=f'⚖️ History for {membre.display_name}', description=description or 'No penalties recorded.', colour=discord.Colour.red()), ephemeral=True)

@bot.tree.command(name='member-info', description='Display useful information about a member.')
@app_commands.rename(membre='member')
async def player_info_command(interaction: discord.Interaction, membre: discord.Member) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    if not is_ticket_staff(interaction.user) and (not is_helper(interaction.user)):
        await interaction.response.send_message('This order is reserved for helpers and staff.', ephemeral=True)
        return
    message_xp, voice_xp, bonus_xp, voice_seconds, total_messages = get_member_stats(interaction.guild.id, membre.id)
    total_xp = message_xp + voice_xp + bonus_xp
    warning_count = require_database().execute('\n        SELECT COUNT(*) FROM warnings\n        WHERE guild_id = ? AND user_id = ? AND active = 1\n        ', (interaction.guild.id, membre.id)).fetchone()[0]
    sanction_count = require_database().execute('\n        SELECT COUNT(*) FROM sanctions\n        WHERE guild_id = ? AND user_id = ?\n        ', (interaction.guild.id, membre.id)).fetchone()[0]
    created_timestamp = int(membre.created_at.timestamp())
    joined_timestamp = int(membre.joined_at.timestamp()) if membre.joined_at is not None else None
    roles = [role.mention for role in reversed(membre.roles[1:]) if not role.is_default()]
    embed = discord.Embed(title=f'🔎 Information • {membre.display_name}', colour=membre.colour if membre.colour.value else discord.Colour.blue(), timestamp=datetime.now(timezone.utc))
    embed.set_thumbnail(url=membre.display_avatar.url)
    embed.add_field(name='Identity', value=f"Account: {membre.mention}\nID: `{membre.id}`\nBot : **{('Yes' if membre.bot else 'No')}**", inline=False)
    embed.add_field(name='Dates', value=f'Account created: <t:{created_timestamp}:F> • <t:{created_timestamp}:R>\n' + (f'Server joins: <t:{joined_timestamp}:F> • <t:{joined_timestamp}:R>' if joined_timestamp is not None else 'Arrival date unavailable'), inline=False)
    embed.add_field(name='Activity', value=f'Level: **{calculate_level(total_xp)}** • XP: **{total_xp:,}**\nMessages recorded: **{total_messages:,}**\nVoice time: **{format_duration(voice_seconds)}**\nInvites: **{get_invite_count(interaction.guild.id, membre.id)}**', inline=False)
    embed.add_field(name='Moderation', value=f"Active warnings: **{warning_count}**\nRegistered sanctions: **{sanction_count}**\nCurrent timeout: **{('Yes' if membre.is_timed_out() else 'No')}**", inline=False)
    embed.add_field(name=f'Roles ({len(roles)})', value=' '.join(roles)[:1024] if roles else 'No role', inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

def can_manage_helpers(member: discord.Member) -> bool:
    return is_ticket_staff(member)

@bot.tree.command(name='helper-add', description='Add the Helper role to a member.')
@app_commands.rename(membre='member')
async def helper_add_command(interaction: discord.Interaction, membre: discord.Member) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    if not can_manage_helpers(interaction.user):
        await interaction.response.send_message('This order is reserved for the top staff.', ephemeral=True)
        return
    if membre.bot:
        await interaction.response.send_message('A bot cannot become a Helper.', ephemeral=True)
        return
    role = await ensure_helper_role(interaction.guild)
    if role is None:
        await interaction.response.send_message('The Helper role could not be created.', ephemeral=True)
        return
    await membre.add_roles(role, reason=f'Helper added by {interaction.user}')
    require_database().execute('\n        INSERT INTO helper_stats (guild_id, user_id, resolved_tickets, points)\n        VALUES (?, ?, 0, 0)\n        ON CONFLICT(guild_id, user_id) DO NOTHING\n        ', (interaction.guild.id, membre.id))
    require_database().commit()
    await reconcile_helper_ticket_permissions(interaction.guild, role)
    await update_helper_leaderboard(interaction.guild)
    await interaction.response.send_message(f'✅ {membre.mention} is now ** Helper **.', ephemeral=True)

@bot.tree.command(name='helper-remove', description='Remove the Helper role from a member.')
@app_commands.rename(membre='member')
async def helper_remove_command(interaction: discord.Interaction, membre: discord.Member) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    if not can_manage_helpers(interaction.user):
        await interaction.response.send_message('This order is reserved for the top staff.', ephemeral=True)
        return
    role = discord.utils.get(interaction.guild.roles, name=HELPER_ROLE_NAME)
    if role is None or role not in membre.roles:
        await interaction.response.send_message('This member does not have the Helper role.', ephemeral=True)
        return
    await membre.remove_roles(role, reason=f'Helper removed by {interaction.user}')
    require_database().execute("\n        UPDATE tickets SET claimed_by = NULL\n        WHERE guild_id = ? AND claimed_by = ? AND status = 'open'\n        ", (interaction.guild.id, membre.id))
    require_database().commit()
    await reconcile_helper_ticket_permissions(interaction.guild, role)
    await update_helper_leaderboard(interaction.guild)
    await interaction.response.send_message(f'The Helper role has been withdrawn from {membre.mention}. His tickets were made available.', ephemeral=True)

@bot.tree.command(name='helper-points-set', description='Defines exactly the points of a Helper.')
@app_commands.rename(membre='member')
async def helper_points_set_command(interaction: discord.Interaction, membre: discord.Member, points: int) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    if not can_manage_helpers(interaction.user):
        await interaction.response.send_message('This order is reserved for the top staff.', ephemeral=True)
        return
    if points < 0:
        await interaction.response.send_message('The number of points cannot be negative.', ephemeral=True)
        return
    role = await ensure_helper_role(interaction.guild)
    if role is None or role not in membre.roles:
        await interaction.response.send_message('This member must first receive the Helper role.', ephemeral=True)
        return
    require_database().execute('\n        INSERT INTO helper_stats (guild_id, user_id, resolved_tickets, points)\n        VALUES (?, ?, 0, ?)\n        ON CONFLICT(guild_id, user_id) DO UPDATE SET points = excluded.points\n        ', (interaction.guild.id, membre.id, points))
    require_database().commit()
    await update_helper_leaderboard(interaction.guild)
    await interaction.response.send_message(f'🏆 {membre.mention} now has exactly **{points} point(s) Helper**.', ephemeral=True)

@bot.tree.command(name='helper-leaderboard', description='Update the Helpers ranking.')
async def helper_leaderboard_command(interaction: discord.Interaction) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return
    if not can_manage_helpers(interaction.user):
        await interaction.response.send_message('This order is reserved for the top staff.', ephemeral=True)
        return
    await update_helper_leaderboard(interaction.guild)
    await interaction.response.send_message('', ephemeral=True)

@bot.tree.command(name='note-add', description="Add an internal note to a member's folder.")
@app_commands.rename(membre='member')
async def moderation_note_add(interaction: discord.Interaction, membre: discord.Member, note: str) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member) or (not is_ticket_staff(interaction.user)) or is_helper(interaction.user):
        await interaction.response.send_message('This order is reserved for the top staff.', ephemeral=True)
        return
    cursor = require_database().execute('\n        INSERT INTO moderation_notes (\n            guild_id, user_id, moderator_id, note, created_at\n        ) VALUES (?, ?, ?, ?, ?)\n        ', (interaction.guild.id, membre.id, interaction.user.id, note[:1500], int(time.time())))
    require_database().commit()
    await interaction.response.send_message(f'📝 Internal note **#{cursor.lastrowid}** added to the record of {membre.mention}.', ephemeral=True)

@bot.tree.command(name='member-notes', description="Consult a member's internal notes.")
@app_commands.rename(membre='member')
async def moderation_notes_show(interaction: discord.Interaction, membre: discord.Member) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member) or (not is_ticket_staff(interaction.user)) or is_helper(interaction.user):
        await interaction.response.send_message('This order is reserved for the top staff.', ephemeral=True)
        return
    rows = require_database().execute('\n        SELECT id, moderator_id, note, created_at FROM moderation_notes\n        WHERE guild_id = ? AND user_id = ? AND active = 1\n        ORDER BY created_at DESC LIMIT 25\n        ', (interaction.guild.id, membre.id)).fetchall()
    description = '\n\n'.join((f'**Note #{note_id}** • <t:{created_at}:f> • <@{moderator_id}>\n{note}' for note_id, moderator_id, note, created_at in rows))[:4000]
    await interaction.response.send_message(embed=discord.Embed(title=f'📝 Internal notes • {membre.display_name}', description=description or 'No active internal notes.', colour=discord.Colour.dark_grey()), ephemeral=True)

@bot.tree.command(name='note-remove', description='Archive an internal note by its number.')
@app_commands.rename(identifiant='note-id')
async def moderation_note_remove(interaction: discord.Interaction, identifiant: int) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member) or (not is_ticket_staff(interaction.user)) or is_helper(interaction.user):
        await interaction.response.send_message('This order is reserved for the top staff.', ephemeral=True)
        return
    cursor = require_database().execute('\n        UPDATE moderation_notes\n        SET active = 0, removed_by = ?, removed_at = ?\n        WHERE id = ? AND guild_id = ? AND active = 1\n        ', (interaction.user.id, int(time.time()), identifiant, interaction.guild.id))
    require_database().commit()
    await interaction.response.send_message(f'✅ Note **#{identifiant}Archived **.' if cursor.rowcount else 'Note active introuvable.', ephemeral=True)

@bot.tree.command(name='staff-statistics', description='Displays monthly staff statistics.')
@app_commands.rename(membre='member')
async def staff_statistics(interaction: discord.Interaction, membre: discord.Member | None=None) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member) or (not is_ticket_staff(interaction.user)) or is_helper(interaction.user):
        await interaction.response.send_message('This order is reserved for the top staff.', ephemeral=True)
        return
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    since = int(start.timestamp())
    connection = require_database()
    if membre is not None:
        sanctions = connection.execute('\n            SELECT COUNT(*) FROM sanctions\n            WHERE guild_id = ? AND moderator_id = ? AND created_at >= ?\n            ', (interaction.guild.id, membre.id, since)).fetchone()[0]
        claimed = connection.execute('\n            SELECT COUNT(*) FROM tickets\n            WHERE guild_id = ? AND claimed_by = ? AND claimed_at >= ?\n            ', (interaction.guild.id, membre.id, since)).fetchone()[0]
        closed = connection.execute('\n            SELECT COUNT(*) FROM tickets\n            WHERE guild_id = ? AND closed_by = ? AND closed_at >= ?\n            ', (interaction.guild.id, membre.id, since)).fetchone()[0]
        average_response = connection.execute('\n            SELECT AVG(claimed_at - created_at) FROM tickets\n            WHERE guild_id = ? AND claimed_by = ? AND claimed_at >= ?\n                  AND claimed_at IS NOT NULL\n            ', (interaction.guild.id, membre.id, since)).fetchone()[0]
        notes = connection.execute('\n            SELECT COUNT(*) FROM moderation_notes\n            WHERE guild_id = ? AND moderator_id = ? AND created_at >= ?\n            ', (interaction.guild.id, membre.id, since)).fetchone()[0]
        description = f'Registered sanctions: **{sanctions}**\nTickets claim : **{claimed}**\nTickets closed: **{closed}**\nAverage response time: **{format_duration(int(average_response or 0))}**\nNotes internes : **{notes}**'
        title = f'📊 Statistics • {membre.display_name}'
    else:
        rows = connection.execute('\n            SELECT moderator_id, COUNT(*) AS actions FROM sanctions\n            WHERE guild_id = ? AND moderator_id IS NOT NULL AND created_at >= ?\n            GROUP BY moderator_id ORDER BY actions DESC LIMIT 15\n            ', (interaction.guild.id, since)).fetchall()
        ticket_rows = dict(connection.execute('\n                SELECT closed_by, COUNT(*) FROM tickets\n                WHERE guild_id = ? AND closed_by IS NOT NULL AND closed_at >= ?\n                GROUP BY closed_by\n                ', (interaction.guild.id, since)).fetchall())
        totals: dict[int, int] = {moderator_id: actions for moderator_id, actions in rows}
        for user_id, tickets in ticket_rows.items():
            totals[user_id] = totals.get(user_id, 0) + tickets
        ranking = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        description = '\n'.join((f'`#{position}` <@{user_id}> • **{score} action(s)**' for position, (user_id, score) in enumerate(ranking[:15], start=1))) or 'No action recorded this month.'
        title = 'Monthly staff classification'
    embed = discord.Embed(title=title, description=description, colour=discord.Colour.blue(), timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=f"Since {start.strftime('%d/%m/%Y')} • internal data")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='admin-commands', description='Publish the list of administration orders.')
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def admin_commands_command(interaction: discord.Interaction) -> None:
    embed = discord.Embed(title='', description='All sensitive commands use dashes and are protected by Discord permissions and bot checks.', colour=discord.Colour.red())
    embed.add_field(name='Moderation', value='`/warn` • add a warning\n`/warns` • view the warns — accessible to helpers\n`/warn-remove` • Remove Warning\n`/clear` • remove a specific number of messages\n`/timeout` • Place a member in timeout\n`/timeout-remove` • Remove Timeout\n`/sanctions` • complete history\n`/note-add`, `/member-notes`, `/note-remove`\n`/staff-statistics` • monthly staff activity\n`/member-info` • information — accessible to helpers', inline=False)
    embed.add_field(name='🎉 Giveaways', value='`/giveaway-create`\n`/giveaway-end`\n`/giveaway-reroll`\n`/giveaway-cancel`', inline=False)
    embed.add_field(name='Helpers Management', value='`/helper-add`\n`/helper-remove`\n`/helper-points-set`', inline=False)
    embed.add_field(name='Events', value='`/event-create`\n`/event-cancel`\n`/event-end`\n`/event-results`', inline=False)
    embed.add_field(name='Community, levels and invitations', value='`/suggestion-status` • Official decision\n`/level-give`\n`/level-reset`\n`/invites-set`', inline=False)
    embed.add_field(name='🎫 Gestion by boutons', value='Claims, closure and transmission of tickets; persistent control of events, suggestions and giveaways.', inline=False)
    embed.set_footer(text='The Helper role has no other moderation control')
    await interaction.response.send_message(embed=embed)

async def refresh_suggestion_message(guild: discord.Guild, suggestion_id: int) -> None:
    connection = require_database()
    row = connection.execute('\n        SELECT channel_id, message_id, title, description, user_id, status,\n               staff_id, staff_response, created_at\n        FROM suggestions WHERE id = ? AND guild_id = ?\n        ', (suggestion_id, guild.id)).fetchone()
    if row is None or row[1] is None:
        return
    channel = guild.get_channel(row[0])
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(row[1])
    except discord.HTTPException:
        return
    votes = connection.execute('\n        SELECT\n            COALESCE(SUM(CASE WHEN vote = 1 THEN 1 ELSE 0 END), 0),\n            COALESCE(SUM(CASE WHEN vote = -1 THEN 1 ELSE 0 END), 0)\n        FROM suggestion_votes WHERE suggestion_id = ?\n        ', (suggestion_id,)).fetchone()
    status_labels = {'pending': '🟡 Pending', 'accepted': 'Accepted', 'rejected': 'Denied', 'done': 'Implemented'}
    colours = {'pending': discord.Colour.gold(), 'accepted': discord.Colour.green(), 'rejected': discord.Colour.red(), 'done': discord.Colour.blurple()}
    embed = discord.Embed(title=f'💡 Suggestion #{suggestion_id} • {row[2]}', description=row[3], colour=colours.get(row[5], discord.Colour.gold()), timestamp=datetime.fromtimestamp(row[8], timezone.utc))
    embed.add_field(name='Proposed by', value=f'<@{row[4]}>', inline=True)
    embed.add_field(name='Votes', value=f'👍 **{votes[0]}** • 👎 **{votes[1]}**', inline=True)
    embed.add_field(name='Status', value=status_labels.get(row[5], row[5]), inline=True)
    if row[7]:
        embed.add_field(name='Official response', value=f'{row[7]}\n\n— <@{row[6]}>', inline=False)
    embed.set_footer(text='Amendmentable vote • one vote per member')
    await message.edit(embed=embed, view=SuggestionVoteView() if row[5] == 'pending' else None)

class SuggestionVoteView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def record_vote(self, interaction: discord.Interaction, vote: int) -> None:
        if interaction.guild is None or interaction.message is None or interaction.user.bot:
            return
        connection = require_database()
        suggestion = connection.execute('\n            SELECT id, user_id, status FROM suggestions\n            WHERE guild_id = ? AND message_id = ?\n            ', (interaction.guild.id, interaction.message.id)).fetchone()
        if suggestion is None or suggestion[2] != 'pending':
            await interaction.response.send_message('The votes are closed for this suggestion.', ephemeral=True)
            return
        if suggestion[1] == interaction.user.id:
            await interaction.response.send_message("You can't vote for your own suggestion.", ephemeral=True)
            return
        previous = connection.execute('\n            SELECT vote FROM suggestion_votes\n            WHERE suggestion_id = ? AND user_id = ?\n            ', (suggestion[0], interaction.user.id)).fetchone()
        if previous is not None and previous[0] == vote:
            connection.execute('\n                DELETE FROM suggestion_votes\n                WHERE suggestion_id = ? AND user_id = ?\n                ', (suggestion[0], interaction.user.id))
            result = 'Your vote has been withdrawn.'
        else:
            connection.execute('\n                INSERT INTO suggestion_votes (\n                    suggestion_id, user_id, vote, voted_at\n                ) VALUES (?, ?, ?, ?)\n                ON CONFLICT(suggestion_id, user_id) DO UPDATE SET\n                    vote = excluded.vote, voted_at = excluded.voted_at\n                ', (suggestion[0], interaction.user.id, vote, int(time.time())))
            result = 'Your vote has been recorded.'
        connection.commit()
        await interaction.response.send_message(result, ephemeral=True)
        await refresh_suggestion_message(interaction.guild, suggestion[0])

    @discord.ui.button(label='For', emoji='👍', style=discord.ButtonStyle.success, custom_id='community:suggestion:up')
    async def vote_up(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.record_vote(interaction, 1)

    @discord.ui.button(label='Contre', emoji='👎', style=discord.ButtonStyle.danger, custom_id='community:suggestion:down')
    async def vote_down(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.record_vote(interaction, -1)

class SuggestionModal(discord.ui.Modal):

    def __init__(self) -> None:
        super().__init__(title='💡 Nouvelle suggestion', timeout=600)
        self.suggestion_title = discord.ui.TextInput(label='Titre', min_length=5, max_length=100, placeholder='Clearly sums up your idea')
        self.details = discord.ui.TextInput(label='Description', min_length=20, max_length=1500, style=discord.TextStyle.paragraph, placeholder='Explains the idea, its interest and how it works')
        self.add_item(self.suggestion_title)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            return
        connection = require_database()
        now = int(time.time())
        cursor = connection.execute('\n            INSERT INTO suggestions (\n                guild_id, user_id, channel_id, title, description,\n                created_at, updated_at\n            ) VALUES (?, ?, ?, ?, ?, ?, ?)\n            ', (interaction.guild.id, interaction.user.id, interaction.channel.id, str(self.suggestion_title), str(self.details), now, now))
        suggestion_id = cursor.lastrowid
        connection.commit()
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title=f'💡 Suggestion #{suggestion_id} • {self.suggestion_title}', description=str(self.details), colour=discord.Colour.gold(), timestamp=datetime.now(timezone.utc))
        embed.add_field(name='Proposed by', value=interaction.user.mention, inline=True)
        embed.add_field(name='Votes', value='👍 **0** • 👎 **0**', inline=True)
        embed.add_field(name='Status', value='🟡 Pending', inline=True)
        embed.set_footer(text='Amendmentable vote • one vote per member')
        message = await interaction.channel.send(embed=embed, view=SuggestionVoteView())
        connection.execute('UPDATE suggestions SET message_id = ? WHERE id = ?', (message.id, suggestion_id))
        connection.commit()
        await interaction.followup.send(f'Suggestion published: {message.jump_url}', ephemeral=True)

@bot.tree.command(name='suggestion', description='Open the form to suggest an idea.')
async def suggestion_create_command(interaction: discord.Interaction) -> None:
    if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name != SUGGESTIONS_CHANNEL_NAME:
        await interaction.response.send_message(f'Use this command in `{SUGGESTIONS_CHANNEL_NAME}`.', ephemeral=True)
        return
    await interaction.response.send_modal(SuggestionModal())

@bot.tree.command(name='suggestion-status', description='Make a formal decision on a suggestion.')
@app_commands.rename(identifiant='suggestion-id', statut='status', reponse='response')
@app_commands.choices(statut=[app_commands.Choice(name='Accepted', value='accepted'), app_commands.Choice(name='Denied', value='rejected'), app_commands.Choice(name='Implemented', value='done'), app_commands.Choice(name='Set back to pending', value='pending')])
async def suggestion_status_command(interaction: discord.Interaction, identifiant: int, statut: app_commands.Choice[str], reponse: str) -> None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member) or (not is_ticket_staff(interaction.user)) or is_helper(interaction.user):
        await interaction.response.send_message('This order is reserved for the top staff.', ephemeral=True)
        return
    cursor = require_database().execute('\n        UPDATE suggestions\n        SET status = ?, staff_id = ?, staff_response = ?, updated_at = ?\n        WHERE id = ? AND guild_id = ?\n        ', (statut.value, interaction.user.id, reponse[:1000], int(time.time()), identifiant, interaction.guild.id))
    require_database().commit()
    if not cursor.rowcount:
        await interaction.response.send_message('Suggestion not found.', ephemeral=True)
        return
    await interaction.response.send_message(f'✅ Suggestion **#{identifiant}** updated.', ephemeral=True)
    await refresh_suggestion_message(interaction.guild, identifiant)

class CommunityEventView(discord.ui.View):

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label='Register', emoji='✅', style=discord.ButtonStyle.success, custom_id='community:event:join')
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.message is None or interaction.guild is None or (not isinstance(interaction.user, discord.Member)):
            return
        connection = require_database()
        event = connection.execute('\n            SELECT starts_at, capacity, status FROM community_events\n            WHERE message_id = ?\n            ', (interaction.message.id,)).fetchone()
        if event is None or event[2] != 'scheduled' or event[0] <= int(time.time()):
            await interaction.response.send_message('Registration for this event is closed.', ephemeral=True)
            return
        existing = connection.execute('\n            SELECT 1 FROM community_event_entries\n            WHERE message_id = ? AND user_id = ?\n            ', (interaction.message.id, interaction.user.id)).fetchone()
        if existing:
            connection.execute('\n                DELETE FROM community_event_entries\n                WHERE message_id = ? AND user_id = ?\n                ', (interaction.message.id, interaction.user.id))
            connection.commit()
            await interaction.response.send_message('Your registration has been withdrawn.', ephemeral=True)
            return
        count = connection.execute('\n            SELECT COUNT(*) FROM community_event_entries\n            WHERE message_id = ?\n            ', (interaction.message.id,)).fetchone()[0]
        connection.execute('\n            INSERT INTO community_event_entries (message_id, user_id, joined_at)\n            VALUES (?, ?, ?)\n            ', (interaction.message.id, interaction.user.id, int(time.time())))
        connection.commit()
        position = count + 1
        if position <= event[1]:
            message = f'Confirmed registration, place ** #{position}**.'
        else:
            message = f"The event is complete. You're ** #{position - event[1]}** on the waiting list."
        await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label='Participants', emoji='👥', style=discord.ButtonStyle.secondary, custom_id='community:event:participants')
    async def participants(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.message is None or interaction.guild is None:
            return
        event = require_database().execute('SELECT capacity FROM community_events WHERE message_id = ?', (interaction.message.id,)).fetchone()
        if event is None:
            return
        rows = require_database().execute('\n            SELECT user_id FROM community_event_entries\n            WHERE message_id = ? ORDER BY joined_at LIMIT 50\n            ', (interaction.message.id,)).fetchall()
        confirmed = [f'<@{user_id}>' for user_id, in rows[:event[0]]]
        waiting = [f'<@{user_id}>' for user_id, in rows[event[0]:]]
        await interaction.response.send_message(f"**Participants ({len(confirmed)}/{event[0]})**\n{', '.join(confirmed) or 'None'}\n\n**Waiting list ({len(waiting)})**\n{', '.join(waiting) or 'None'}", ephemeral=True)

@bot.tree.command(name='event-create', description='Creates an event with registrations.')
@app_commands.default_permissions(manage_events=True)
@app_commands.checks.has_permissions(manage_events=True)
@app_commands.rename(nom='name', debut='start', places='slots')
@app_commands.describe(nom='Event name', debut='Paris date and time: DD/MM/YYYY HH:MM', places='Number of available slots', description='Description and requirements')
async def event_create(interaction: discord.Interaction, nom: str, debut: str, places: app_commands.Range[int, 2, 500], description: str) -> None:
    if interaction.guild is None:
        return
    try:
        starts_at = datetime.strptime(debut, '%d/%m/%Y %H:%M').replace(tzinfo=PARIS_TIMEZONE)
    except ValueError:
        await interaction.response.send_message('Invalid format. Use `DD/MM/YYYY HH:MM`, for example `15/08/2026 20:30`.', ephemeral=True)
        return
    if starts_at <= datetime.now(PARIS_TIMEZONE) + timedelta(minutes=5):
        await interaction.response.send_message('The event must begin in more than five minutes.', ephemeral=True)
        return
    channel = discord.utils.get(interaction.guild.text_channels, name=EVENT_ANNOUNCEMENT_CHANNEL_NAME)
    if channel is None:
        await interaction.response.send_message('The event announcement show is not available. Contact an administrator.', ephemeral=True)
        return
    timestamp = int(starts_at.timestamp())
    embed = discord.Embed(title=f'🎪 {nom[:180]}', description=description[:3000], colour=discord.Colour.purple())
    embed.add_field(name='Start', value=f'<t:{timestamp}:F> • <t:{timestamp}:R>', inline=False)
    embed.add_field(name='👥 Slots', value=str(places), inline=True)
    embed.add_field(name='Organized by', value=interaction.user.mention, inline=True)
    embed.set_footer(text='Register with the button • Automatic waiting list')
    await interaction.response.defer(ephemeral=True)
    message = await channel.send(embed=embed, view=CommunityEventView())
    require_database().execute('\n        INSERT INTO community_events (\n            message_id, guild_id, channel_id, host_id, name,\n            description, starts_at, capacity, created_at\n        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)\n        ', (message.id, interaction.guild.id, channel.id, interaction.user.id, nom[:180], description[:3000], timestamp, places, int(time.time())))
    require_database().commit()
    await interaction.followup.send(f'Event created: {message.jump_url}', ephemeral=True)

@bot.tree.command(name='event-cancel', description='Cancel an event.')
@app_commands.default_permissions(manage_events=True)
@app_commands.checks.has_permissions(manage_events=True)
@app_commands.rename(raison='reason')
async def event_cancel(interaction: discord.Interaction, message_id: str, raison: str) -> None:
    if interaction.guild is None or not message_id.isdigit():
        await interaction.response.send_message('Invalid message identifier.', ephemeral=True)
        return
    row = require_database().execute("\n        SELECT channel_id, name FROM community_events\n        WHERE message_id = ? AND guild_id = ? AND status = 'scheduled'\n        ", (int(message_id), interaction.guild.id)).fetchone()
    if row is None:
        await interaction.response.send_message('Active event not found.', ephemeral=True)
        return
    require_database().execute("UPDATE community_events SET status = 'cancelled' WHERE message_id = ?", (int(message_id),))
    require_database().commit()
    channel = interaction.guild.get_channel(row[0])
    if isinstance(channel, discord.TextChannel):
        await channel.send(f'The event **{row[1]}** has been cancelled.\nReason: {raison[:1000]}')
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(view=None)
        except discord.HTTPException:
            pass
    await interaction.response.send_message('Event cancelled.', ephemeral=True)

@bot.tree.command(name='event-end', description='End an active event.')
@app_commands.default_permissions(manage_events=True)
@app_commands.checks.has_permissions(manage_events=True)
async def event_finish(interaction: discord.Interaction, message_id: str) -> None:
    if interaction.guild is None or not message_id.isdigit():
        await interaction.response.send_message('Invalid message identifier.', ephemeral=True)
        return
    row = require_database().execute("\n        SELECT channel_id, name FROM community_events\n        WHERE message_id = ? AND guild_id = ?\n          AND status IN ('scheduled', 'started')\n        ", (int(message_id), interaction.guild.id)).fetchone()
    if row is None:
        await interaction.response.send_message('Event not found or already closed.', ephemeral=True)
        return
    require_database().execute("UPDATE community_events SET status = 'finished' WHERE message_id = ?", (int(message_id),))
    require_database().commit()
    channel = interaction.guild.get_channel(row[0])
    if isinstance(channel, discord.TextChannel):
        await channel.send(f'The event **{row[1]}** is now over.')
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(view=None)
        except discord.HTTPException:
            pass
    await interaction.response.send_message('Closed event.', ephemeral=True)

@bot.tree.command(name='event-results', description='Publish the podium and assign the roles of the event.')
@app_commands.default_permissions(manage_events=True)
@app_commands.checks.has_permissions(manage_events=True)
@app_commands.rename(premier='first', deuxieme='second', troisieme='third')
async def event_results(interaction: discord.Interaction, message_id: str, premier: discord.Member, deuxieme: discord.Member | None=None, troisieme: discord.Member | None=None) -> None:
    if interaction.guild is None or not message_id.isdigit():
        await interaction.response.send_message('Invalid message identifier.', ephemeral=True)
        return
    row = require_database().execute("\n        SELECT channel_id, name FROM community_events\n        WHERE message_id = ? AND guild_id = ? AND status != 'cancelled'\n        ", (int(message_id), interaction.guild.id)).fetchone()
    if row is None:
        await interaction.response.send_message('Event not found.', ephemeral=True)
        return
    podium = [(premier, '🥇・Event Champion', '🥇'), (deuxieme, '🥈・Event Finalist', '🥈'), (troisieme, '🥉・Event Third Place', '🥉')]
    if len({member.id for member, _, _ in podium if member is not None}) != len([member for member, _, _ in podium if member is not None]):
        await interaction.response.send_message('A member cannot occupy more than one seat.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    result_lines = []
    for member, role_name, medal in podium:
        if member is None:
            continue
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if role is not None:
            try:
                await member.add_roles(role, reason=f'Event Podium {row[1]}')
            except discord.HTTPException:
                logging.exception('Could not assign %s', role_name)
        result_lines.append(f'{medal} {member.mention}')
    require_database().execute("UPDATE community_events SET status = 'finished' WHERE message_id = ?", (int(message_id),))
    require_database().commit()
    channel = interaction.guild.get_channel(row[0])
    if isinstance(channel, discord.TextChannel):
        await channel.send(embed=discord.Embed(title=f'Results • {row[1]}', description='\n'.join(result_lines), colour=discord.Colour.gold()))
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(view=None)
        except discord.HTTPException:
            pass
    await interaction.followup.send('Published podium and assigned roles.', ephemeral=True)

@bot.tree.command(name='level', description='Show your level or that of a member.')
@app_commands.guild_only()
@app_commands.rename(membre='member')
@app_commands.describe(membre='Member whose progress you want to view')
async def level_command(interaction: discord.Interaction, membre: discord.Member | None=None) -> None:
    if interaction.guild is None:
        return
    target = membre or interaction.user
    if not isinstance(target, discord.Member):
        return
    message_xp, voice_xp, bonus_xp, voice_seconds, total_messages = get_member_stats(interaction.guild.id, target.id)
    total_xp = message_xp + voice_xp + bonus_xp
    level = calculate_level(total_xp)
    current_threshold = level * level * 100
    next_threshold = (level + 1) * (level + 1) * 100
    progress = total_xp - current_threshold
    required = next_threshold - current_threshold
    position_row = require_database().execute('\n        SELECT COUNT(*) + 1\n        FROM member_stats\n        WHERE guild_id = ? AND message_xp + voice_xp + bonus_xp > ?\n        ', (interaction.guild.id, total_xp)).fetchone()
    leaderboard_position = int(position_row[0]) if position_row else 1
    await interaction.response.defer(thinking=True)
    try:
        card = await asyncio.to_thread(generate_level_card, username=target.display_name, level=level, total_xp=total_xp, progress=progress, required=required, total_messages=total_messages, voice_seconds=voice_seconds, leaderboard_position=leaderboard_position)
    except Exception:
        logging.exception('Unable to generate level map')
        await interaction.followup.send('The level card could not be generated.', ephemeral=True)
        return
    await interaction.followup.send(file=discord.File(card, filename=f'level-{target.id}.png'))

@bot.tree.command(name='leaderboard', description='Show the most active server members.')
@app_commands.guild_only()
async def leaderboard_command(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    rows = require_database().execute('\n        SELECT user_id, message_xp + voice_xp + bonus_xp AS total_xp,\n               voice_seconds, total_messages\n        FROM member_stats\n        WHERE guild_id = ?\n        ORDER BY total_xp DESC\n        LIMIT 10\n        ', (interaction.guild.id,)).fetchall()
    if not rows:
        await interaction.response.send_message('The ranking is still empty.', ephemeral=True)
        return
    lines = []
    medals = ('🥇', '🥈', '🥉')
    for position, (user_id, total_xp, voice_seconds, total_messages) in enumerate(rows, start=1):
        member = interaction.guild.get_member(user_id)
        name = member.display_name if member is not None else f'Member {user_id}'
        marker = medals[position - 1] if position <= 3 else f'`#{position}`'
        lines.append(f'{marker} **{name}** — level {calculate_level(total_xp)} • {total_xp:,} XP • {format_duration(voice_seconds)}')
    embed = discord.Embed(title='Community ranking', description='\n'.join(lines), colour=discord.Colour.gold())
    embed.set_footer(text='XP won with messages and voice activity')
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='invites', description='Shows the number of invitations from a member.')
@app_commands.guild_only()
@app_commands.rename(membre='member')
@app_commands.describe(membre='Member whose invites you want to view')
async def invites_command(interaction: discord.Interaction, membre: discord.Member | None=None) -> None:
    if interaction.guild is None:
        return
    target = membre or interaction.user
    if not isinstance(target, discord.Member):
        return
    count = get_invite_count(interaction.guild.id, target.id)
    current_tier = next(((required, role_name, bonus) for required, role_name, bonus in INVITE_ROLE_TIERS if count >= required), None)
    next_tier = next(((required, role_name, bonus) for required, role_name, bonus in reversed(INVITE_ROLE_TIERS) if count < required), None)
    description = f'{target.mention} has **{count} invitation(s) **.'
    if current_tier is not None:
        description += f'\nCurrent role: **{current_tier[1]}** • bonus giveaway **+{current_tier[2]:g} chance**'
    if next_tier is not None:
        description += f'\nProchain palier : **{next_tier[1]}** to **{next_tier[0]} invitations**'
    embed = discord.Embed(title='🔗 Invitations', description=description, colour=discord.Colour.teal())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='invites-set', description='Sets the exact number of invitations from a member.')
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(membre='member', nombre='count')
@app_commands.describe(membre='Member to update', nombre='New exact invite count')
async def set_invites_command(interaction: discord.Interaction, membre: discord.Member, nombre: int) -> None:
    if interaction.guild is None:
        return
    if nombre < 0:
        await interaction.response.send_message('The number of invitations cannot be negative.', ephemeral=True)
        return
    connection = require_database()
    connection.execute('\n        INSERT INTO invite_stats (guild_id, user_id, invite_count)\n        VALUES (?, ?, ?)\n        ON CONFLICT(guild_id, user_id) DO UPDATE SET\n            invite_count = excluded.invite_count\n        ', (interaction.guild.id, membre.id, nombre))
    connection.commit()
    await update_invite_role(membre)
    await interaction.response.send_message(f'✅ {membre.mention} now has exactly **{nombre} invitation(s) **.', ephemeral=True)

@bot.tree.command(name='giveaway-create', description='Creates a complete Giveaway with weighted draw.')
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(lot='prize', duree='duration', gagnants='winners', salon='channel')
@app_commands.describe(lot='Prize to win', duree='Duration, e.g. 30m, 2h or 1d12h', gagnants='Number of winners', salon='Channel where the giveaway will be posted')
async def create_giveaway_command(interaction: discord.Interaction, lot: str, duree: str, gagnants: app_commands.Range[int, 1, 20]=1, salon: discord.TextChannel | None=None) -> None:
    if interaction.guild is None:
        return
    duration_seconds = parse_duration(duree)
    if duration_seconds is None:
        await interaction.response.send_message('Invalid duration. Examples: `30m`, `2h`, `1d12h` (minimum 10 seconds, maximum 1 year).', ephemeral=True)
        return
    target_channel = salon or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message('Choose a text room.', ephemeral=True)
        return
    ends_at = int(time.time()) + duration_seconds
    embed = discord.Embed(title=f'🎉 GIVEAWAY • {lot[:180]}', description=f'Click on ** Participate ** to try your luck!\n\nEnd: <t:{ends_at}:F> • <t:{ends_at}:R>\nWinner(s): **{gagnants}**\nOrganized by: {interaction.user.mention}\n\n** Chance Bonus **\n5 invitations: +0.5\n10 invitations: +1\n15 invitations: +1.5\n20 invitations: +2\nServer booster: +1', colour=discord.Colour.magenta())
    embed.set_footer(text='The role of invitations does not combine • Booster bonus stacks together')
    await interaction.response.defer(ephemeral=True, thinking=True)
    message = await target_channel.send(embed=embed, view=GiveawayView())
    connection = require_database()
    connection.execute('\n        INSERT INTO giveaways (\n            message_id, guild_id, channel_id, host_id, prize,\n            winners_count, ends_at, created_at\n        )\n        VALUES (?, ?, ?, ?, ?, ?, ?, ?)\n        ', (message.id, interaction.guild.id, target_channel.id, interaction.user.id, lot[:180], gagnants, ends_at, int(time.time())))
    connection.commit()
    await interaction.followup.send(f'Giveaway created: {message.jump_url}', ephemeral=True)

@bot.tree.command(name='giveaway-end', description='Immediately complete a Giveaway.')
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(message_id='Giveaway message ID')
async def end_giveaway_command(interaction: discord.Interaction, message_id: str) -> None:
    if not message_id.isdigit() or get_giveaway(int(message_id)) is None:
        await interaction.response.send_message('Giveaway introuvable.', ephemeral=True)
        return
    giveaway = get_giveaway(int(message_id))
    if giveaway is None or giveaway[6] != 'active':
        await interaction.response.send_message('This giveaway is already over.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    winners = await finish_giveaway(int(message_id))
    await interaction.followup.send(f'Giveaway finished with **{len(winners)} winner(s) **.', ephemeral=True)

@bot.tree.command(name='giveaway-reroll', description='Make a new draw of a finished Giveaway.')
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(message_id='Giveaway message ID')
async def reroll_giveaway_command(interaction: discord.Interaction, message_id: str) -> None:
    if not message_id.isdigit():
        await interaction.response.send_message('Invalid message ID.', ephemeral=True)
        return
    giveaway = get_giveaway(int(message_id))
    if giveaway is None or giveaway[6] != 'ended':
        await interaction.response.send_message('This giveaway is not found or active.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    winners = await finish_giveaway(int(message_id), reroll=True)
    await interaction.followup.send(f'Reissued with **{len(winners)} winner(s) **.', ephemeral=True)

@bot.tree.command(name='giveaway-cancel', description='Cancel a giveaway without pulling a winner.')
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(message_id='Giveaway message ID')
async def cancel_giveaway_command(interaction: discord.Interaction, message_id: str) -> None:
    if not message_id.isdigit():
        await interaction.response.send_message('Invalid message ID.', ephemeral=True)
        return
    giveaway = get_giveaway(int(message_id))
    if giveaway is None or giveaway[6] != 'active':
        await interaction.response.send_message('This giveaway is not found or is no longer active.', ephemeral=True)
        return
    guild_id, channel_id, _, prize, _, _, _ = giveaway
    guild = bot.get_guild(guild_id)
    channel = guild.get_channel(channel_id) if guild is not None else None
    require_database().execute("UPDATE giveaways SET status = 'cancelled' WHERE message_id = ?", (int(message_id),))
    require_database().commit()
    if isinstance(channel, discord.TextChannel):
        try:
            message = await channel.fetch_message(int(message_id))
            embed = message.embeds[0] if message.embeds else discord.Embed()
            embed.title = f'Giveaway cancelled • {prize}'
            embed.colour = discord.Colour.red()
            await message.edit(embed=embed, view=GiveawayView())
        except discord.HTTPException:
            pass
    await interaction.response.send_message('Giveaway canceled without draw.', ephemeral=True)

@bot.tree.command(name='level-give', description='Give one or more levels to a member.')
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(membre='member', levelx='levels')
@app_commands.describe(membre='Member receiving the levels', levelx='Number of levels to add')
async def give_levels_command(interaction: discord.Interaction, membre: discord.Member, levelx: int) -> None:
    if interaction.guild is None:
        return
    if membre.bot:
        await interaction.response.send_message('Levels cannot be attributed to a bot.', ephemeral=True)
        return
    if levelx < 1:
        await interaction.response.send_message('The number of levels shall be greater than zero.', ephemeral=True)
        return
    message_xp, voice_xp, bonus_xp, _, _ = get_member_stats(interaction.guild.id, membre.id)
    total_xp = message_xp + voice_xp + bonus_xp
    current_level = calculate_level(total_xp)
    target_level = current_level + levelx
    target_xp = target_level * target_level * 100
    if target_xp > 9223372036854775807:
        await interaction.response.send_message('This number exceeds the maximum database capacity.', ephemeral=True)
        return
    granted_xp = target_xp - total_xp
    connection = require_database()
    connection.execute('\n        INSERT INTO member_stats (guild_id, user_id, bonus_xp)\n        VALUES (?, ?, ?)\n        ON CONFLICT(guild_id, user_id) DO UPDATE SET\n            bonus_xp = bonus_xp + excluded.bonus_xp\n        ', (interaction.guild.id, membre.id, granted_xp))
    connection.commit()
    await update_level_role(membre)
    await interaction.response.send_message(f'✅ {membre.mention} advanced from level **{current_level}** to **{target_level}** with **{granted_xp:,} bonus XP**.', ephemeral=True)

@bot.tree.command(name='level-reset', description='Reset the level and XP of a member.')
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(membre='member')
@app_commands.describe(membre='Member whose level will be reset')
async def reset_level_command(interaction: discord.Interaction, membre: discord.Member) -> None:
    if interaction.guild is None:
        return
    if membre.bot:
        await interaction.response.send_message('Bot levels are not managed.', ephemeral=True)
        return
    message_xp, voice_xp, bonus_xp, _, _ = get_member_stats(interaction.guild.id, membre.id)
    previous_xp = message_xp + voice_xp + bonus_xp
    previous_level = calculate_level(previous_xp)
    connection = require_database()
    connection.execute('\n        INSERT INTO member_stats (\n            guild_id, user_id, message_xp, voice_xp, bonus_xp\n        )\n        VALUES (?, ?, 0, 0, 0)\n        ON CONFLICT(guild_id, user_id) DO UPDATE SET\n            message_xp = 0,\n            voice_xp = 0,\n            bonus_xp = 0,\n            last_message_xp = 0\n        ', (interaction.guild.id, membre.id))
    connection.commit()
    await update_level_role(membre)
    await interaction.response.send_message(f'{membre.mention} has been reset: level **{previous_level} → 0** and **{previous_xp:,} XP** removed.', ephemeral=True)

async def _setup_server_structure(interaction: discord.Interaction) -> None:
    """Fully restores the community structure of the server."""
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message('This command must be used in a server.', ephemeral=True)
        return
    if guild.id in setup_in_progress_guilds:
        await interaction.response.send_message('A `/setup` is already running on this server.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    setup_in_progress_guilds.add(guild.id)
    reason = f'Command /setup launched by {interaction.user} ({interaction.user.id})'
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
    community_was_enabled = 'COMMUNITY' in guild.features
    old_community_channels = tuple((channel for channel in (guild.rules_channel, guild.public_updates_channel) if channel is not None))
    try:
        await reset_dynamic_server_data(guild)
        roles, created_roles = await ensure_roles(guild, reason)
        await restore_invite_roles(guild)
        default_permissions = guild.default_role.permissions
        default_permissions.update(mention_everyone=False)
        await guild.default_role.edit(permissions=default_permissions, reason='Disable @everyone and @here for members')
        deleted_channels, deleted_categories = await delete_all_channels(guild, reason)
        for spec in UNCATEGORIZED_CHANNELS:
            _, created, fallback = await ensure_channel(guild, spec, None, reason, reuse_existing=False)
            created_channels += int(created)
            stage_fallbacks += int(fallback)
        for category_spec in SERVER_STRUCTURE:
            if category_spec.staff_only:
                category = await guild.create_category(category_spec.name, overwrites=staff_overwrites(guild, roles), reason=reason)
            elif category_spec.staff_voice:
                category = await guild.create_category(category_spec.name, overwrites=staff_voice_overwrites(guild, roles), reason=reason)
            elif category_spec.stats_only:
                category = await guild.create_category(category_spec.name, overwrites=server_stats_overwrites(guild, roles), reason=reason)
            elif category_spec.verification_only:
                category = await guild.create_category(category_spec.name, overwrites=verification_overwrites(guild, roles), reason=reason)
            else:
                category = await guild.create_category(category_spec.name, overwrites=member_overwrites(guild, roles), reason=reason)
            created_categories += 1
            for channel_spec in category_spec.channels:
                channel, created, fallback = await ensure_channel(guild, channel_spec, category, reason, reuse_existing=False)
                created_channels += int(created)
                stage_fallbacks += int(fallback)
                if isinstance(channel, discord.TextChannel) and (not category_spec.staff_only):
                    await channel.set_permissions(roles[MEMBER_ROLE_NAME], view_channel=True, read_message_history=True, send_messages=not channel_spec.read_only, add_reactions=True, use_application_commands=True, reason=reason)
                    for role_name in channel_spec.write_roles:
                        await channel.set_permissions(roles[role_name], view_channel=True, read_message_history=True, send_messages=True, add_reactions=True, reason=reason)
                if isinstance(channel, discord.VoiceChannel) and category_spec.staff_voice and (channel_spec.member_connect is not None):
                    await channel.set_permissions(roles[MEMBER_ROLE_NAME], view_channel=True, connect=channel_spec.member_connect, speak=False, reason=reason)
                if channel_spec.name == ROLE_SELECTION_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    role_selection_channel = channel
                if channel_spec.name == TICKET_PANEL_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    ticket_panel_channel = channel
                if channel_spec.name == TICKET_RULES_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    ticket_rules_channel = channel
                if channel_spec.name == RECRUITMENT_INFO_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    recruitment_info_channel = channel
                if channel_spec.name == RECRUITMENT_PANEL_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    recruitment_panel_channel = channel
                if channel_spec.name == FAQ_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    faq_channel = channel
                if channel_spec.name == CHANGELOG_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    changelog_channel = channel
                if channel_spec.name == TRADE_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    trade_channel = channel
                if channel_spec.name == TRADE_MARKET_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    trade_market_channel = channel
                if channel_spec.name == PLAYER_CV_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    player_cv_channel = channel
                if channel_spec.name == CREW_PRESENTATION_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    crew_presentation_channel = channel
                if channel_spec.name == CREW_RECRUITMENT_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    crew_recruitment_channel = channel
                if channel_spec.name == CLIPS_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    clips_channel = channel
                if channel_spec.name == VERIFICATION_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    verification_channel = channel
                if channel_spec.name == RULES_CHANNEL_NAME and isinstance(channel, discord.TextChannel):
                    rules_channel = channel
        await update_server_stats(guild)
        if rules_channel is not None:
            rules_embed = discord.Embed(title=f'{guild.name} Rules', description='Welcome to the community! By joining and using this server, you agree to the rules below. They keep the community welcoming, safe and accessible to everyone.', colour=discord.Colour.orange())
            rules_embed.add_field(name='1・Respect and behavior', value='Respect every member. Harassment, insults, discrimination, threats, repeated provocation and toxic behavior are prohibited.', inline=False)
            rules_embed.add_field(name='2・Allowed content', value='NSFW, shocking, illegal or dangerous content is prohibited. This also applies to avatars, usernames, statuses, links, images and voice channels.', inline=False)
            rules_embed.add_field(name='3・Spam and mentions', value='Spam, flooding, repeated messages, excessive capitals, mass mentions and disruptive bot usage are prohibited.', inline=False)
            rules_embed.add_field(name='4・Advertising and partnerships', value='Unauthorized private or public advertising is prohibited. Partnership proposals must go through a **Partnership** ticket.', inline=False)
            rules_embed.add_field(name='5・Roblox, games and purchases', value='Scams, fake giveaways, suspicious Roblox links, account sales and requests for login details are prohibited. Report purchase issues through a ticket without posting private information.', inline=False)
            rules_embed.add_field(name='6・Cheating and security', value='Do not share exploits, malicious software, hacking methods or content designed to bypass Roblox, Discord or game rules.', inline=False)
            rules_embed.add_field(name='7・Text and voice channels', value='Use each channel for its intended purpose. In voice channels, avoid shouting, disruptive soundboards, excessive noise and unjustified kicks.', inline=False)
            rules_embed.add_field(name='8・Tickets and reports', value='Do not open fake tickets or contact staff privately without a valid reason. Provide honest information and evidence whenever possible.', inline=False)
            rules_embed.add_field(name='9・Privacy', value='Do not publish personal information without consent. Impersonation, doxxing and malicious sharing of private conversations are prohibited.', inline=False)
            rules_embed.add_field(name='10・Moderation and sanctions', value='Staff may warn, timeout, kick or ban members depending on severity and repetition. Evading a sanction with another account will make it worse. Appeals must be submitted calmly through a ticket.', inline=False)
            rules_embed.add_field(name='✅ Verification', value=f'Then click the button in **{VERIFICATION_CHANNEL_NAME}**. Not knowing the rules does not excuse a violation.', inline=False)
            rules_embed.set_footer(text=f'{guild.name} • The rules may be updated when necessary')
            await rules_channel.send(embed=rules_embed)
        if verification_channel is not None:
            verification_embed = discord.Embed(title='Community Verification', description=f'Welcome to **{guild.name}**!\n\nBefore accessing the server, read the rules carefully and click the button below to confirm that you accept them.\n\nYou will automatically receive the `✅・Member` role.', colour=discord.Colour.green())
            verification_embed.set_footer(text='Following the rules is mandatory')
            await verification_channel.send(embed=verification_embed, view=VerificationView())
        if role_selection_channel is not None:
            embed = discord.Embed(title='Choose your roles', description='Use the menus below to customize your notifications, select your community profile and indicate which platforms you use to play Roblox.\n\nThe `💡・Creator` and `🐛・Bug Hunter` roles are staff-awarded distinctions and cannot be self-assigned.', colour=discord.Colour.orange())
            embed.set_footer(text=guild.name)
            await role_selection_channel.send(embed=embed, view=RoleSelectionView())
        if faq_channel is not None:
            faq_embed = discord.Embed(title='Frequently Asked Questions', description=f'Find here the quick answers to the most common questions about the community of {guild.name}.', colour=discord.Colour.blurple())
            faq_embed.add_field(name='How to access the server?', value='Read the rules and then validate the check. The Member role will automatically unlock the community channels.', inline=False)
            faq_embed.add_field(name='How do I get my roles?', value='Use the choice-of-role menus to select your notifications, profile and Roblox platforms.', inline=False)
            faq_embed.add_field(name='How do I contact the staff?', value='Read the ticket rules and then use the help desk. Applications have a separate category.', inline=False)
            faq_embed.add_field(name='How to create a private voice?', value='Join the room Create a voice. Your temporary channel will be created automatically. Manage it with `/voice-limit`, `/voice-private`, `/voice-invite` and `/voice-kick`.', inline=False)
            faq_embed.add_field(name='How to gain levels?', value='Be active in discussions and voice channels. Use `/level` to display your map and `/leaderboard` to see the ranking.', inline=False)
            faq_embed.add_field(name='How do giveaways work?', value='Click Participate under the Giveaway. Invitation roles and server boost can increase your chances.', inline=False)
            faq_embed.set_footer(text='Missing a question? Open an Assistance ticket')
            await faq_channel.send(embed=faq_embed)
        if changelog_channel is not None:
            changelog_embed = discord.Embed(title='', description='Updates, show changes, bot features and important changes will be announced here.', colour=discord.Colour.orange())
            changelog_embed.add_field(name='🚀 Initial setup', value='Creation of community structure, ticket centre, levels, invitations, giveaways and protections.', inline=False)
            changelog_embed.set_footer(text=guild.name)
            await changelog_channel.send(embed=changelog_embed)
        studio_information = {stylize_channel_name('🛠️・progress'): ('Project progress', 'The team will publish here the important stages of development: completed systems, maps, interfaces, tests and ongoing objectives.'), stylize_channel_name('📰・updates'): ('Updates', 'Find here the changelogs of our games, new features, bug fixes and deployed improvements.'), stylize_channel_name('🚨・admin-abuse'): ('🚨 Sessions Admin Abuse', 'The dates, schedules, games and instructions of the next sessions of Admin Abuse will be announced here.'), stylize_channel_name('🎮・new-games'): ('🎮 New games', 'Each new Roblox project will be presented here with its description, link and access information.'), stylize_channel_name('🗺️・roadmap'): ('🗺️ Public roadmap', 'This roadmap presents the expected features. Dates remain indicative and may evolve during development.'), stylize_channel_name('📋・become-a-tester'): ('Become a beta tester', 'Openings of applications and conditions for access to the tests will be published here. Do not contact the team in private to request the role.'), stylize_channel_name('🐛・bug-reports'): ('Report bug', 'Indicates the game, platform, steps to reproduce the problem and adds a capture or video if possible. Do not share any personal data.'), stylize_channel_name('🔗・official-links'): ('🔗 Official links', 'Only the links published in this channel are considered official. Never enter your Roblox password on a site sent in a private message.')}
        for channel_name, (title, description) in studio_information.items():
            info_channel = discord.utils.get(guild.text_channels, name=channel_name)
            if info_channel is not None:
                await info_channel.send(embed=discord.Embed(title=title, description=description, colour=discord.Colour.blurple()))
        if trade_channel is not None:
            trade_embed = discord.Embed(title='Security and Trade Value', description='Before you accept an exchange, you can consult the fruit values on ** Blox Fruits Values **:\n\nhttps://bloxfruitsvalues.com/\n\nCompare both sides of the trade and ask the community for advice if you have a doubt.', colour=discord.Colour.green())
            trade_embed.add_field(name='⛔ Always reject these offers', value='• Exchange for an object or currency of a ** other game **\n• Give your fruit first against a promise of payment after\n• Lending fruit, account or object with promise of restitution\n• Use a false middleman or intermediary imposed by the other\n• Click on a Roblox, Discord or Inventory link sent in private\n• Exchange an account, real money or your credentials', inline=False)
            trade_embed.add_field(name='✅ Best practices', value='Perform all the exchange in the official Blox Fruits window, check one last time before confirming and make catches. If the exchange does not fit into a single secure transaction, ** will refuse it **. A promise is never a guarantee.', inline=False)
            trade_embed.add_field(name='⚠️ Indicative values', value='The values of a site can evolve and do not guarantee that an exchange is channel. Ask for several opinions if you have a doubt.', inline=False)
            trade_embed.set_footer(text=f'{guild.name} is not affiliated with Blox Fruits Values')
            await trade_channel.send(embed=trade_embed)
        if trade_market_channel is not None:
            await trade_market_channel.send(embed=discord.Embed(title='Secure Trade Market', description='Publish an offer with `/trade-publish` indicating what you are proposing and searching. You can paste custom emojis from the server into both fields.\n\nAn interested person clicks on the button: a private channel is created. Each participant can only have one active trade. At the end, use `/trade-review` or `/trade-close`.', colour=discord.Colour.teal()))
        if player_cv_channel is not None:
            cv_embed = discord.Embed(title='Create your player resume', description='No normal messages are allowed in this room.\n\nUse only ** `/cv-create` **: the bot will open a private form and then publish your resume for you. Launch the same command to modify your existing CV.', colour=discord.Colour.teal())
            cv_embed.add_field(name='Requested information', value='Nickname Roblox, sea level, fruit/race/V4, activities, availability, platform, region and type of crew sought.', inline=False)
            cv_embed.add_field(name='Rules', value='No false information, spam, external server recruitment or personal contact information. Answer CVs in private message without harassing the author.', inline=False)
            await player_cv_channel.send(embed=cv_embed)
        if crew_presentation_channel is not None:
            await crew_presentation_channel.send(embed=discord.Embed(title='', description='Each crew created with `/crew-create` automatically appears here with its captain and number of members. The presentations are updated by the bot.', colour=discord.Colour.gold()))
        if crew_recruitment_channel is not None:
            await crew_recruitment_channel.send(embed=discord.Embed(title='Crew recruitment', description='No normal messages are allowed in this room.\n\nThe captains publish with ** `/crew-recruitment` **. The bot opens a form and then sends the ad with a ** button Apply **.\n\nTo apply, you must have created your CV with `/cv-create`. A private channel will then be opened with the captain.', colour=discord.Colour.gold()))
        if clips_channel is not None:
            clips_embed = discord.Embed(title='', description='Share here your best moments on our Roblox, YouTube or Twitch games.', colour=discord.Colour.purple())
            clips_embed.add_field(name='Authorized', value='Your own clips, the official clips and the creations for which you have permission. Add a short description.', inline=False)
            clips_embed.add_field(name='⛔ Prohibited', value='Stolen or creditless content, repeated advertising, NSFW content, humiliation, harassment, cheating, suspicious links and spam.', inline=False)
            clips_embed.set_footer(text='An automatic reminder of these rules is published every day')
            await clips_channel.send(embed=clips_embed)
        if ticket_rules_channel is not None:
            ticket_rules_embed = discord.Embed(title='Payment and use of tickets', description='Tickets are used to contact the server team privately. Read these instructions before opening one.', colour=discord.Colour.orange())
            ticket_rules_embed.add_field(name='How do I open a ticket?', value=f"1. Go in. {TICKET_PANEL_CHANNEL_NAME}.\n2. Choose the button for your request.\n3. Fill in the form with specific information.\n4. Wait for the staff's response in the created private channel.", inline=False)
            ticket_rules_embed.add_field(name='To be undertaken', value='Clearly explain the problem, add catch or evidence if necessary and remain available to answer questions.', inline=False)
            ticket_rules_embed.add_field(name='⛔ Prohibited', value='False tickets, spam, insults, repeated staff statements, duplicate requests and ticket closure before the end of its processing.', inline=False)
            ticket_rules_embed.set_footer(text='Any abuse of the ticket system can be punished')
            await ticket_rules_channel.send(embed=ticket_rules_embed)
        if ticket_panel_channel is not None:
            ticket_embed = discord.Embed(title=f"🎫 Centre d'assistance de {guild.name}", description='Choose the type of request that fits your situation.\nA private channel will be created between you and the team.\n\n** Assistance ** — general question or problem\n** Partnership ** — propose a collaboration\n** Report ** — report member or behavior\n** Bug ** — report a problem in a game\n\n** Appeal for sanction ** — calmly contest a sanction', colour=discord.Colour.orange())
            ticket_embed.set_footer(text='One ticket opened by type and member')
            await ticket_panel_channel.send(embed=ticket_embed, view=TicketPanelView())
        if recruitment_info_channel is not None:
            recruitment_info_embed = discord.Embed(title=f'Join the team of {guild.name}', description='You want to help the community and participate in its evolution? Read the conditions below before submitting your application.', colour=discord.Colour.green())
            recruitment_info_embed.add_field(name='', value='• Being mature, respectful and active on the server\n• Know the rules well and know how to keep calm\n• Being available regularly and working as a team\n• Provide an honest and sufficiently detailed application', inline=False)
            recruitment_info_embed.add_field(name='📝 How to apply', value=f'Go back in {RECRUITMENT_PANEL_CHANNEL_NAME}, click on ** File my application **, then complete all the questions. A private ticket will be created to exchange with managers.', inline=False)
            recruitment_info_embed.add_field(name='', value="Don't ask when your application will be processed and don't contact the staff in private. A rejected application must not be resubmitted immediately. Lying can result in a definitive refusal.", inline=False)
            recruitment_info_embed.set_footer(text='The final decision is the responsibility of the server')
            await recruitment_info_channel.send(embed=recruitment_info_embed)
        if recruitment_panel_channel is not None:
            recruitment_panel_embed = discord.Embed(title='Apply', description='After reading the recruitment information, click on the button below and respond carefully to the form.\n\nOnly one open application is allowed per member.', colour=discord.Colour.green())
            await recruitment_panel_channel.send(embed=recruitment_panel_embed, view=RecruitmentPanelView())
        if community_was_enabled and rules_channel is not None and (changelog_channel is not None):
            try:
                await guild.edit(rules_channel=rules_channel, public_updates_channel=changelog_channel, reason='Restoring Community mode after /setup')
                for old_channel in old_community_channels:
                    if old_channel.id not in PRESERVED_SETUP_CHANNEL_IDS and old_channel.id not in {rules_channel.id, changelog_channel.id}:
                        try:
                            await old_channel.delete(reason='Community channel replacement by /setup')
                        except discord.HTTPException:
                            logging.warning('Former trade channel Community %s impossible to remove', old_channel.id)
            except discord.HTTPException:
                logging.exception('Cannot replace Community mode channels')
        helper_role = await ensure_helper_role(guild)
        if helper_role is not None:
            await reconcile_helper_ticket_permissions(guild, helper_role)
        await ensure_discord_audit_log_channel(guild)
        await refresh_command_guides(guild)
        fallback_message = f'\n⚠️ **{stage_fallbacks}** conference channel(s) have been created in voice channels, as Discord does not allow conferences on this server.' if stage_fallbacks else ''
        try:
            await interaction.followup.send(f'Reset completed: **{deleted_categories}** category(s) and **{deleted_channels}** removed, then **{created_categories}** category(s), **{created_channels}** channel(s) and **{created_roles}** new role(s) created.{fallback_message}', ephemeral=True)
        except discord.NotFound:
            logging.info('Reset completed: %s channels and %s categories deleted', deleted_channels, deleted_categories)
    except discord.Forbidden:
        await interaction.followup.send("I don't have the necessary permission. Place my role above the roles involved and grant me ** Manage ** Trade Shows.", ephemeral=True)
    except discord.HTTPException as error:
        logging.exception('Discord refused an operation during /setup')
        await interaction.followup.send(f'Discord refused an operation (`{error.code}`) : `{error.text}`', ephemeral=True)
    finally:
        setup_in_progress_guilds.discard(guild.id)

async def ensure_discord_audit_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    channel = discord.utils.get(guild.text_channels, name=DISCORD_AUDIT_LOG_CHANNEL_NAME)
    if channel is not None:
        return channel
    bot_member = guild.me
    if bot_member is None:
        return None
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {guild.default_role: discord.PermissionOverwrite(view_channel=False), bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)}
    for role in guild.roles:
        if role.name in STAFF_ROLE_NAMES:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    category = discord.utils.get(guild.categories, name=JOURNALS_CATEGORY_NAME)
    try:
        if category is None:
            category = await guild.create_category(JOURNALS_CATEGORY_NAME, overwrites=overwrites, reason='Automatic creation of the log category')
        return await guild.create_text_channel(DISCORD_AUDIT_LOG_CHANNEL_NAME, category=category, overwrites=overwrites, reason='Automatic creation of the Discord audit log')
    except discord.Forbidden:
        logging.warning('Permissions insufficient to create Discord logs on %s', guild.id)
    except discord.HTTPException:
        logging.exception('Unable to create Discord logs on %s', guild.id)
    return None
AUDIT_ACTION_LABELS = {'guild_update': 'Modified server', 'channel_create': 'Channel created', 'channel_update': 'Renowned or modified show', 'channel_delete': 'Channel deleted', 'overwrite_create': 'Channel Permission Added', 'overwrite_update': 'Amended Lounge Permission', 'overwrite_delete': 'Room Permission Deleted', 'kick': 'Expulsion Member', 'ban': 'Banished Member', 'unban': 'Member debanni', 'member_update': 'Profile of an amended member', 'member_role_update': 'Amended member roles', 'member_move': 'Member moved to voice', 'member_disconnect': 'Disconnected member of a voice', 'bot_add': 'Bot added', 'role_create': 'Role created', 'role_update': 'Modified role', 'role_delete': 'Role deleted', 'invite_create': 'Invitation established', 'invite_update': 'Amended invitation', 'invite_delete': 'Invitation deleted', 'webhook_create': 'Webhook created', 'webhook_update': 'Webhook modified', 'webhook_delete': 'Webhook deleted', 'emoji_create': 'Emoji created', 'emoji_update': 'Emoji modified', 'emoji_delete': 'Emoji deleted', 'sticker_create': 'Sticker created', 'sticker_update': 'Sticker modified', 'sticker_delete': 'Sticker deleted', 'thread_create': 'Wire created', 'thread_update': 'Modified wire', 'thread_delete': 'Yarn deleted', 'message_delete': 'Message deleted by staff', 'message_bulk_delete': 'Mass deleted messages', 'message_pin': 'pinned message', 'message_unpin': 'Unpinned message'}

def describe_audit_target(target: object) -> str:
    target_id = getattr(target, 'id', None)
    mention = getattr(target, 'mention', None)
    name = getattr(target, 'display_name', None) or getattr(target, 'name', None) or str(target)
    description = str(mention or name)
    if target_id is not None:
        description += f'\n`{target_id}`'
    return description[:1024]

def format_audit_value(value: object) -> str:
    if value is None:
        return 'None'
    if isinstance(value, (list, tuple, set)):
        labels = [getattr(item, 'name', None) or str(item) for item in value]
        return ', '.join(labels)[:300] or 'None'
    return str(getattr(value, 'name', value))[:300]

def audit_changes_summary(entry: discord.AuditLogEntry) -> str | None:
    field_labels = {'name': 'Name', 'nick': 'Nickname', 'topic': 'Subject', 'position': 'Position', 'user_limit': 'User limit', 'roles': 'Roles', 'permissions': 'Permissions', 'slowmode_delay': 'Slow mode', 'nsfw': 'NSFW', 'bitrate': 'Flow', 'communication_disabled_until': 'Timeout'}
    lines: list[str] = []
    for attribute, label in field_labels.items():
        old_value = getattr(entry.before, attribute, None)
        new_value = getattr(entry.after, attribute, None)
        if old_value == new_value or (old_value is None and new_value is None):
            continue
        lines.append(f'**{label} :** `{format_audit_value(old_value)}` → `{format_audit_value(new_value)}`')
        if len(lines) >= 6:
            break
    return '\n'.join(lines)[:1024] if lines else None

async def send_discord_audit_entry(guild: discord.Guild, channel: discord.TextChannel, entry: discord.AuditLogEntry) -> None:
    actor = entry.user
    if actor is None or actor.id == getattr(bot.user, 'id', None):
        return
    actor_member = guild.get_member(actor.id)
    if actor_member is None or not is_ticket_staff(actor_member):
        return
    action_name = entry.action.name
    action_label = AUDIT_ACTION_LABELS.get(action_name, action_name.replace('_', ' ').title())
    embed = discord.Embed(title=f'🧾 {action_label}', colour=discord.Colour.dark_gold(), timestamp=entry.created_at)
    embed.add_field(name='Action taken by', value=f'{actor_member.mention}\n`{actor_member.id}`', inline=True)
    if entry.target is not None:
        embed.add_field(name='Element concerned', value=describe_audit_target(entry.target), inline=True)
    extra_channel = getattr(entry.extra, 'channel', None)
    if extra_channel is not None:
        embed.add_field(name='Channel concerned', value=describe_audit_target(extra_channel), inline=True)
    count = getattr(entry.extra, 'count', None)
    if count is not None:
        embed.add_field(name='Count', value=str(count), inline=True)
    changes = audit_changes_summary(entry)
    if changes:
        embed.add_field(name='Changes', value=changes, inline=False)
    embed.add_field(name='Exact date and time', value=f'<t:{int(entry.created_at.timestamp())}:F>', inline=False)
    if entry.reason:
        embed.add_field(name='Reason', value=entry.reason[:1024], inline=False)
    embed.set_footer(text=f'ID audit : {entry.id}')
    await channel.send(embed=embed)

@tasks.loop(seconds=10)
async def discord_audit_log_loop() -> None:
    connection = require_database()
    for guild in managed_guilds():
        if guild.id in setup_in_progress_guilds:
            continue
        channel = await ensure_discord_audit_log_channel(guild)
        if channel is None:
            continue
        state = connection.execute('SELECT last_entry_id FROM audit_log_state WHERE guild_id = ?', (guild.id,)).fetchone()
        try:
            entries = [entry async for entry in guild.audit_logs(limit=100)]
        except discord.Forbidden:
            logging.warning('Permission See missing audit log on %s', guild.id)
            continue
        except discord.HTTPException:
            logging.exception('Could not read audit log on %s', guild.id)
            continue
        if not entries:
            continue
        newest_id = max((entry.id for entry in entries))
        if state is None:
            connection.execute('\n                INSERT INTO audit_log_state (guild_id, last_entry_id)\n                VALUES (?, ?)\n                ', (guild.id, newest_id))
            connection.commit()
            continue
        last_entry_id = state[0]
        for entry in sorted(entries, key=lambda current: current.id):
            if entry.id <= last_entry_id:
                continue
            try:
                await send_discord_audit_entry(guild, channel, entry)
            except discord.HTTPException:
                logging.exception('Could not send audit entry %s', entry.id)
        connection.execute('\n            UPDATE audit_log_state SET last_entry_id = ?\n            WHERE guild_id = ?\n            ', (newest_id, guild.id))
        connection.commit()

@discord_audit_log_loop.before_loop
async def before_discord_audit_log_loop() -> None:
    await bot.wait_until_ready()

async def _setup_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        message = 'You must be an administrator to use `/setup`.'
    else:
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        logging.error('Error not managed in /setup', exc_info=(type(original), original, original.__traceback__))
        message = f'An error occurred during `/setup`: `{type(original).__name__}: {original}`'
    if interaction.response.is_done():
        try:
            await interaction.followup.send(message, ephemeral=True)
        except discord.NotFound:
            logging.error('Could not display error: the show was deleted')
    else:
        await interaction.response.send_message(message, ephemeral=True)

@bot.tree.command(name='setup', description='Reconstructs the entire server structure.')
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def setup_command(interaction: discord.Interaction) -> None:
    await _setup_server_structure(interaction)

@setup_command.error
async def setup_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    await _setup_error(interaction, error)

async def publish_bot_update(guild: discord.Guild) -> None:
    connection = require_database()
    if connection.execute('\n        SELECT 1 FROM bot_update_posts\n        WHERE guild_id = ? AND version = ?\n        ', (guild.id, BOT_UPDATE_VERSION)).fetchone():
        return
    channel = discord.utils.get(guild.text_channels, name=CHANGELOG_CHANNEL_NAME)
    if channel is None:
        logging.warning('Update channel not found on server %s', guild.id)
        return
    embed = discord.Embed(title='Community bot — Full functionality', description='Here are all the systems currently available on the server, as well as the latest additions to the bot.', colour=discord.Colour.orange(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name='Automatic server installation', value='The structure includes categories, channels, roles, permissions and signs. Protected channels are preserved and official spaces remain read-only.', inline=False)
    embed.add_field(name='Verification and reception', value='Full settlement, check button, member/bot autoroles, personalized welcome message, FAQ, changelog and role selection.', inline=False)
    embed.add_field(name='Statistics and activity', value='XP by messages and voice time, progression roles, `/level` card, `/leaderboard`, addition and level reset.', inline=False)
    embed.add_field(name='🔗 Invites and boosters', value='Counting invitations, automatic assignment of the four recruitment roles, `/invites`, `/invites-set` and automatic thank you of the booster members.', inline=False)
    embed.add_field(name='Weighted Giveaways', value='Creation, participation, list of participants, exact duration, additional chances depending on invitations and boosts, draw, reroll, cancellation and reminders at 24 hours and 1 hour.', inline=False)
    embed.add_field(name='🛡️ Automatic protection', value='Antispam, block massive mentions, `@everyone`, fraudulent links, suspicious domains and shortcuts, with automatic deletion and timeout. Recent accounts remain authorized.', inline=False)
    embed.add_field(name='Studio Roblox and community', value='Game progress, updates, admin ads abuse, new games, public roadmap, community tests, bug reports, clips, suggestions and community content.', inline=False)
    embed.add_field(name='Test and creation Roblox', value='Beta-test space, returns and bugs, as well as channels dedicated to development, building, design UI, modeling, audio, resources and ideas of Roblox games.', inline=False)
    embed.add_field(name='Communication of games', value='Official spaces to present the main game, current projects, old games, their links and server status.', inline=False)
    embed.add_field(name='🆘 Helpers and tickets', value='A unique centre for assistance, partnerships, reporting, bugs, purchasing problems and sanction calls. Tickets have an exclusive form, claim, confirmed closure, private permissions, Helpers points and transcripts.', inline=False)
    embed.add_field(name='Moderation and logs', value='Numbered folders, cancellation by button, internal notes, automatic escalation of warns, limited clear with filter per member, monthly statistics and separate logs for messages, voice, arrivals, departures and tickets. The new Discord log accurately identifies the actions of the staff, and each ticket claim retains its author, date and time.', inline=False)
    embed.add_field(name='💡 Community suggestions', value='Form `/suggestion`, votes For/Contract unique and editable, official status Waiting/Accepted/Refused/Realized and Staff Response.', inline=False)
    embed.add_field(name='Events', value='Order creation, registration, seating limit, participants, waiting list, reminders at 24 hours and 30 minutes, cancellation, closing and podium with medal roles.', inline=False)
    embed.add_field(name='🔊 Temporary voice channels', value='Creation of a temporary voice, personalized limit, private mode, invitation with direct link, expulsion, vacuum removal and automatic transmission to the member who has been present for the longest time.', inline=False)
    embed.add_field(name='📢 Automations', value='Welcome messages, rules, FAQs, ticket instructions, clip rules, social reminders, giveaways, events and versioned publication of bot updates.', inline=False)
    embed.set_footer(text=f'{guild.name} • Version {BOT_UPDATE_VERSION}')
    try:
        message = await channel.send(embed=embed)
    except discord.HTTPException:
        logging.exception('Could not publish bot update')
        return
    connection.execute('\n        INSERT INTO bot_update_posts (guild_id, version, message_id, posted_at)\n        VALUES (?, ?, ?, ?)\n        ', (guild.id, BOT_UPDATE_VERSION, message.id, int(time.time())))
    connection.commit()

async def upsert_command_guide(channel: discord.TextChannel, *, title: str, embed: discord.Embed) -> None:
    try:
        async for message in channel.history(limit=100):
            if message.author == bot.user and message.embeds and (message.embeds[0].title == title):
                await message.edit(embed=embed)
                return
        await channel.send(embed=embed)
    except discord.HTTPException:
        logging.exception('Could not update guide %s', title)

async def refresh_command_guides(guild: discord.Guild) -> None:
    commands_channel = discord.utils.get(guild.text_channels, name=COMMANDS_CHANNEL_NAME)
    if commands_channel is not None:
        embed = discord.Embed(title='Bot controls', description='All commands use ** dashes **. Commands displayed by Discord with an old name should no longer be used.', colour=discord.Colour.blue())
        embed.add_field(name='Profile and community', value='`/level` • show your map\n`/leaderboard` • activity classification\n`/invites` • view your invitations\n`/suggestion` • suggest an idea', inline=False)
        embed.add_field(name='Temporary voice', value='`/voice-limit`\n`/voice-private`\n`/voice-invite`\n`/voice-kick`', inline=False)
        embed.add_field(name='🎮 Studio Roblox', value='Consult the promotion channels, updates, new games and admin abuse. Use `/suggestion` to propose an idea and support to report a bug or purchase problem.', inline=False)
        embed.add_field(name='🆘 Helpers', value='`/warns` and `/member-info` are the only helper commands available.', inline=False)
        embed.set_footer(text='The staff can publish its catalog with /admin-commands')
        await upsert_command_guide(commands_channel, title='Bot controls', embed=embed)
    suggestions_channel = discord.utils.get(guild.text_channels, name=SUGGESTIONS_CHANNEL_NAME)
    if suggestions_channel is not None:
        embed = discord.Embed(title='Propose and vote a suggestion', description='Use ** `/suggestion` ** to open the form. The bot then publishes your idea with the ** buttons for ** and ** against **.', colour=discord.Colour.gold())
        embed.add_field(name='How it works', value='Only one vote per member, subject to change at any time. The staff will then indicate whether the suggestion is accepted, refused or carried out, with an official response.', inline=False)
        await upsert_command_guide(suggestions_channel, title='Propose and vote a suggestion', embed=embed)
    cv_channel = discord.utils.get(guild.text_channels, name=PLAYER_CV_CHANNEL_NAME)
    if cv_channel is not None:
        embed = discord.Embed(title='Create your player resume', description='Use only ** `/cv-create` ** in this channel. The bot opens a private form and then publishes your resume. Re-launch the command to modify it.', colour=discord.Colour.teal())
        embed.add_field(name='Requested information', value='Nickname Roblox, level and sea, profile Blox Fruits, availability and type of crew sought.', inline=False)
        await upsert_command_guide(cv_channel, title='Create your player resume', embed=embed)
    recruitment_channel = discord.utils.get(guild.text_channels, name=CREW_RECRUITMENT_CHANNEL_NAME)
    if recruitment_channel is not None:
        embed = discord.Embed(title='Crew recruitment', description='Captains only publish with ** `/crew-recruitment` **. The bot opens the form and adds the ** button Apply **.\n\nCandidates must first use `/cv-create`.', colour=discord.Colour.gold())
        await upsert_command_guide(recruitment_channel, title='Crew recruitment', embed=embed)
    market_channel = discord.utils.get(guild.text_channels, name=TRADE_MARKET_CHANNEL_NAME)
    if market_channel is not None:
        embed = discord.Embed(title='Secure Trade Market', description='Publish with ** `/trade-publish` **. An interested person uses the ad button, then both members finish with `/trade-review`. Use `/trade-close` if the exchange is cancelled.', colour=discord.Colour.teal())
        await upsert_command_guide(market_channel, title='Secure Trade Market', embed=embed)

@bot.event
async def setup_hook() -> None:
    initialize_database()
    for command_name in LEGACY_BLOX_COMMANDS:
        bot.tree.remove_command(command_name)
    bot.add_view(VerificationView())
    bot.add_view(RoleSelectionView())
    bot.add_view(TicketPanelView())
    bot.add_view(TicketControlView())
    bot.add_view(GiveawayView())
    bot.add_view(CommunityEventView())
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
    else:
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
    for guild in managed_guilds():
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
    reminder_rows = connection.execute("\n        SELECT message_id, guild_id, channel_id, prize, ends_at, created_at,\n               reminded_24h, reminded_1h\n        FROM giveaways\n        WHERE status = 'active' AND ends_at > ?\n        ", (current_time,)).fetchall()
    for message_id, guild_id, channel_id, prize, ends_at, created_at, reminded_24h, reminded_1h in reminder_rows:
        remaining = ends_at - current_time
        duration = ends_at - created_at
        reminder_kind: str | None = None
        if duration > 86400 and remaining <= 86400 and (not reminded_24h):
            reminder_kind = '24h'
        elif duration > 3600 and remaining <= 3600 and (not reminded_1h):
            reminder_kind = '1h'
        if reminder_kind is None:
            continue
        guild = bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild is not None else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(f'⏰ **Giveaway reminder — {reminder_kind} remaining**\nThe giveaway **{prize}** ends <t:{ends_at}:R>! [Open the giveaway](https://discord.com/channels/{guild_id}/{channel_id}/{message_id})')
            except discord.HTTPException:
                logging.exception('Could not send Giveaway reminder %s', message_id)
                continue
        column = 'reminded_24h' if reminder_kind == '24h' else 'reminded_1h'
        connection.execute(f'UPDATE giveaways SET {column} = 1 WHERE message_id = ?', (message_id,))
    connection.commit()
    rows = connection.execute("\n        SELECT message_id FROM giveaways\n        WHERE status = 'active' AND ends_at <= ?\n        ", (current_time,)).fetchall()
    for message_id, in rows:
        try:
            await finish_giveaway(message_id)
        except Exception:
            logging.exception('Giveaway Failed %s', message_id)

@giveaway_end_loop.before_loop
async def before_giveaway_end_loop() -> None:
    await bot.wait_until_ready()

@tasks.loop(minutes=1)
async def event_reminder_loop() -> None:
    now = datetime.now(timezone.utc)
    connection = require_database()
    for guild in managed_guilds():
        channel = discord.utils.get(guild.text_channels, name=EVENT_ANNOUNCEMENT_CHANNEL_NAME)
        if channel is None:
            continue
        for event in guild.scheduled_events:
            if event.status is not discord.EventStatus.scheduled:
                continue
            remaining = (event.start_time - now).total_seconds()
            reminder_kind: str | None = None
            if 82800 < remaining <= 86400:
                reminder_kind = '24h'
            elif 1500 < remaining <= 1800:
                reminder_kind = '30m'
            if reminder_kind is None:
                continue
            exists = connection.execute('\n                SELECT 1 FROM event_reminders\n                WHERE guild_id = ? AND event_id = ? AND reminder_kind = ?\n                ', (guild.id, event.id, reminder_kind)).fetchone()
            if exists is not None:
                continue
            timestamp = int(event.start_time.timestamp())
            try:
                await channel.send(f'** Event Reminder — {reminder_kind}**\n**{event.name}** commence <t:{timestamp}:R> (<t:{timestamp}:F>).\n{event.url}')
            except discord.HTTPException:
                logging.exception('Could not recall event %s', event.id)
                continue
            connection.execute('\n                INSERT INTO event_reminders (\n                    guild_id, event_id, reminder_kind, sent_at\n                ) VALUES (?, ?, ?, ?)\n                ', (guild.id, event.id, reminder_kind, int(time.time())))
        custom_events = connection.execute("\n            SELECT message_id, channel_id, name, starts_at,\n                   reminded_24h, reminded_30m\n            FROM community_events\n            WHERE guild_id = ? AND status = 'scheduled'\n            ", (guild.id,)).fetchall()
        current_timestamp = int(now.timestamp())
        for message_id, channel_id, event_name, starts_at, reminded_24h, reminded_30m in custom_events:
            remaining = starts_at - current_timestamp
            if remaining <= 0:
                connection.execute("\n                    UPDATE community_events SET status = 'started'\n                    WHERE message_id = ?\n                    ", (message_id,))
                continue
            reminder_kind = None
            if remaining <= 86400 and (not reminded_24h):
                reminder_kind = '24h'
            if remaining <= 1800 and (not reminded_30m):
                reminder_kind = '30m'
            if reminder_kind is None:
                continue
            event_channel = guild.get_channel(channel_id)
            if not isinstance(event_channel, discord.TextChannel):
                continue
            try:
                await event_channel.send(f'** Event Reminder — {reminder_kind}**\n**{event_name}** commence <t:{starts_at}:R>.\nhttps://discord.com/channels/{guild.id}/{channel_id}/{message_id}')
            except discord.HTTPException:
                continue
            column = 'reminded_24h' if reminder_kind == '24h' else 'reminded_30m'
            connection.execute(f'UPDATE community_events SET {column} = 1 WHERE message_id = ?', (message_id,))
    connection.commit()

@event_reminder_loop.before_loop
async def before_event_reminder_loop() -> None:
    await bot.wait_until_ready()

@tasks.loop(minutes=1)
async def clip_rules_reminder_loop() -> None:
    now = datetime.now(PARIS_TIMEZONE)
    if now.hour != 18:
        return
    slot = f'clips-{now.date().isoformat()}'
    connection = require_database()
    for guild in managed_guilds():
        channel = discord.utils.get(guild.text_channels, name=CLIPS_CHANNEL_NAME)
        if channel is None:
            continue
        row = connection.execute('\n            SELECT last_slot, message_id FROM social_bumps\n            WHERE guild_id = ? AND channel_id = ?\n            ', (guild.id, channel.id)).fetchone()
        if row is not None and row[0] == slot:
            continue
        if row is not None and row[1] is not None:
            try:
                previous = await channel.fetch_message(row[1])
                await previous.delete()
            except discord.HTTPException:
                pass
        try:
            message = await channel.send('** Reminder clips **\nPublish only your content or authorized content, credit the creator, add a description and avoid spam. The stolen, NSFW, humiliating, cheating or suspicious links will be removed.')
        except discord.HTTPException:
            logging.exception('Could not send clip reminder')
            continue
        connection.execute('\n            INSERT INTO social_bumps (guild_id, channel_id, last_slot, message_id)\n            VALUES (?, ?, ?, ?)\n            ON CONFLICT(guild_id, channel_id) DO UPDATE SET\n                last_slot = excluded.last_slot,\n                message_id = excluded.message_id\n            ', (guild.id, channel.id, slot, message.id))
    connection.commit()

@clip_rules_reminder_loop.before_loop
async def before_clip_rules_reminder_loop() -> None:
    await bot.wait_until_ready()

@tasks.loop(minutes=1)
async def social_bump_loop() -> None:
    now = datetime.now(PARIS_TIMEZONE)
    if now.hour not in SOCIAL_BUMP_HOURS:
        return
    slot = f'{now.date().isoformat()}-{now.hour:02d}'
    connection = require_database()
    for guild in managed_guilds():
        for channel_name, content in SOCIAL_BUMP_MESSAGES.items():
            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if channel is None:
                continue
            row = connection.execute('\n                SELECT last_slot, message_id FROM social_bumps\n                WHERE guild_id = ? AND channel_id = ?\n                ', (guild.id, channel.id)).fetchone()
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
                logging.exception('Could not send reminder in %s', channel.id)
                continue
            connection.execute('\n                INSERT INTO social_bumps (guild_id, channel_id, last_slot, message_id)\n                VALUES (?, ?, ?, ?)\n                ON CONFLICT(guild_id, channel_id) DO UPDATE SET\n                    last_slot = excluded.last_slot,\n                    message_id = excluded.message_id\n                ', (guild.id, channel.id, slot, message.id))
    connection.commit()

@social_bump_loop.before_loop
async def before_social_bump_loop() -> None:
    await bot.wait_until_ready()

@bot.event
async def on_message_delete(message: discord.Message) -> None:
    if message.guild is None or message.author.bot:
        return
    channel = discord.utils.get(message.guild.text_channels, name=DELETED_MESSAGE_LOG_CHANNEL_NAME)
    if channel is None:
        return
    embed = discord.Embed(title='Message deleted', colour=discord.Colour.red(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name='Author', value=f'{message.author.mention} (`{message.author.id}`)', inline=False)
    embed.add_field(name='Channel', value=f'{message.channel.mention} (`{message.channel.id}`)', inline=False)
    embed.add_field(name='Content', value=message.content[:1000] or '*No text or content not available*', inline=False)
    if message.attachments:
        embed.add_field(name='Attachments', value='\n'.join((item.url for item in message.attachments))[:1000], inline=False)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
    if before.guild is None or before.author.bot or before.content == after.content:
        return
    channel = discord.utils.get(before.guild.text_channels, name=EDITED_MESSAGE_LOG_CHANNEL_NAME)
    if channel is None:
        return
    embed = discord.Embed(title='modified message', description=f'[Access message]({after.jump_url})', colour=discord.Colour.orange(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name='Author', value=f'{before.author.mention} (`{before.author.id}`)', inline=False)
    embed.add_field(name='Avant', value=before.content[:1000] or '*Vide*', inline=False)
    embed.add_field(name='After', value=after.content[:1000] or '*Vide*', inline=False)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass

@bot.event
async def on_member_join(member: discord.Member) -> None:
    await update_server_stats(member.guild)
    log_channel = discord.utils.get(member.guild.text_channels, name=JOIN_LEAVE_LOG_CHANNEL_NAME)
    if log_channel is not None:
        created_at = int(member.created_at.timestamp())
        try:
            await log_channel.send(embed=discord.Embed(title='Member arrived', description=f'{member.mention} (`{member.id}`)\nAccount created: <t:{created_at}:F> • <t:{created_at}:R>', colour=discord.Colour.green(), timestamp=datetime.now(timezone.utc)).set_thumbnail(url=member.display_avatar.url))
        except discord.HTTPException:
            pass
    if member.bot:
        bot_role = discord.utils.get(member.guild.roles, name=BOT_ROLE_NAME)
        if bot_role is not None:
            try:
                await member.add_roles(bot_role, reason='Control for bots')
            except discord.Forbidden:
                logging.warning('Could not assign Bots role to %s', member)
        return
    await process_member_invite(member)
    role = discord.utils.get(member.guild.roles, name=UNVERIFIED_ROLE_NAME)
    if role is not None:
        try:
            await member.add_roles(role, reason='Member awaiting verification')
        except discord.Forbidden:
            logging.warning('Could not assign %s to %s: incorrect role hierarchy', UNVERIFIED_ROLE_NAME, member)
    welcome_channel = discord.utils.get(member.guild.text_channels, name=WELCOME_CHANNEL_NAME)
    if welcome_channel is None:
        return
    embed = discord.Embed(title=f'Welcome to {member.guild.name}!', description=f'Hey {member.mention}, welcome to our Roblox game development community!\n\n**To access the server:**\n1️⃣ Read the rules in `{RULES_CHANNEL_NAME}`\n2️⃣ Click the verification button in `{VERIFICATION_CHANNEL_NAME}`\n3️⃣ Choose your notification, profile, and platform roles\n\nOnce verified, you can follow game development, receive update and admin-event announcements, share ideas, report bugs, and join tests and events.\n\nYou are member **#{member.guild.member_count}**. Welcome aboard!', colour=discord.Colour.orange())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f'{member.guild.name} • Thanks for joining the community!')
    try:
        await welcome_channel.send(embed=embed)
    except discord.Forbidden:
        logging.warning('Could not send welcome message')

@bot.event
async def on_member_remove(member: discord.Member) -> None:
    await update_server_stats(member.guild)
    if is_helper(member):
        require_database().execute("\n            UPDATE tickets SET claimed_by = NULL\n            WHERE guild_id = ? AND claimed_by = ? AND status = 'open'\n            ", (member.guild.id, member.id))
        require_database().commit()
        helper_role = discord.utils.get(member.guild.roles, name=HELPER_ROLE_NAME)
        if helper_role is not None:
            await reconcile_helper_ticket_permissions(member.guild, helper_role)
    log_channel = discord.utils.get(member.guild.text_channels, name=JOIN_LEAVE_LOG_CHANNEL_NAME)
    if log_channel is not None:
        try:
            await log_channel.send(embed=discord.Embed(title='📤 Member left', description=f'**{member}** (`{member.id}`)', colour=discord.Colour.red(), timestamp=datetime.now(timezone.utc)).set_thumbnail(url=member.display_avatar.url))
        except discord.HTTPException:
            pass

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member) -> None:
    if before.roles != after.roles:
        superior_role = discord.utils.get(after.guild.roles, name=SUPERIOR_STAFF_ROLE_NAME)
        has_superior_source = any((role.name in SUPERIOR_SOURCE_ROLE_NAMES for role in after.roles))
        if superior_role is not None and has_superior_source and (superior_role not in after.roles):
            try:
                await after.add_roles(superior_role, reason='Automatic access to the upper staff')
            except discord.HTTPException:
                logging.exception('Could not assign Staff greater than %s', after.id)
    if before.premium_since != after.premium_since:
        await update_server_stats(after.guild)
    if before.premium_since is None and after.premium_since is not None:
        channel = discord.utils.get(after.guild.text_channels, name=BOOST_THANKS_CHANNEL_NAME)
        if channel is not None:
            embed = discord.Embed(title='Thanks for the boost!', description=f'A huge thank you to {after.mention}, who just boosted the server! Your support directly helps the {after.guild.name} community unlock better Discord perks.', colour=discord.Colour.magenta(), timestamp=datetime.now(timezone.utc))
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.add_field(name='🎉 Giveaway bonus', value='While your boost is active, you automatically receive **+1 entry weight** in giveaways. This stacks with your highest invite reward role.', inline=False)
            embed.set_footer(text=f'The server now has {after.guild.premium_subscription_count} boost(s)')
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                logging.exception('Could not send boost thank you')

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
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
    if member.bot:
        return
    if before.channel != after.channel:
        log_channel = discord.utils.get(member.guild.text_channels, name=VOICE_LOG_CHANNEL_NAME)
        if log_channel is not None:
            if before.channel is None and after.channel is not None:
                action = '🔊 Voice connected'
                details = f'{member.mention} joined {after.channel.mention}.'
                colour = discord.Colour.green()
            elif before.channel is not None and after.channel is None:
                action = '🔇 Voice disconnected'
                details = f'{member.mention} left **{before.channel.name}**.'
                colour = discord.Colour.red()
            else:
                action = '🔄 Voice channel changed'
                details = f'{member.mention} moved from **{before.channel.name}** to {after.channel.mention}.'
                colour = discord.Colour.orange()
            try:
                await log_channel.send(embed=discord.Embed(title=action, description=details, colour=colour, timestamp=datetime.now(timezone.utc)).set_footer(text=f'Member ID: {member.id}'))
            except discord.HTTPException:
                pass
    joined_channel = after.channel
    if joined_channel is not None and joined_channel != before.channel and (joined_channel.name != TEMP_VOICE_TRIGGER_NAME) and (joined_channel.category is not None) and (joined_channel.category.name == TEMP_VOICE_CATEGORY_NAME):
        voice_join_times[joined_channel.id, member.id] = time.monotonic()
    if joined_channel is not None and joined_channel.name == TEMP_VOICE_TRIGGER_NAME and (joined_channel.category is not None) and (joined_channel.category.name == TEMP_VOICE_CATEGORY_NAME):
        safe_name = member.display_name.strip()[:70] or 'Member'
        overwrites = dict(joined_channel.category.overwrites)
        overwrites[member] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, manage_channels=True, move_members=True)
        try:
            temporary_channel = await member.guild.create_voice_channel(f'{TEMP_VOICE_PREFIX}{safe_name}', category=joined_channel.category, overwrites=overwrites, reason=f'Temporary voice created for {member} ({member.id})')
            await member.move_to(temporary_channel, reason='Move to temporary voice')
            try:
                await temporary_channel.send(content=member.mention, embed=build_voice_help_embed())
            except discord.HTTPException:
                logging.exception('Cannot send help to voice chat %s', temporary_channel.id)
        except discord.HTTPException:
            logging.exception('Could not create temporary voice %s', member)
            if 'temporary_channel' in locals():
                await temporary_channel.delete(reason='Failed to move in temporary voice')
    left_channel = before.channel
    if left_channel is not None and left_channel.name != TEMP_VOICE_TRIGGER_NAME and (left_channel.category is not None) and (left_channel.category.name == TEMP_VOICE_CATEGORY_NAME):
        was_owner = left_channel.overwrites_for(member).manage_channels is True
        voice_join_times.pop((left_channel.id, member.id), None)
        if not left_channel.members:
            try:
                await left_channel.delete(reason='Temporary voice become empty')
            except discord.NotFound:
                pass
            except discord.Forbidden:
                logging.warning('Could not delete temporary voice %s', left_channel.id)
            finally:
                stale_keys = [key for key in voice_join_times if key[0] == left_channel.id]
                for key in stale_keys:
                    voice_join_times.pop(key, None)
        elif was_owner:
            candidates = [candidate for candidate in left_channel.members if not candidate.bot]
            if candidates:
                new_owner = min(candidates, key=lambda candidate: voice_join_times.get((left_channel.id, candidate.id), float('inf')))
                old_permissions = left_channel.overwrites_for(member)
                old_permissions.manage_channels = None
                old_permissions.move_members = None
                new_permissions = left_channel.overwrites_for(new_owner)
                new_permissions.view_channel = True
                new_permissions.connect = True
                new_permissions.speak = True
                new_permissions.manage_channels = True
                new_permissions.move_members = True
                safe_name = new_owner.display_name.strip()[:70] or 'Member'
                try:
                    await left_channel.set_permissions(member, overwrite=old_permissions, reason='Ownership of the transmitted temporary voice')
                    await left_channel.set_permissions(new_owner, overwrite=new_permissions, reason='New owner of the temporary voice')
                    await left_channel.edit(name=f'{TEMP_VOICE_PREFIX}{safe_name}', reason=f'Vocal transmitted automatically to {new_owner}')
                    await left_channel.send(f'👑 {new_owner.mention} automatically becomes the owner of the voice, as it is the member present for the longest time.')
                except discord.HTTPException:
                    logging.exception('Could not transmit temporary voice %s', left_channel.id)

@bot.event
async def on_ready() -> None:
    if bot.user is None:
        return
    for guild in managed_guilds():
        helper_role = await ensure_helper_role(guild)
        if helper_role is not None:
            await reconcile_helper_ticket_permissions(guild, helper_role)
        await refresh_command_guides(guild)
        await update_server_stats(guild)
        await refresh_invite_cache(guild)
        await restore_invite_roles(guild)
        await publish_bot_update(guild)
        category = discord.utils.get(guild.categories, name=TEMP_VOICE_CATEGORY_NAME)
        if category is None:
            continue
        for channel in category.voice_channels:
            if channel.name != TEMP_VOICE_TRIGGER_NAME and (not channel.members):
                try:
                    await channel.delete(reason='Cleaning an empty temporary voice on startup')
                except discord.HTTPException:
                    logging.exception('Could not clean temporary voice %s', channel.id)
            elif channel.name != TEMP_VOICE_TRIGGER_NAME:
                startup_time = time.monotonic()
                for position, current_member in enumerate(channel.members):
                    if not current_member.bot:
                        voice_join_times.setdefault((channel.id, current_member.id), startup_time + position / 1000)
    if GUILD_ID:
        guild_object = discord.Object(id=int(GUILD_ID))
        synced = await bot.tree.sync(guild=guild_object)
        scope = f'server {GUILD_ID}'
    else:
        synced = await bot.tree.sync()
        scope = 'global synchronization'
    logging.info('Connected as %s (%s) — %s command(s) synchronized on %s', bot.user, bot.user.id, len(synced), scope)

@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    await refresh_invite_cache(guild)
    if GUILD_ID and guild.id == int(GUILD_ID):
        guild_object = discord.Object(id=guild.id)
        synced = await bot.tree.sync(guild=guild_object)
        logging.info('%s command(s) synchronized on development server %s', len(synced), guild.id)
if __name__ == '__main__':
    if not TOKEN:
        raise RuntimeError('DISCORD TOKEN is absent. Copy.env.example to.env and add token.')
    bot.run(TOKEN)
