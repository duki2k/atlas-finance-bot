import aiosqlite
from datetime import datetime

async def init_db():
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS farms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                week_num INTEGER,
                quantidade REAL,
                tipo TEXT DEFAULT 'un',
                added_by INTEGER,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                description TEXT,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                participants TEXT DEFAULT '[]'  -- JSON list user_ids
            )
        ''')
        await db.commit()

async def add_farm_admin(user_id: int, username: str, quantidade: float, added_by: int, tipo='un'):
    week_num = datetime.now().isocalendar()[1]
    async with aiosqlite.connect('faction.db') as db:
        await db.execute(
            'INSERT INTO farms (user_id, username, week_num, quantidade, tipo, added_by) VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, username, week_num, quantidade, tipo, added_by)
        )
        await db.commit()

async def get_monthly_report(admin_id: int):
    async with aiosqlite.connect('faction.db') as db:
        async with db.execute(
            'SELECT username, SUM(quantidade) as total, COUNT(*) as adds, MAX(added_at) FROM farms WHERE added_by = ? GROUP BY username ORDER BY total DESC',
            (admin_id,)
        ) as cursor:
            return await cursor.fetchall()

async def get_weekly_top():
    week_num = datetime.now().isocalendar()[1]
    async with aiosqlite.connect('faction.db') as db:
        async with db.execute(
            'SELECT user_id, username, SUM(quantidade) as total FROM farms WHERE week_num = ? GROUP BY user_id ORDER BY total DESC LIMIT 10',
            (week_num,)
        ) as cursor:
            return await cursor.fetchall()

async def reset_week():
    week_num = datetime.now().isocalendar()[1] - 5
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('DELETE FROM farms WHERE week_num < ?', (week_num,))
        await db.commit()

async def create_event(title: str, description: str, created_by: int):
    async with aiosqlite.connect('faction.db') as db:
        await db.execute('INSERT INTO events (title, description, created_by) VALUES (?, ?, ?)', (title, description, created_by))
        await db.commit()
        cursor = await db.execute('SELECT last_insert_rowid()')
        return (await cursor.fetchone())[0]

async def get_event_participants(event_id: int):
    async with aiosqlite.connect('faction.db') as db:
        async with db.execute('SELECT participants FROM events WHERE id = ?', (event_id,)) as cursor:
            row = await cursor.fetchone()
            return eval(row[0]) if row else []
