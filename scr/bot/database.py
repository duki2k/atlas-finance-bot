import aiosqlite
from datetime import datetime

async def init_db():
    async with aiosqlite.connect('faction_farms.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS farms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                week_num INTEGER,
                tipo TEXT,
                quantidade REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()

async def add_farm(user_id: int, username: str, tipo: str, quantidade: float):
    week_num = datetime.now().isocalendar()[1]
    async with aiosqlite.connect('faction_farms.db') as db:
        await db.execute(
            'INSERT INTO farms (user_id, username, week_num, tipo, quantidade) VALUES (?, ?, ?, ?, ?)',
            (user_id, username, week_num, tipo, quantidade)
        )
        await db.commit()

async def get_weekly_top(limit: int = 5):
    week_num = datetime.now().isocalendar()[1]
    async with aiosqlite.connect('faction_farms.db') as db:
        async with db.execute(
            'SELECT user_id, username, SUM(quantidade) as total FROM farms WHERE week_num = ? GROUP BY user_id ORDER BY total DESC LIMIT ?',
            (week_num, limit)
        ) as cursor:
            return await cursor.fetchall()

async def get_user_farms(user_id: int):
    week_num = datetime.now().isocalendar()[1]
    async with aiosqlite.connect('faction_farms.db') as db:
        async with db.execute(
            'SELECT tipo, SUM(quantidade) as total FROM farms WHERE user_id = ? AND week_num = ? GROUP BY tipo',
            (user_id, week_num)
        ) as cursor:
            return await cursor.fetchall()

async def reset_week():
    week_num = datetime.now().isocalendar()[1] - 5  # Keep 4 weeks
    async with aiosqlite.connect('faction_farms.db') as db:
        await db.execute('DELETE FROM farms WHERE week_num < ?', (week_num,))
        await db.commit()
