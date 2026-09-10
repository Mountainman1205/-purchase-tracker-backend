import httpx
import re
import os
import base64
import json
from dotenv import load_dotenv
load_dotenv()
from collections import defaultdict
from datetime import datetime, timedelta
 
from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import anthropic
 
import models
import schemas
from database import Base, engine, get_db
from auth import validate_init_data, DEV_USER
 
Base.metadata.create_all(bind=engine)
 
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DEV_MODE = os.getenv("DEV_MODE", "0") == "1"
 
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
 
app = FastAPI(title="Purchase Tracker API")
 
# На проде замените "*" на реальный домен вашего фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
DEFAULT_CATEGORIES = [
    {"name": "Продукты", "icon": "🛒", "color": "#22C55E"},
    {"name": "Транспорт", "icon": "🚕", "color": "#3B82F6"},
    {"name": "Кафе и рестораны", "icon": "🍔", "color": "#F97316"},
    {"name": "Развлечения", "icon": "🎬", "color": "#A855F7"},
    {"name": "Одежда", "icon": "👕", "color": "#EC4899"},
    {"name": "Здоровье", "icon": "💊", "color": "#EF4444"},
    {"name": "Прочее", "icon": "💳", "color": "#6B7280"},
]
 
 
def get_current_user(
    x_telegram_init_data: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.User:
    if DEV_MODE:
        tg_user = DEV_USER
    else:
        if not x_telegram_init_data:
            raise HTTPException(401, "Missing Telegram init data")
        tg_user = validate_init_data(x_telegram_init_data, BOT_TOKEN)
        if tg_user is None:
            raise HTTPException(401, "Invalid Telegram init data")
 
    telegram_id = str(tg_user["id"])
    print(f"[MINI APP] telegram_id = {telegram_id}")
    user = db.query(models.User).filter(models.User.telegram_id == telegram_id).first()
 
    if user is None:
        user = models.User(
            telegram_id=telegram_id,
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
 
        # Создаём дефолтные категории для нового пользователя
        for cat in DEFAULT_CATEGORIES:
            db.add(models.Category(user_id=user.id, **cat))
        db.commit()
 
    return user
 
 
# --------------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------------
@app.get("/api/categories", response_model=list[schemas.CategoryOut])
def list_categories(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(models.Category).filter(models.Category.user_id == user.id).all()
 
 
@app.post("/api/categories", response_model=schemas.CategoryOut)
def create_category(
    payload: schemas.CategoryCreate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cat = models.Category(user_id=user.id, **payload.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat
 
 
@app.delete("/api/categories/{category_id}")
def delete_category(
    category_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cat = db.query(models.Category).filter(
        models.Category.id == category_id, models.Category.user_id == user.id
    ).first()
    if not cat:
        raise HTTPException(404, "Category not found")
    db.delete(cat)
    db.commit()
    return {"ok": True}
 
 
# --------------------------------------------------------------------------
# Purchases
# --------------------------------------------------------------------------
@app.get("/api/purchases", response_model=list[schemas.PurchaseOut])
def list_purchases(
    limit: int = 50,
    category_id: int | None = None,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(models.Purchase).filter(models.Purchase.user_id == user.id)
    if category_id is not None:
        q = q.filter(models.Purchase.category_id == category_id)
    return q.order_by(models.Purchase.date.desc()).limit(limit).all()
 
 
@app.post("/api/purchases", response_model=schemas.PurchaseOut)
def create_purchase(
    payload: schemas.PurchaseCreate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    purchase = models.Purchase(
        user_id=user.id,
        amount=payload.amount,
        category_id=payload.category_id,
        description=payload.description,
        date=payload.date or datetime.utcnow(),
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)
    return purchase
 
 
@app.delete("/api/purchases/{purchase_id}")
def delete_purchase(
    purchase_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    purchase = db.query(models.Purchase).filter(
        models.Purchase.id == purchase_id, models.Purchase.user_id == user.id
    ).first()
    if not purchase:
        raise HTTPException(404, "Purchase not found")
    db.delete(purchase)
    db.commit()
    return {"ok": True}
 
 
# --------------------------------------------------------------------------
# Receipt recognition (shared helper for bot + Mini App)
# --------------------------------------------------------------------------
def analyze_receipt(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    try:
        resp = anthropic_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": (
                        "Извлеки из чека данные и верни ТОЛЬКО валидный JSON без markdown-обёртки, "
                        "в формате: "
                        '{"store": "название магазина или null", "total": число, '
                        '"items": [{"name": "название", "price": число}]}. '
                        "Если total не виден явно — просчитай сумму по items. "
                        'Если это вообще не похоже на чек — верни {"store": null, "total": 0, "items": []}.'
                    )},
                ],
            }],
        )
        text = resp.content[0].text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"[RECEIPT] analyze_receipt error: {e}")
        return {"store": None, "total": 0, "items": []}
 
 
@app.post("/api/purchases/from-receipt", response_model=schemas.PurchaseOut)
async def create_purchase_from_receipt(
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raise HTTPException(503, "Распознавание чеков временно не работает, приносим свои извинения 🙏")
    image_bytes = await file.read()
    data = analyze_receipt(image_bytes, media_type=file.content_type or "image/jpeg")
    if not data.get("total"):
        raise HTTPException(400, "Не удалось распознать чек")
 
    items_text = "\n".join(f"{i['name']}: {i['price']}" for i in data.get("items", []))
    description = (data.get("store") or "Чек") + (f"\n{items_text}" if items_text else "")
 
    purchase = models.Purchase(
        user_id=user.id, amount=data["total"], category_id=None,
        description=description, date=datetime.utcnow(),
    )
    db.add(purchase)
    db.commit()
    db.refresh(purchase)
    return purchase
 
 
# --------------------------------------------------------------------------
# Budgets
# --------------------------------------------------------------------------
def _period_start(period: str) -> datetime:
    now = datetime.utcnow()
    if period == "week":
        return now - timedelta(days=now.weekday())
    # по умолчанию — месяц
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
 
 
@app.get("/api/budgets", response_model=list[schemas.BudgetOut])
def list_budgets(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(models.Budget).filter(models.Budget.user_id == user.id).all()
 
 
@app.post("/api/budgets", response_model=schemas.BudgetOut)
def create_budget(
    payload: schemas.BudgetCreate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    budget = models.Budget(user_id=user.id, **payload.model_dump())
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget
 
 
@app.delete("/api/budgets/{budget_id}")
def delete_budget(
    budget_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    budget = db.query(models.Budget).filter(
        models.Budget.id == budget_id, models.Budget.user_id == user.id
    ).first()
    if not budget:
        raise HTTPException(404, "Budget not found")
    db.delete(budget)
    db.commit()
    return {"ok": True}
 
 
@app.get("/api/budgets/status", response_model=list[schemas.BudgetStatus])
def budgets_status(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    budgets = db.query(models.Budget).filter(models.Budget.user_id == user.id).all()
    result = []
    for b in budgets:
        start = _period_start(b.period)
        q = db.query(models.Purchase).filter(
            models.Purchase.user_id == user.id,
            models.Purchase.date >= start,
        )
        if b.category_id is not None:
            q = q.filter(models.Purchase.category_id == b.category_id)
        spent = sum(p.amount for p in q.all())
        remaining = b.limit_amount - spent
        percent = round((spent / b.limit_amount) * 100, 1) if b.limit_amount > 0 else 0
        result.append(
            schemas.BudgetStatus(
                budget=b, spent=spent, remaining=remaining, percent_used=percent
            )
        )
    return result
 
 
# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------
@app.get("/api/stats/summary", response_model=schemas.StatsSummary)
def stats_summary(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    purchases = db.query(models.Purchase).filter(models.Purchase.user_id == user.id).all()
 
    by_category_map = defaultdict(float)
    cat_info = {}
    by_month_map = defaultdict(float)
 
    now = datetime.utcnow()
    current_month_key = now.strftime("%Y-%m")
    total_all_time = 0.0
    total_current_month = 0.0
 
    for p in purchases:
        total_all_time += p.amount
        month_key = p.date.strftime("%Y-%m")
        by_month_map[month_key] += p.amount
        if month_key == current_month_key:
            total_current_month += p.amount
 
        if p.category:
            key = p.category.id
            cat_info[key] = (p.category.name, p.category.icon, p.category.color)
        else:
            key = None
            cat_info[key] = ("Без категории", "❔", "#9CA3AF")
        by_category_map[key] += p.amount
 
    by_category = [
        schemas.SummaryByCategory(
            category_id=k,
            category_name=cat_info[k][0],
            icon=cat_info[k][1],
            color=cat_info[k][2],
            total=round(v, 2),
        )
        for k, v in sorted(by_category_map.items(), key=lambda x: -x[1])
    ]
 
    by_month = [
        schemas.SummaryByMonth(month=k, total=round(v, 2))
        for k, v in sorted(by_month_map.items())
    ]
 
    return schemas.StatsSummary(
        by_category=by_category,
        by_month=by_month,
        total_all_time=round(total_all_time, 2),
        total_current_month=round(total_current_month, 2),
    )
 
 
@app.get("/api/health")
def health():
    return {"status": "ok"}
 
 
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
 
 
def get_or_create_user_by_telegram_id(
    telegram_id: str, username: str | None, first_name: str | None, db: Session
) -> models.User:
    user = db.query(models.User).filter(models.User.telegram_id == telegram_id).first()
    if user is None:
        user = models.User(telegram_id=telegram_id, username=username, first_name=first_name)
        db.add(user)
        db.commit()
        db.refresh(user)
        for cat in DEFAULT_CATEGORIES:
            db.add(models.Category(user_id=user.id, **cat))
        db.commit()
    return user
 
 
def parse_quick_purchase(text: str, categories: list[models.Category]):
    """Извлекает сумму и категорию из текста вида 'такси 320'."""
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    rest = (text[: match.start()] + text[match.end() :]).strip()
 
    matched_category = None
    for cat in categories:
        if cat.name.lower() in rest.lower():
            matched_category = cat
            rest = re.sub(re.escape(cat.name), "", rest, flags=re.IGNORECASE).strip()
            break
 
    description = rest.strip() or None
    return amount, matched_category, description
 
 
async def send_telegram_message(chat_id: int, text: str):
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendMessage", json={"chat_id": chat_id, "text": text})
 
 
@app.post("/telegram/webhook")
async def telegram_webhook(update: dict, db: Session = Depends(get_db)):
    message = update.get("message")
    if not message:
        return {"ok": True}
 
    chat_id = message["chat"]["id"]
    from_user = message.get("from", {})
    telegram_id = str(from_user.get("id"))
    print(f"[WEBHOOK] telegram_id = {telegram_id}")
    text = message.get("text", "")
 
    user = get_or_create_user_by_telegram_id(
        telegram_id, from_user.get("username"), from_user.get("first_name"), db
    )
 
    if text.startswith("/start"):
        await send_telegram_message(
            chat_id,
            "Привет! Просто напиши сумму и категорию, например: «такси 320» или «продукты 1500», "
            "и я добавлю покупку. Или пришли фото чека — я распознаю его сам.",
        )
        return {"ok": True}
 
    # --- Обработка фото чека (временно отключено) ---
    photos = message.get("photo")
    if photos:
        await send_telegram_message(
            chat_id,
            "Распознавание чеков временно не работает, приносим свои извинения 🙏 "
            "Пока просто напиши сумму и категорию текстом, например: «такси 320».",
        )
        return {"ok": True}
 
    categories = db.query(models.Category).filter(models.Category.user_id == user.id).all()
    parsed = parse_quick_purchase(text, categories)
 
    if parsed is None:
        await send_telegram_message(chat_id, "Не нашёл сумму в сообщении. Напиши, например: «кафе 450», или пришли фото чека.")
        return {"ok": True}
 
    amount, category, description = parsed
    purchase = models.Purchase(
        user_id=user.id,
        amount=amount,
        category_id=category.id if category else None,
        description=description,
        date=datetime.utcnow(),
    )
    db.add(purchase)
    db.commit()
 
    cat_label = category.name if category else "Без категории"
    extra = f" ({description})" if description else ""
    await send_telegram_message(chat_id, f"Добавлено: {amount:.0f} ₽ — {cat_label}{extra}")
    return {"ok": True}
