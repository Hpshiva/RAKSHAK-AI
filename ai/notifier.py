import os
import requests
import threading
from datetime import datetime

# Environment Config for Alert Dispatch
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
WEBHOOK_ALERT_URL = os.getenv("WEBHOOK_ALERT_URL", "")

def _send_telegram(message: str, image_path: str = None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        if image_path and os.path.exists(image_path):
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            with open(image_path, 'rb') as photo:
                requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": message}, files={"photo": photo}, timeout=5)
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
    except Exception as e:
        print(f"[Notifier Error] Telegram dispatch failed: {e}")

def _send_webhook(payload: dict):
    if not WEBHOOK_ALERT_URL:
        return
    try:
        requests.post(WEBHOOK_ALERT_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[Notifier Error] Webhook dispatch failed: {e}")

def send_alert_notification(label: str, confidence: float, severity: str, camera: str, snapshot_path: str = None):
    """Dispatches asynchronous alert notifications via Telegram / Webhooks."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = (
        f"🚨 RAKSHAK AI ALERT DETECTED 🚨\n\n"
        f"• Severity: {severity}\n"
        f"• Threat/Label: {label}\n"
        f"• Confidence: {confidence:.1f}%\n"
        f"• Camera: {camera}\n"
        f"• Time: {timestamp}"
    )
    payload = {
        "event": "RAKSHAK_ALERT",
        "severity": severity,
        "label": label,
        "confidence": confidence,
        "camera": camera,
        "timestamp": timestamp,
        "snapshot_path": snapshot_path
    }

    # Dispatch asynchronously in background thread to not block video streaming
    threading.Thread(target=_send_telegram, args=(message, snapshot_path), daemon=True).start()
    threading.Thread(target=_send_webhook, args=(payload,), daemon=True).start()
