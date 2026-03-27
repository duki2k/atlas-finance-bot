import aiosqlite
from datetime import datetime

async def init_db():
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS farms (
            id INTEGER PRIMARY KEY,
            admin_id INTEGER,
            admin_name TEXT,
            target_name TEXT,
            week INTEGER,
            tipo TEXT,
            qtd REAL,
            timestamp TEXT
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS pvp (
            id INTEGER PRIMARY KEY,
            name TEXT,
            msg TEXT,
            participants TEXT,
            timestamp TEXT
        )''')
        await db.commit()

async def add_farm(admin_id, admin_name, target, tipo, qtd):
    week = datetime.now().isocalendar()[1]
    ts = datetime.now().strftime('%d/%m %H:%M')
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('INSERT INTO farms VALUES (NULL,?,?,?,?,?,?,?)',
                        (admin_id, admin_name, target, week, tipo, qtd, ts))
        await db.commit()

async def weekly_top(limit=10):
    week = datetime.now().isocalendar()[1]
    async with aiosqlite.connect('faction.db') as db:
        cursor = await db.execute(
            'SELECT target_name, SUM(qtd) total FROM farms WHERE week=? GROUP BY target_name ORDER BY total DESC LIMIT ?',
            (week, limit)
        )
        return await cursor.fetchall()

async def create_pvp(name, msg):
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('INSERT INTO pvp (name, msg, participants) VALUES (?,?,\'[]\')',
                        (name, msg))
        await db.commit()
        cursor = await db.execute('SELECT seq FROM sqlite_sequence WHERE name="pvp"')
        return (await cursor.fetchone())[0]

async def toggle_pvp(event_id, user_id):
    async with aiosqlite.connect('faction.db') as db:
        cursor = await db.execute('SELECT participants FROM pvp WHERE id=?', (event_id,))
        parts = json.loads((await cursor.fetchone())[0])
        if user_id in parts:
            parts.remove(user_id)
        else:
            parts.append(user_id)
        await db.execute('UPDATE pvp SET participants=? WHERE id=?', (json.dumps(parts), event_id))
        await db.commit()
