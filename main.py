import os
import queue
import time
import server
import telegram

from bybit_helpers import *

from trade_bot import TradeBot
from dotenv import load_dotenv
from pybit.unified_trading import HTTP

load_dotenv()


def connect_bybit(testnet=False):
    api_key = os.getenv("API_KEY")
    secret_key = os.getenv("SECRET_KEY")

    if not api_key or not secret_key:
        raise ValueError("Bybit API credentials not found, please check...")
    else:
        print("Bybit API credentials found!")

    session = HTTP(testnet=testnet,
                   api_key=api_key,
                   api_secret=secret_key,
                   recv_window=5000)

    try:
        response = session.get_wallet_balance(accountType="UNIFIED")
        if response["retCode"] != 0:
            raise RuntimeError(f"Bybit authentication failed: {response}")
        print("Successfully connected to Bybit!")

        return session

    except Exception as e:
        raise RuntimeError(f"Failed to connect to Bybit: {e}") from e


def main():

    ngrok_process = None
    bot = None

    try:
        server.start_webhook()
        ngrok_process = server.start_ngrok()
        server.start_heartbeat(ngrok_process)

        session = connect_bybit(testnet=False)

        telegram.start(session)

        bot = TradeBot(session)
        bot.initialise_tracker()
        bot.initialise_manager()
        bot.run()

        while not server.shutdown_requested.is_set():
            if not server.signal_queue.empty():
                trade = server.signal_queue.get(timeout=5)
                bot.receiver(trade)

    except KeyboardInterrupt:
        print("\nInitiating clean shutdown...")

    finally:
        telegram.stop()
        server.stop_heartbeat()
        server.stop_webhook()
        server.stop_ngrok(ngrok_process)
        bot.shutdown()


if __name__ == "__main__":
    main()
