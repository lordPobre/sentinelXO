"""
Sentinel XO — Notificaciones por Telegram
Bot único de Sentinel XO (SENTINEL_TELEGRAM_BOT_TOKEN), un chat_id por cliente.
"""
import logging
import requests

logger = logging.getLogger("sentinel.telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_message(chat_id: str, text: str) -> tuple[bool, str]:
    """
    Envía un mensaje de texto a un chat de Telegram vía el bot de Sentinel XO.
    Retorna (success, error_msg).
    """
    from django.conf import settings

    bot_token = getattr(settings, "SENTINEL_TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        return False, "SENTINEL_TELEGRAM_BOT_TOKEN no configurado"
    if not chat_id:
        return False, "chat_id vacío"

    url = TELEGRAM_API.format(token=bot_token)
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        if resp.status_code == 200 and resp.json().get("ok"):
            return True, ""
        body = resp.text[:300]
        logger.warning(f"Telegram sendMessage falló ({resp.status_code}): {body}")
        return False, body
    except Exception as e:
        logger.error(f"Error enviando mensaje Telegram: {e}")
        return False, str(e)


def notify_telegram(client, text: str) -> bool:
    """
    Envía una notificación por Telegram al chat configurado del cliente, si existe.
    No falla silenciosamente — registra el resultado en logs.
    Retorna True si se envió correctamente (o si no estaba configurado, sin error).
    """
    chat_id = (getattr(client, "telegram_chat_id", "") or "").strip()
    if not chat_id:
        return True  # no configurado — no es un error

    success, error = send_telegram_message(chat_id, text)
    if success:
        logger.info(f"Telegram enviado a {client.company_name} (chat {chat_id})")
    else:
        logger.error(f"Error enviando Telegram a {client.company_name}: {error}")
    return success


def send_telegram_test(client) -> tuple[bool, str]:
    """Envía un mensaje de prueba al chat configurado del cliente. Para botón 'Probar'."""
    from django.conf import settings
    from django.utils import timezone

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    chat_id = (getattr(client, "telegram_chat_id", "") or "").strip()

    if not getattr(settings, "SENTINEL_TELEGRAM_BOT_TOKEN", ""):
        return False, "SENTINEL_TELEGRAM_BOT_TOKEN no está configurado en el servidor"
    if not chat_id:
        return False, "Este cliente no tiene un Chat ID de Telegram configurado"

    now = timezone.localtime(timezone.now())
    text = (
        f"✅ <b>{company}</b>\n\n"
        f"Mensaje de prueba para <b>{client.company_name}</b>.\n"
        f"Si ves esto, las alertas críticas por Telegram están configuradas correctamente.\n\n"
        f"<i>{now.strftime('%d/%m/%Y %H:%M')}</i>"
    )
    return send_telegram_message(chat_id, text)
