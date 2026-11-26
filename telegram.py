import os
import time
import requests
import threading

from bybit_helpers import *

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

shutdown_requested = threading.Event()
telegram_thread = None


def send(message, chat_id=None):
    try:
        url = f"{BASE_URL}/sendMessage"

        response = requests.post(url,
                                 json={
                                     "chat_id": chat_id or TELEGRAM_CHAT_ID,
                                     "text": message
                                 },
                                 timeout=(3, 5))

        response.raise_for_status()
        return response.json().get("ok", False)

    except requests.exceptions.RequestException as e:
        print(f"Telegram send error: {e}")
        return False


def handle_message(bybit_session, message, chat_id):
    command = message.strip().split()[0].lower().split("@")[0]

    if command == "/summary":
        summary = get_live_summary(bybit_session)
        send(f"Your account summary:\n\n{summary}", chat_id)

    elif command == "/positions":
        positions = get_live_positions(bybit_session)
        send(f"Your positions:\n\n{positions}", chat_id)

    elif command == "/help":
        help_message = ("Available commands:\n\n"
                        "/summary - Get a live account summary\n"
                        "/positions - Get details of your open positions\n")

        send(help_message, chat_id)

    else:
        send("Unknown command. Type /help to see available commands.", chat_id)


def register_commands():
    commands = [{
        "command": "summary",
        "description": "Summary of your account"
    }, {
        "command": "positions",
        "description": "Status of your positions"
    }]

    try:
        response = requests.post(f"{BASE_URL}/setMyCommands",
                                 json={"commands": commands},
                                 timeout=(3, 5))

        response.raise_for_status()

    except requests.exceptions.RequestException as e:
        print(f"Command registration error: {e}")


def start(bybit_session):
    global telegram_thread
    shutdown_requested.clear()

    telegram_thread = threading.Thread(target=telegram_server,
                                       args=(bybit_session, ),
                                       name="TelegramServer",
                                       daemon=True)
    telegram_thread.start()
    print("Telegram server started")


def telegram_server(bybit_session):
    offset = None
    register_commands()
    while not shutdown_requested.is_set():
        try:
            response = requests.get(f"{BASE_URL}/getUpdates",
                                    params={
                                        "offset": offset,
                                        "timeout": 5
                                    },
                                    timeout=(3, 8))

            response.raise_for_status()
            updates = response.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                text = message.get("text")
                chat_id = message.get("chat", {}).get("id")

                if text and chat_id and text.startswith("/"):
                    handle_message(bybit_session, text, chat_id)

        except requests.exceptions.RequestException as e:
            print(f"Telegram polling error: {e}")
            time.sleep(2)


def stop():
    global telegram_thread
    shutdown_requested.set()
    telegram_thread.join(timeout=10)
    print("Telegram server successfully shutdown")
    telegram_thread = None
