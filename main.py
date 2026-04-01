import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1486268008266596443
WELCOME_LOG_CHANNEL_ID = 1486268009550188556
RANKING_CHANNEL_ID = 1486268011823366218
DB_FILE = "faction.db"

ADMIN_ROLES = [
    1486268008409206867,
    1486268008409206864,
    1486268008266596449,
    1486268008266596448
]

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
guild_obj = discord.Object(id=GUILD_ID)

def is_admin(member: discord.Member) -> bool:
    return any(role.id in ADMIN_ROLES for role in member.roles)

def get_week_key():
    now = datetime.now()
    year, week, _ = now.isocalendar()
    return f"{year}-W{week}"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS farms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_key TEXT NOT NULL,
            membro TEXT NOT NULL,
            farm_tipo TEXT NOT NULL,
            qtd REAL NOT NULL,
            admin_id INTEGER NOT NULL,
            admin_name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pvp_events (
            message_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            created_by_id INTEGER NOT NULL,
            created_by_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            week_key TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pvp_confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(message_id, user_id)
        )
    """)

    conn.commit()
    conn.close()

def add_farm(membro: str, farm_tipo: str, qtd: float, admin_id: int, admin_name: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO farms (week_key, membro, farm_tipo, qtd, admin_id, admin_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        get_week_key(),
        membro,
        farm_tipo,
        qtd,
        admin_id,
        admin_name,
        datetime.now().strftime("%d/%m/%Y %H:%M")
    ))
    conn.commit()
    conn.close()

def get_farm_breakdown(limit=10):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT membro,
               SUM(CASE WHEN farm_tipo = 'Pedra' THEN qtd ELSE 0 END) as pedra,
               SUM(CASE WHEN farm_tipo = 'Semente' THEN qtd ELSE 0 END) as semente,
               SUM(qtd) as total
        FROM farms
        WHERE week_key = ?
        GROUP BY membro
        ORDER BY total DESC
        LIMIT ?
    """, (get_week_key(), limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

def save_pvp_event(message_id: int, channel_id: int, title: str, description: str, created_by_id: int, created_by_name: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO pvp_events
        (message_id, channel_id, title, description, created_by_id, created_by_name, created_at, week_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        message_id,
        channel_id,
        title,
        description,
        created_by_id,
        created_by_name,
        datetime.now().strftime("%d/%m/%Y %H:%M"),
        get_week_key()
    ))
    conn.commit()
    conn.close()

def upsert_confirmation(message_id: int, user_id: int, user_name: str, status: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO pvp_confirmations (message_id, user_id, user_name, status, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(message_id, user_id)
        DO UPDATE SET
            user_name=excluded.user_name,
            status=excluded.status,
            updated_at=excluded.updated_at
    """, (
        message_id,
        user_id,
        user_name,
        status,
        datetime.now().strftime("%d/%m/%Y %H:%M")
    ))
    conn.commit()
    conn.close()

def delete_confirmation(message_id: int, user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM pvp_confirmations
        WHERE message_id = ? AND user_id = ?
    """, (message_id, user_id))
    conn.commit()
    conn.close()

def remove_member_from_event(message_id: int, member_name: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM pvp_confirmations
        WHERE 
