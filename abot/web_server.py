# ============================================================
# سرور FastAPI برای سرو مینی‌اپ و API
# ============================================================
import hmac
import hashlib
import json
import uuid
import shutil
import asyncio
from pathlib import Path
from urllib.parse import parse_qsl
from typing import Dict
from io import BytesIO

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
    HTTPException,
    Header,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    FileResponse,
    Response,
    JSONResponse,
)
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

import database as db
from config import TELEGRAM_TOKEN, ADMIN_IDS

app = FastAPI(title="Product Content Mini App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

UPLOAD_TMP = Path(__file__).parent / "uploads_tmp"
UPLOAD_TMP.mkdir(exist_ok=True)
JOBS: Dict[str, dict] = {}

# ============================================================
# پوشه cache برای تصاویر کوچک
# ============================================================
THUMBS_DIR = Path(__file__).parent / "thumbs"
THUMBS_DIR.mkdir(exist_ok=True)

THUMB_SIZE = 300
THUMB_QUALITY = 70


# ============================================================
# احراز هویت initData
# ============================================================
def validate_init_data(init_data: str):
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        hash_received = parsed.pop("hash", None)
        if not hash_received:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )
        secret_key = hmac.new(
            b"WebAppData", TELEGRAM_TOKEN.encode(), hashlib.sha256
        ).digest()
        calculated = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if calculated != hash_received:
            return None

        if "user" in parsed:
            parsed["user"] = json.loads(parsed["user"])
        return parsed
    except Exception:
        return None


def get_user(x_init_data: str = Header(...)) -> dict:
    data = validate_init_data(x_init_data)
    if not data or "user" not in data:
        raise HTTPException(401, "Invalid initData")
    return data["user"]


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ============================================================
# سرو کردن فایل‌ها
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse("<h1>Mini App API is running</h1>")


@app.get("/files/{path:path}")
async def serve_file(path: str):
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).parent / path
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(p)


# ============================================================
# 🆕 سرو thumbnail (سبک و سریع)
# ============================================================
@app.get("/thumb/{path:path}")
async def serve_thumb(path: str, size: int = 300):
    """
    اگر thumbnail موجود بود، مستقیم برمی‌گردونه.
    وگرنه می‌سازه، cache می‌کنه و برمی‌گردونه.
    """
    original = Path(path)
    if not original.is_absolute():
        original = Path(__file__).parent / path

    if not original.exists() or not original.is_file():
        raise HTTPException(404, "Not found")

    try:
        mtime = int(original.stat().st_mtime)
    except Exception:
        mtime = 0

    safe_name = hashlib.md5(
        f"{path}|{mtime}|{size}".encode()
    ).hexdigest()
    thumb_path = THUMBS_DIR / f"{safe_name}.jpg"

    if thumb_path.exists():
        return FileResponse(
            thumb_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    try:
        img = Image.open(original)
        img = img.convert("RGB")
        img.thumbnail((size, size), Image.LANCZOS)
        img.save(thumb_path, "JPEG", quality=THUMB_QUALITY, optimize=True)

        return FileResponse(
            thumb_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception:
        return FileResponse(original)


# ============================================================
# DEBUG: بررسی initData
# ============================================================
@app.get("/api/debug")
async def api_debug(request: Request):
    headers = dict(request.headers)
    init_data = headers.get("x-init-data", "")
    data = validate_init_data(init_data) if init_data else None

    return {
        "init_data_received": bool(init_data),
        "init_data_length": len(init_data) if init_data else 0,
        "init_data_preview": (init_data[:80] + "...") if init_data else "",
        "validation_ok": data is not None,
        "parsed_user": data.get("user") if data else None,
        "admin_ids": ADMIN_IDS,
        "all_headers_keys": list(headers.keys()),
    }


# ============================================================
# API: اطلاعات کاربر
# ============================================================
@app.get("/api/me")
async def api_me(x_init_data: str = Header(...)):
    user = get_user(x_init_data)
    return {
        "id": user["id"],
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "username": user.get("username", ""),
        "is_admin": is_admin(user["id"]),
    }


# ============================================================
# API: محصولات کاربر
# ============================================================
@app.get("/api/products")
async def api_products(x_init_data: str = Header(...)):
    user = get_user(x_init_data)
    products = await db.list_products(user["id"])
    for p in products:
        p["images"] = await db.get_images(p["id"], kind="generated")
        p["originals"] = await db.get_images(p["id"], kind="original")
    return {"products": products}


# ============================================================
# API: آپلود
# ============================================================
@app.post("/api/upload")
async def api_upload(
    files: list[UploadFile] = File(...),
    style: str = Form(...),
    custom_prompt: str = Form(""),
    text_length: str = Form("medium"),
    generate_hashtags: str = Form("0"),
    x_init_data: str = Header(...),
):
    user = get_user(x_init_data)

    upload_id = uuid.uuid4().hex
    folder = UPLOAD_TMP / upload_id
    folder.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        p = folder / f"{uuid.uuid4().hex}.jpg"
        with open(p, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(str(p))

    JOBS[upload_id] = {
        "user_id": user["id"],
        "files": saved,
        "style": style,
        "custom_prompt": custom_prompt.strip(),
        "text_length": text_length,
        "generate_hashtags": generate_hashtags == "1",
        "status": "uploaded",
        "stage": "آپلود شد",
    }
    return {"upload_id": upload_id}


# ============================================================
# API: شروع پردازش
# ============================================================
@app.post("/api/generate")
async def api_generate(
    upload_id: str = Form(...),
    x_init_data: str = Header(...),
):
    user = get_user(x_init_data)
    job = JOBS.get(upload_id)
    if not job or job["user_id"] != user["id"]:
        raise HTTPException(404, "Upload not found")

    job["status"] = "processing"
    asyncio.create_task(run_generation(upload_id))
    return {"job_id": upload_id}


# ============================================================
# API: وضعیت
# ============================================================
@app.get("/api/status/{job_id}")
async def api_status(job_id: str, x_init_data: str = Header(...)):
    user = get_user(x_init_data)
    job = JOBS.get(job_id)
    if not job or job["user_id"] != user["id"]:
        raise HTTPException(404, "Job not found")
    return {
        "status": job["status"],
        "stage": job.get("stage"),
        "error": job.get("error"),
        "result": job.get("result"),
    }


# ============================================================
# APIهای ادمین
# ============================================================
@app.get("/api/admin/requests")
async def api_admin_requests(
    limit: int = 100,
    offset: int = 0,
    x_init_data: str = Header(...),
):
    user = get_user(x_init_data)
    if not is_admin(user["id"]):
        raise HTTPException(403, "دسترسی فقط برای ادمین")

    products = await db.list_all_requests(limit=limit, offset=offset)
    stats = await db.get_admin_stats()
    return {"products": products, "stats": stats}


@app.get("/api/admin/requests/{product_id}")
async def api_admin_request_detail(
    product_id: int,
    x_init_data: str = Header(...),
):
    user = get_user(x_init_data)
    if not is_admin(user["id"]):
        raise HTTPException(403, "دسترسی فقط برای ادمین")

    product = await db.get_product(product_id)
    if not product:
        raise HTTPException(404, "Not found")

    product["originals"] = await db.get_images(product_id, kind="original")
    product["generated"] = await db.get_images(product_id, kind="generated")
    return product


# ============================================================
# پردازش اصلی
# ============================================================
async def run_generation(job_id: str):
    job = JOBS[job_id]
    try:
        from bot import (
            detect_product,
            generate_image,
            generate_text,
            generate_hashtags,
        )

        BASE_DIR = Path(__file__).parent.resolve()
        first = job["files"][0]
        style = job["style"]
        custom_prompt = job.get("custom_prompt", "")
        text_length = job.get("text_length", "medium")
        want_hashtags = job.get("generate_hashtags", False)

        # ۱) تشخیص محصول
        job["stage"] = "🔍 در حال تشخیص محصول..."
        product_name = await asyncio.to_thread(detect_product, first)

        # ۲) ساخت محصول
        product_id = await db.get_or_create_product(
            job["user_id"], product_name, custom_prompt
        )

        # ۳) ذخیره عکس‌های اصلی
        for f in job["files"]:
            try:
                rel = str(Path(f).resolve().relative_to(BASE_DIR))
            except ValueError:
                rel = str(f)
            await db.add_image(
                product_id, job["user_id"], rel,
                kind="original", custom_prompt=custom_prompt
            )

        # ۴) تولید عکس‌ها
        generated = []
        for i, f in enumerate(job["files"]):
            job["stage"] = f"🎨 در حال تولید عکس {i+1}/{len(job['files'])}..."
            img_path = await asyncio.to_thread(
                generate_image, f, product_name, style, custom_prompt
            )
            try:
                rel = str(Path(img_path).resolve().relative_to(BASE_DIR))
            except ValueError:
                rel = str(img_path)

            await db.add_image(
                product_id, job["user_id"], rel,
                kind="generated", style=style,
                custom_prompt=custom_prompt,
            )
            generated.append({"url": f"/files/{rel}", "path": rel})

        # ۵) تولید متن
        job["stage"] = "✍️ در حال نوشتن متن..."
        description = await asyncio.to_thread(
            generate_text, product_name, first, text_length
        )
        await db.set_description(product_id, description)
        await db.set_style(product_id, style)

        try:
            await db.set_text_length(product_id, text_length)
        except Exception:
            pass

        # ۶) تولید هشتگ
        hashtags = ""
        if want_hashtags:
            job["stage"] = "🏷 در حال تولید هشتگ..."
            hashtags = await asyncio.to_thread(
                generate_hashtags, product_name, first
            )
            try:
                await db.set_hashtags(product_id, hashtags)
            except Exception:
                pass

        job["result"] = {
            "product_id": product_id,
            "product_name": product_name,
            "images": generated,
            "description": description,
            "hashtags": hashtags,
        }
        job["status"] = "done"

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)[:300]


# ============================================================
# اجرای مستقیم
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)