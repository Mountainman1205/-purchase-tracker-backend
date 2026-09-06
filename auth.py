"""
Проверка подлинности данных, которые Telegram Mini App передаёт при открытии.

Telegram подписывает данные о пользователе (initData) хэшем на основе токена
бота. Бэкенд обязан проверять эту подпись — иначе кто угодно сможет прислать
запрос от имени чужого telegram_id.

Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> dict | None:
    """
    Возвращает словарь с данными пользователя, если подпись верна и данные
    не устарели. Иначе — None.
    """
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    # Строка для проверки: все поля, кроме hash, отсортированы по ключу
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date = int(parsed.get("auth_date", 0))
    if time.time() - auth_date > max_age_seconds:
        return None

    user_raw = parsed.get("user")
    if not user_raw:
        return None

    return json.loads(user_raw)


# ---------------------------------------------------------------------------
# Режим для локальной разработки без реального Telegram-клиента.
# Если переменная окружения DEV_MODE=1, initData не проверяется, а вместо
# этого используется фиктивный пользователь. Никогда не включайте это в
# продакшене.
# ---------------------------------------------------------------------------
DEV_USER = {"id": "000000", "username": "dev_user", "first_name": "Dev"}
