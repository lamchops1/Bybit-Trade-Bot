import os
import threading
import requests
import time
import subprocess

from queue import Queue
from flask import Flask, request, jsonify
from werkzeug.serving import make_server
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

signal_queue = Queue()

webhook_server = None
webhook_thread = None
heartbeat_thread = None

heartbeat_stop = threading.Event()
heartbeat_ready = threading.Event()
shutdown_requested = threading.Event()

is_online = False


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if data.get("secret") != os.getenv("WEBHOOK_KEY"):
        return jsonify({"error": "Unauthorized"}), 401

    side = data.get("action")
    signal = data.get("signal")
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    trendline = data.get("trendline")
    support = data.get("support")
    resistance = data.get("resistance")
    bar_time = data.get("bar_time")

    print("\n")
    print("Received TradingView Alert!")
    print("side:", side)
    print("Signal:", signal)
    print("Symbol:", symbol)
    print("Timeframe:", timeframe)
    print("Trendline:", trendline)
    print("Support:", support)
    print("Resistance:", resistance)
    print("Bar Time:", bar_time)
    print("\n\n")

    trade_signal = {
        "side": side,
        "signal": signal,
        "symbol": symbol,
        "timeframe": timeframe,
        "trendline": trendline,
        "support": support,
        "resistance": resistance,
        "bar_time": bar_time
    }

    signal_queue.put(trade_signal)

    return jsonify({"status": "received"}), 200


def start_webhook():

    global webhook_server, webhook_thread

    webhook_server = make_server("0.0.0.0", 5000, app, threaded=True)
    webhook_thread = threading.Thread(target=webhook_server.serve_forever,
                                      daemon=False)

    webhook_thread.start()
    print("Webhook server started")
    return webhook_thread


def stop_webhook():

    global webhook_server, webhook_thread

    if webhook_server:
        webhook_server.shutdown()
        webhook_server.server_close()

    if webhook_thread and webhook_thread.is_alive():
        webhook_thread.join(timeout=10)

    if webhook_thread and webhook_thread.is_alive():
        print("WARNING: Webhook thread did not stop within 10 seconds")
    else:
        print("Webhook server successfully shutdown.")

    webhook_server = None
    webhook_thread = None


def start_ngrok():
    ngrok_process = subprocess.Popen([
        "ngrok", "http", "5000",
        "--url=https://constrict-aide-stem.ngrok-free.dev"
    ],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
    print("ngrok started")
    return ngrok_process


def stop_ngrok(process):
    if process is None:
        print("ngrok process not found.")
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        print("ngrok successfully shutdown.")
    else:
        print(f"ngrok is currently not polled, succesfully shutdown.")


def start_heartbeat(ngrok_process):
    global heartbeat_thread
    heartbeat_stop.clear()
    heartbeat_ready.clear()
    shutdown_requested.clear()

    heartbeat_thread = threading.Thread(target=heartbeat_check,
                                        args=(ngrok_process, ),
                                        daemon=True)
    heartbeat_thread.start()

    while not heartbeat_ready.wait(timeout=1):
        if shutdown_requested.is_set():
            print("Failed to establish server connection.")
            return False

    while not is_online:
        if shutdown_requested.is_set():
            print("Failed to establish server connection.")
            return False
        heartbeat_stop.wait(1)

    print("Server is online. Starting TradeBot!")
    return True


def heartbeat_check(ngrok_process):

    reconnect_attempt = 0
    global is_online

    while not heartbeat_stop.is_set() and reconnect_attempt < 10:
        try:
            response = requests.get("http://127.0.0.1:5000/health", timeout=5)
            webhook_online = response.status_code == 200
        except requests.RequestException:
            webhook_online = False
            print("Webhook server closed, shutting down TradeBot")

        try:
            response = requests.get(
                "https://constrict-aide-stem.ngrok-free.dev/health", timeout=5)
            ngrok_online = response.status_code == 200
        except requests.RequestException:
            ngrok_online = False
            print("ngrok went offline, shutting down TradeBot")

        is_online = (webhook_online and ngrok_online
                     and ngrok_process.poll() is None)

        heartbeat_ready.set()

        if is_online:
            print("Server online.\n")
            reconnect_attempt = 0
        else:
            print("Server connection unavailable. Retrying...\n")
            reconnect_attempt += 1

        if reconnect_attempt >= 10:
            shutdown_requested.set()

        heartbeat_stop.wait(10)


def stop_heartbeat():
    global is_online

    heartbeat_stop.set()
    is_online = False

    if heartbeat_thread and heartbeat_thread.is_alive():
        heartbeat_thread.join(timeout=10)
        print("Heartbeat successfully shutdown.")


# $body = @{
#     secret = "kXq57B4fN7kpYYNcfwMaqEEaBUSX6HteeCXpxbOL5QM"
#     action = "Buy"
#     signal = "TREND_UP"
#     symbol = "ETHUSDT"
#     timeframe = "15"
#     trendline = 1663.61
#     support = 1664.79
#     resistance =1713.33
#     bar_time = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
# } | ConvertTo-Json

# Invoke-RestMethod `
#     -Uri "https://constrict-aide-stem.ngrok-free.dev/webhook" `
#     -Method POST `
#     -ContentType "application/json" `
#     -Body $body

# $body = @{
#     secret = "kXq57B4fN7kpYYNcfwMaqEEaBUSX6HteeCXpxbOL5QM"
#     action = "Sell"
#     signal = "TREND_DOWN"
#     symbol = "ETHUSDT"
#     timeframe = "15"
#     trendline = 1728.00
#     support = 1664.79
#     resistance =1713.54
#     bar_time = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
# } | ConvertTo-Json

# Invoke-RestMethod `
#     -Uri "https://constrict-aide-stem.ngrok-free.dev/webhook" `
#     -Method POST `
#     -ContentType "application/json" `
#     -Body $body
