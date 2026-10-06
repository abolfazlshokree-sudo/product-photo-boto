# ============================================================
# ربات تلگرام تولید محتوای محصول با AvalAI
# نسخه نهایی — مینی‌اپ + پنل ادمین + توضیحات سفارشی
# ============================================================

import os
import asyncio
import base64
import logging
from pathlib import Path
from openai import OpenAI
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from PIL import Image
import requests

import database as db
from config import (
    TELEGRAM_TOKEN,
    AVALAI_API_KEY,
    ADMIN_IDS,
    MINI_APP_URL,
    IMAGE_MODEL,
    VISION_MODEL,
    TEXT_MODEL,
)

# ============================================================
# کلاینت OpenAI (AvalAI)
# ============================================================
client = OpenAI(
    api_key=AVALAI_API_KEY,
    base_url="https://api.avalai.ir/v1",
    timeout=300.0,
    max_retries=3,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ============================================================
# پوشه‌ها
# ============================================================
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
GENERATED_DIR = BASE_DIR / "generated"
DOWNLOAD_DIR.mkdir(exist_ok=True)
GENERATED_DIR.mkdir(exist_ok=True)

# ============================================================
# لاگ
# ============================================================
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# تم عکس حرفه‌ای
# ============================================================
PROFESSIONAL_THEME = (
    "Background: soft neutral gradient backdrop in warm cream and "
    "light beige tones, smooth seamless studio wall, no patterns, "
    "no props, no decorations. "
    "Lighting: consistent three-point studio lighting with a warm key "
    "light and gentle fill light, soft shadow beneath the product. "
    "Composition: minimalist, product centered, generous empty space "
    "around it, same camera angle and same distance in every photo. "
    "Style: premium editorial catalogue, cinematic color grading, "
    "4K, photorealistic."
)


# ============================================================
# کیبوردها
# ============================================================
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ ساخت متن محصول", callback_data="make_text")],
        [InlineKeyboardButton("🎨 استودیو (مینی‌اپ)", web_app=WebAppInfo(url=MINI_APP_URL))],
        [InlineKeyboardButton("🆕 محصول جدید", callback_data="new_product")],
    ])


def style_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 عکس حرفه‌ای", callback_data="style_professional")],
        [InlineKeyboardButton("📰 عکس ژورنالی", callback_data="style_journalistic")],
        [InlineKeyboardButton("🆕 محصول جدید", callback_data="new_product")],
    ])


# ============================================================
# کوچک‌سازی عکس
# ============================================================
def optimize_image(path, max_size=1024):
    img = Image.open(path)
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        img = img.resize(
            (int(img.size[0] * ratio), int(img.size[1] * ratio)),
            Image.LANCZOS,
        )
        img.convert("RGB").save(path, "JPEG", quality=90)


# ============================================================
# لودینگ
# ============================================================
async def show_loading(message, seconds=60, prefix="⏳"):
    frames = ["🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙"]
    steps = 20
    delay = seconds / steps

    loading_msg = await message.reply_text(f"{frames[0]} {prefix} 0%")

    for i in range(1, steps + 1):
        percent = int((i / steps) * 95)
        frame = frames[i % len(frames)]
        bar_filled = "█" * (percent // 5)
        bar_empty = "░" * (20 - percent // 5)
        try:
            await loading_msg.edit_text(
                f"{frame} {prefix} {percent}%\n{bar_filled}{bar_empty}"
            )
        except Exception:
            pass
        await asyncio.sleep(delay)

    return loading_msg


# ============================================================
# تشخیص نام محصول
# ============================================================
def detect_product(image_path):
    logger.info("🔍 در حال تشخیص محصول...")

    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = """این عکس یک محصول است. یک «نام تجاری جذاب و کوتاه فارسی» برایش بساز.

قواعد:
- اگر برند مشخص است: «نوع محصول + برند» (مثال: کوله پشتی کت)
- اگر برند مشخص نیست: «نوع محصول + یک صفت جذاب» (مثال: کوله پشتی چرمی)
- حداکثر ۵ کلمه
- فقط نام نهایی، بدون توضیح، بدون کوتیشن، بدون نقطه

مثال خروجی: کوله پشتی کت"""

    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}"
                        },
                    },
                ],
            }
        ],
        max_tokens=100,
    )

    name = response.choices[0].message.content.strip()
    name = name.strip('"\'«» .،')
    logger.info(f"✅ محصول: {name}")
    return name


# ============================================================
# تولید عکس
# ============================================================
def generate_image(image_path, product_name, style, custom_prompt: str = None):
    if style == "professional":
        theme_part = f"Theme (must apply exactly):\n{PROFESSIONAL_THEME}"
    else:
        theme_part = (
            "Design the scene like a premium international brand advertisement. "
            "Choose the most fitting background, lighting, angle and mood for "
            "this specific product type."
        )

    custom_part = ""
    if custom_prompt and custom_prompt.strip():
        custom_part = (
            f"\n\nUser's custom instructions (HIGH PRIORITY, must follow):\n"
            f"{custom_prompt.strip()}\n"
        )

    prompt = (
        f"Create a professional, flawless, high-end commercial product "
        f"photograph of '{product_name}'.\n\n"
        f"The image must look absolutely perfect, polished and premium — "
        f"like a photo from a luxury brand catalogue or a top fashion magazine. "
        f"If the product has any visible imperfections, correct them to make "
        f"the product look flawless and premium.\n\n"
        f"{theme_part}"
        f"{custom_part}\n\n"
        f"Keep the product itself fully recognizable in shape, color and design."
    )

    logger.info(f"🎨 در حال تولید عکس ({style})...")

    with open(image_path, "rb") as f:
        response = client.images.edit(
            model=IMAGE_MODEL,
            image=f,
            prompt=prompt,
            size="1024x1024",
        )

    item = response.data[0]

    safe = "".join(
        c for c in product_name[:20] if c.isalnum() or c in "-_"
    ) or "product"
    filepath = GENERATED_DIR / f"{style}_{safe}_{os.urandom(4).hex()}.png"

    if getattr(item, "b64_json", None):
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(item.b64_json))
    elif getattr(item, "url", None):
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://api.avalai.ir/",
        }
        r = requests.get(item.url, headers=headers, timeout=60)
        r.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(r.content)
    else:
        raise Exception(f"عکس در پاسخ نبود: {item.model_dump()}")

    logger.info(f"✅ ذخیره شد: {filepath}")
    return str(filepath)


# ============================================================
# تولید متن
# ============================================================
def generate_text(product_name, first_image_path, length="medium"):
    logger.info(f"✍️ در حال نوشتن متن ({length})...")

    length_specs = {
        "short": {
            "words": "۲۰ تا ۳۰ کلمه",
            "structure": (
                "۱. یک تیتر جذاب (حداکثر ۵ کلمه)\n"
                "۲. یک پاراگراف یک‌خطی\n"
                "۳. یک جمله فراخوان به اقدام"
            ),
        },
        "medium": {
            "words": "۵۰ تا ۷۰ کلمه",
            "structure": (
                "۱. تیتر جذاب (حداکثر ۶ کلمه)\n"
                "۲. پاراگراف دو-سه خطی\n"
                "۳. دو ویژگی کلیدی با •\n"
                "۴. فراخوان به اقدام"
            ),
        },
        "long": {
            "words": "۱۰۰ تا ۱۵۰ کلمه",
            "structure": (
                "۱. تیتر جذاب قوی\n"
                "۲. پاراگراف معرفی (۳-۴ خط)\n"
                "۳. سه-چهار ویژگی کلیدی با •\n"
                "۴. پاراگراف حس و تجربه‌ی استفاده\n"
                "۵. فراخوان قوی به اقدام"
            ),
        },
    }
    spec = length_specs.get(length, length_specs["medium"])

    with open(first_image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = (
        f"این عکس محصول «{product_name}» است.\n\n"
        f"یک متن بازاریابی‌محور فارسی با طول «{spec['words']}» بنویس.\n\n"
        f"ساختار:\n{spec['structure']}\n\n"
        f"نکات:\n"
        f"- لحن مدرن و صمیمی\n"
        f"- بدون ایموجی\n"
        f"- فقط متن نهایی، بدون توضیح اضافه"
    )

    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "تو یک کپی‌رایتر حرفه‌ای فارسی هستی "
                    "که متن‌های فروشنده می‌نویسد."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}"
                        },
                    },
                ],
            },
        ],
        max_tokens=800,
    )
    return response.choices[0].message.content.strip()
    
    
    
# ============================================================
# 🆕 تولید هشتگ هوشمند اینستاگرام
# ============================================================
def generate_hashtags(product_name, first_image_path):
    logger.info("🏷 در حال تولید هشتگ...")

    with open(first_image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = (
        f"این عکس محصول «{product_name}» است.\n\n"
        f"۱۵ تا ۲۰ هشتگ هوشمند و مؤثر برای اینستاگرام پیشنهاد بده.\n\n"
        f"قواعد:\n"
        f"- ترکیبی از هشتگ‌های فارسی و انگلیسی\n"
        f"- شامل هشتگ‌های عمومی پرطرفدار + هشتگ‌های تخصصی این دسته‌بندی\n"
        f"- هشتگ‌های مرتبط با سبک زندگی، فروش و ترندهای روز اینستاگرام\n"
        f"- هشتگ‌های فارسی بدون فاصله باشند (مثل #کوله_پشتی یا #کوله_پشتی_چرمی)\n"
        f"- هر هشتگ در یک خط جدید با علامت #\n"
        f"- فقط هشتگ‌ها، بدون هیچ توضیح اضافه\n\n"
        f"مثال خروجی:\n"
        f"#کوله_پشتی\n"
        f"#backpack\n"
        f"#style\n"
        f"#فروش_آنلاین"
    )

    response = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "تو یک متخصص سئو و مارکتینگ اینستاگرام هستی "
                    "که هشتگ‌های مؤثر و پرطرفدار پیشنهاد می‌دهی."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}"
                        },
                    },
                ],
            },
        ],
        max_tokens=500,
    )
    return response.choices[0].message.content.strip()

# ============================================================
# /start
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "سلام! 👋\n\n"
        "من ربات تولید محتوای محصول هستم.\n\n"
        "کافیه «عکس‌های محصول» رو بفرستی. من:\n\n"
        "🔍 محصول رو از روی عکس اول تشخیص می‌دم\n"
        "🎨 بعد از ارسال عکس، ازت می‌پرسم چه سبکی می‌خوای:\n"
        "   📸 عکس حرفه‌ای (استودیو گرم)\n"
        "   📰 عکس ژورنالی (خودکار و متنوع)\n\n"
        "بعد از ارسال همه عکس‌ها،\n"
        "دکمه «✍️ ساخت متن محصول» رو بزن.\n\n"
        "🎨 برای تجربه بهتر، دکمه «استودیو» رو بزن!",
        reply_markup=main_keyboard(),
    )


# ============================================================
# محصول جدید
# ============================================================
async def new_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.message.reply_text(
        "🆕 آماده‌ی محصول جدید!\n\nعکس اول محصول بعدی رو بفرست.",
        reply_markup=main_keyboard(),
    )


# ============================================================
# انتخاب سبک
# ============================================================
async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "style_professional":
        style = "professional"
        style_name = "📸 عکس حرفه‌ای"
    else:
        style = "journalistic"
        style_name = "📰 عکس ژورنالی"

    context.user_data["style"] = style

    product_name = context.user_data.get("product_name")
    product_id = context.user_data.get("product_id")
    pending = context.user_data.get("pending_image")

    if not product_name or not pending or not os.path.exists(pending):
        await query.message.reply_text(
            "⚠️ عکسی برای پردازش پیدا نشد.\n"
            "لطفاً دوباره عکس بفرست.",
            reply_markup=main_keyboard(),
        )
        return

    await query.message.reply_text(
        f"✅ سبک انتخابی: {style_name}\n\n"
        f"🎨 در حال ساخت عکس «{product_name}»..."
    )

    loading_msg = await show_loading(
        query.message, seconds=60, prefix=f"🎨 در حال ساخت {style_name}"
    )

    try:
        img_path = generate_image(pending, product_name, style)

        # ذخیره در دیتابیس
        if product_id:
            await db.add_image(
                product_id,
                query.from_user.id,
                img_path,
                kind="generated",
                style=style,
            )

        try:
            await loading_msg.edit_text("✅ عکس آماده شد! 100%")
        except Exception:
            pass

        with open(img_path, "rb") as img:
            await query.message.reply_photo(
                photo=img,
                caption=f"📸 عکس «{product_name}» با سبک {style_name}",
                reply_markup=main_keyboard(),
            )

        context.user_data.pop("pending_image", None)

        await query.message.reply_text(
            "📸 می‌تونی عکس‌های بعدی رو بفرستی "
            "(همه با همین سبک ساخته می‌شن)\n"
            "✍️ یا اگه تموم شد، دکمه «ساخت متن محصول» رو بزن.",
            reply_markup=main_keyboard(),
        )

    except Exception as e:
        logger.error(f"خطا در تولید عکس: {e}", exc_info=True)
        try:
            await loading_msg.edit_text(f"❌ خطا: {str(e)[:150]}")
        except Exception:
            pass


# ============================================================
# ساخت متن
# ============================================================
async def make_text_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_name = context.user_data.get("product_name")
    first_image = context.user_data.get("first_image")
    product_id = context.user_data.get("product_id")

    if not product_name:
        await query.message.reply_text(
            "⚠️ هنوز محصولی ثبت نشده.", reply_markup=main_keyboard()
        )
        return

    if not first_image or not os.path.exists(first_image):
        await query.message.reply_text(
            "⚠️ عکس اول پیدا نشد.", reply_markup=main_keyboard()
        )
        return

    if context.user_data.get("description"):
        await query.message.reply_text(
            "ℹ️ متن این محصول قبلاً ساخته شده.",
            reply_markup=main_keyboard(),
        )
        return

    loading_msg = await show_loading(
        query.message, seconds=25, prefix="✍️ در حال نوشتن متن"
    )

    try:
        description = generate_text(product_name, first_image)
        context.user_data["description"] = description

        if product_id:
            await db.set_description(product_id, description)

        try:
            await loading_msg.edit_text("✅ متن آماده شد! 100%")
        except Exception:
            pass

        for i in range(0, len(description), 4000):
            await query.message.reply_text(
                description[i: i + 4000], reply_markup=main_keyboard()
            )

    except Exception as e:
        logger.error(f"خطا در تولید متن: {e}", exc_info=True)
        try:
            await loading_msg.edit_text(f"❌ خطا: {str(e)[:100]}")
        except Exception:
            pass


# ============================================================
# دریافت متن غیرعکس
# ============================================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 فقط عکس بفرست!", reply_markup=main_keyboard()
    )


# ============================================================
# دریافت عکس
# ============================================================
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    user_dir = DOWNLOAD_DIR / str(user.id)
    user_dir.mkdir(exist_ok=True)
    image_path = user_dir / f"{photo.file_id}.jpg"
    await file.download_to_drive(str(image_path))

    try:
        optimize_image(str(image_path))
    except Exception as e:
        logger.warning(f"بهینه‌سازی ناموفق: {e}")

    # ============ عکس اول ============
    if "product_name" not in context.user_data:
        loading_msg = await show_loading(
            update.message, seconds=15, prefix="🔍 در حال تشخیص محصول"
        )

        try:
            product_name = detect_product(str(image_path))
        except Exception as e:
            logger.error(f"خطا در تشخیص محصول: {e}", exc_info=True)
            try:
                await loading_msg.edit_text(
                    f"❌ خطا در تشخیص محصول: {str(e)[:150]}"
                )
            except Exception:
                pass
            return

        context.user_data["product_name"] = product_name
        context.user_data["first_image"] = str(image_path)
        context.user_data["pending_image"] = str(image_path)

        # ذخیره در دیتابیس
        try:
            product_id = await db.get_or_create_product(user.id, product_name)
            context.user_data["product_id"] = product_id
            await db.add_image(
                product_id, user.id, str(image_path), kind="original"
            )
        except Exception as e:
            logger.error(f"خطای دیتابیس: {e}", exc_info=True)

        try:
            await loading_msg.edit_text(f"✅ محصول: «{product_name}» 100%")
        except Exception:
            pass

        await update.message.reply_text(
            f"🎯 محصول: «{product_name}»\n\n"
            f"حالا سبک عکس رو انتخاب کن:\n\n"
            f"📸 عکس حرفه‌ای: استودیو با پس‌زمینه گرم کرم/بژ، "
            f"نورپردازی سه‌نقطه، مناسب کاتالوگ رسمی\n\n"
            f"📰 عکس ژورنالی: سبک متنوع و خلاقانه، "
            f"تم بر اساس نوع محصول (مثل برندهای بین‌المللی)",
            reply_markup=style_keyboard(),
        )
        return

    # ============ سبک انتخاب نشده ============
    style = context.user_data.get("style")
    if not style:
        await update.message.reply_text(
            "⚠️ لطفاً اول سبک عکس رو انتخاب کن.",
            reply_markup=style_keyboard(),
        )
        return

    # ============ عکس‌های بعدی ============
    product_name = context.user_data["product_name"]
    product_id = context.user_data.get("product_id")
    style_name = (
        "📸 عکس حرفه‌ای" if style == "professional" else "📰 عکس ژورنالی"
    )

    loading_msg = await show_loading(
        update.message,
        seconds=60,
        prefix=f"🎨 در حال ساخت عکس «{product_name}»",
    )

    try:
        img_path = generate_image(str(image_path), product_name, style)

        # ذخیره در دیتابیس
        if product_id:
            await db.add_image(
                product_id, user.id, img_path,
                kind="generated", style=style,
            )

        try:
            await loading_msg.edit_text("✅ عکس آماده شد! 100%")
        except Exception:
            pass

        with open(img_path, "rb") as img:
            await update.message.reply_photo(
                photo=img,
                caption=f"📸 عکس «{product_name}» با سبک {style_name}",
                reply_markup=main_keyboard(),
            )

        await update.message.reply_text(
            "📸 عکس بعدی رو بفرست یا دکمه «ساخت متن محصول» رو بزن.",
            reply_markup=main_keyboard(),
        )

    except Exception as e:
        logger.error(f"خطا در پردازش عکس: {e}", exc_info=True)
        try:
            await loading_msg.edit_text(f"❌ خطا: {str(e)[:150]}")
        except Exception:
            pass


# ============================================================
# تابع اصلی
# ============================================================
def main():
    # راه‌اندازی دیتابیس
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(db.init_db())

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        CallbackQueryHandler(new_product_callback, pattern="^new_product$")
    )
    app.add_handler(CallbackQueryHandler(style_callback, pattern="^style_"))
    app.add_handler(
        CallbackQueryHandler(make_text_callback, pattern="^make_text$")
    )
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    logger.info("🤖 ربات روشن شد...")
    print("\n" + "=" * 50)
    print("🤖 ربات با موفقیت روشن شد!")
    print("=" * 50 + "\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()