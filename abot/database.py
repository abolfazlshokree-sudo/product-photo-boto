# ============================================================
# دیتابیس مشترک بین ربات و مینی‌اپ (SQLite + aiosqlite)
# ============================================================
import aiosqlite
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "data.db"


# ============================================================
# ایجاد جداول
# ============================================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                description TEXT,
                style TEXT,
                custom_prompt TEXT,
                text_length TEXT DEFAULT 'medium',
                hashtags TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                kind TEXT NOT NULL,
                style TEXT,
                custom_prompt TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(product_id) REFERENCES products(id)
            )
        """)

        # 🆕 اگر دیتابیس قدیمی بود، ستون‌های جدید رو اضافه کن
        for col_sql in [
            "ALTER TABLE products ADD COLUMN text_length TEXT DEFAULT 'medium'",
            "ALTER TABLE products ADD COLUMN hashtags TEXT",
        ]:
            try:
                await db.execute(col_sql)
            except Exception:
                pass

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_products_user ON products(user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_product ON images(product_id)"
        )
        await db.commit()


# ============================================================
# ساخت / گرفتن محصول
# ============================================================
async def create_product(user_id: int, product_name: str,
                         custom_prompt: str = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO products
               (user_id, product_name, custom_prompt, created_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, product_name, custom_prompt,
             datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def get_or_create_product(user_id: int, product_name: str,
                                custom_prompt: str = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """SELECT id FROM products
               WHERE user_id=? AND product_name=?
               ORDER BY id DESC LIMIT 1""",
            (user_id, product_name),
        )
        row = await cur.fetchone()
        if row:
            return row[0]
    return await create_product(user_id, product_name, custom_prompt)


# ============================================================
# افزودن عکس
# ============================================================
async def add_image(product_id: int, user_id: int, file_path: str,
                    kind: str, style: str = None,
                    custom_prompt: str = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO images
               (product_id, user_id, file_path, kind, style,
                custom_prompt, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (product_id, user_id, file_path, kind, style, custom_prompt,
             datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


# ============================================================
# به‌روزرسانی
# ============================================================
async def set_description(product_id: int, description: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE products SET description=? WHERE id=?",
            (description, product_id),
        )
        await db.commit()


async def set_style(product_id: int, style: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE products SET style=? WHERE id=?",
            (style, product_id),
        )
        await db.commit()


async def set_text_length(product_id: int, length: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "ALTER TABLE products ADD COLUMN text_length TEXT DEFAULT 'medium'"
            )
        except Exception:
            pass
        await db.execute(
            "UPDATE products SET text_length=? WHERE id=?",
            (length, product_id),
        )
        await db.commit()


async def set_hashtags(product_id: int, hashtags: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "ALTER TABLE products ADD COLUMN hashtags TEXT"
            )
        except Exception:
            pass
        await db.execute(
            "UPDATE products SET hashtags=? WHERE id=?",
            (hashtags, product_id),
        )
        await db.commit()


# ============================================================
# خواندن
# ============================================================
async def list_products(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM products WHERE user_id=? ORDER BY id DESC",
            (user_id,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_product(product_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM products WHERE id=?", (product_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_images(product_id: int, kind: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if kind:
            cur = await db.execute(
                "SELECT * FROM images WHERE product_id=? AND kind=? ORDER BY id",
                (product_id, kind),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM images WHERE product_id=? ORDER BY id",
                (product_id,),
            )
        return [dict(r) for r in await cur.fetchall()]


# ============================================================
# پنل ادمین
# ============================================================
async def list_all_requests(limit: int = 200, offset: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT * FROM products
               ORDER BY id DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        products = [dict(r) for r in await cur.fetchall()]

        for p in products:
            p["originals"] = await get_images(p["id"], kind="original")
            p["generated"] = await get_images(p["id"], kind="generated")

        return products


async def get_admin_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM products")
        total_products = (await cur.fetchone())[0]

        cur = await db.execute("SELECT COUNT(DISTINCT user_id) FROM products")
        total_users = (await cur.fetchone())[0]

        cur = await db.execute(
            "SELECT COUNT(*) FROM images WHERE kind='generated'"
        )
        total_generated = (await cur.fetchone())[0]

        return {
            "total_products": total_products,
            "total_users": total_users,
            "total_generated": total_generated,
        }