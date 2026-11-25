from bybit_helpers import *
from algo_helpers import *
from telegram import *

from enum import Enum, auto

import threading
import queue
import time


class State(Enum):
    MONITORING = auto()
    REVERSING = auto()
    OPENING = auto()
    CLOSING = auto()
    LOGGING = auto()
    EVALUATING = auto()


class TradeBot:
    MAX_POSITIONS = 3
    INTERVAL = 15  # Only working with 15 minute charts

    STOP_LOSS_THRESHOLD = 0.75
    ROUNDTRIP_THRESHOLD = 0.75
    BREAK_EVEN_THRESHOLD = 0.05

    def __init__(self, session):
        self.session = session
        self.balance = get_balance(self.session)
        self.current_positions = get_positions(self.session)
        #self.analyse_position()

        self.open_position = False
        self.update_position = False
        self.reverse_position = False

        self.finalised_order_ids = []
        self.live_prices = {}

        self.live_order_queue = queue.Queue(maxsize=1)
        self.incoming_trade_queue = queue.Queue(maxsize=1)
        self.bot_shutdown = threading.Event()

    def check_roundtrip(self, symbol, open_time, stop_loss, break_even_price,
                        entry_price, side):

        end_time = get_current_time(self.session)
        data = get_past_low_high_prices(self.session, symbol,
                                        TradeBot.INTERVAL, open_time, end_time)

        if data is None:
            return False

        lowest_price = data["lowest_price"]
        highest_price = data["highest_price"]
        lowest_timestamp = data["lowest_timestamp"]
        highest_timestamp = data["highest_timestamp"]

        if side == "Buy":

            tp_threshold = highest_price >= take_profit_interpolation(
                entry_price, stop_loss, TradeBot.ROUNDTRIP_THRESHOLD)

            break_even_threshold = lowest_price <= break_even_interpolation(
                break_even_price, stop_loss, TradeBot.BREAK_EVEN_THRESHOLD)

            chronological = highest_timestamp < lowest_timestamp

            if (tp_threshold and break_even_threshold and chronological):
                print(f"Roundtrip has been detected on {symbol} ")

            return tp_threshold and break_even_threshold and chronological

        elif side == "Sell":

            tp_threshold = lowest_price <= take_profit_interpolation(
                entry_price, stop_loss, TradeBot.ROUNDTRIP_THRESHOLD)

            break_even_threshold = highest_price >= break_even_interpolation(
                break_even_price, stop_loss, TradeBot.BREAK_EVEN_THRESHOLD)

            chronological = lowest_timestamp < highest_timestamp

            if (tp_threshold and break_even_threshold and chronological):
                print(f"Roundtrip has been detected on {symbol} ")

            return tp_threshold and break_even_threshold and chronological

        return False

    def analyse_position(self):

        if self.current_positions is None:
            return

        for position in self.current_positions:
            position["roundtripped"] = self.check_roundtrip(
                position["symbol"], position["timestamp"],
                position["stop_loss"], position["break_even_price"],
                position["entry_price"], position["side"])

    def check_account_eligibility(self, reverse=False):
        balance = float(get_balance(self.session)["wallet_balance"])

        if self.current_positions is None and balance > 5.0:
            print("Account is eligible to open a new position")
            return True, balance

        if (len(self.current_positions) < TradeBot.MAX_POSITIONS
                and balance > 5.0) or (reverse and balance > 5.0):
            print("Account is eligible to open a new position")
            return True, balance
        else:
            print("Account is not eligible to open a new position!")
            return False, None

    def calculate_optimum_position(self, funds):
        max_leverage, mmr, mm_deduction, theoretical_quantity = get_position_constraints(
            self.session, self.live_prices[self.trade["symbol"]]["last_price"],
            self.trade["symbol"], self.trade["side"], funds)
        osl = optimum_stop_loss(
            self.live_prices[self.trade["symbol"]]["last_price"],
            self.trade["side"], self.trade["trendline"], self.trade["support"],
            self.trade["resistance"], TradeBot.STOP_LOSS_THRESHOLD)
        ol = optimum_leverage(
            self.live_prices[self.trade["symbol"]]["last_price"], osl,
            self.trade["side"], max_leverage, mmr, mm_deduction,
            theoretical_quantity)
        oca = optimum_coin_amount(
            self.live_prices[self.trade["symbol"]]["last_price"], ol, funds,
            self.trade["side"])

        return osl, ol, oca

    def reset(self, order_id, order_status):
        self.finalised_order_ids.remove((order_id, order_status))
        self.update_position = False
        self.open_position = False
        self.reverse_position = False
        self.trade = None
        self.live_order_queue.task_done()
        if not self.incoming_trade_queue.empty():
            self.incoming_trade_queue.get()
            self.incoming_trade_queue.task_done()

    def initialise_tracker(self):
        self.price_tracker_thread = threading.Thread(target=self.price_tracker,
                                                     daemon=True)
        self.price_tracker_thread.start()

    def price_tracker(self):

        symbols = [
            "BTCUSDT", "ETHUSDT", "DOGEUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT",
            "LINKUSDT"
        ]

        while not self.bot_shutdown.is_set():

            if self.bot_shutdown.is_set():
                break

            for symbol in symbols:
                live_prices = get_price(self.session, symbol)
                self.live_prices[symbol] = {
                    "last_price": live_prices["last_price"],
                    "mark_price": live_prices["mark_price"],
                    "index_price": live_prices["index_price"]
                }
                time.sleep(0.1)

    def receiver(self, trade):

        if self.bot_shutdown.is_set():
            return

        self.incoming_trade_queue.join()

        self.trade = trade
        self.incoming_trade_queue.put(self.trade)

        position_exists = False

        if not self.current_positions:
            self.open_position = True
            return

        for position in self.current_positions:
            if position["symbol"] == trade["symbol"]:
                position_exists = True
                if position["side"] != trade["side"]:
                    self.reverse_position = True
                    break

        if not position_exists:
            self.open_position = True

    def initialise_manager(self):
        self.position_manager_thread = threading.Thread(
            target=self.position_manager, daemon=True)
        self.position_manager_thread.start()

    def position_manager(self):

        while not self.bot_shutdown.is_set():

            if self.bot_shutdown.is_set():
                break

            self.live_order_queue.join()

            if not self.finalised_order_ids and self.current_positions:
                autoclosed_order_ids = check_autoclosed_order_id(
                    self.session, self.current_positions,
                    TradeBot.MAX_POSITIONS)
                if autoclosed_order_ids:
                    print("An autoclosed position has been detected!")
                    self.finalised_order_ids = autoclosed_order_ids

            if self.finalised_order_ids:
                order_id, order_status = self.finalised_order_ids[0]
                if order_status == "CLOSE":
                    closed_orders_ids = confirm_closed_order_id(
                        self.session, order_id)

                    if closed_orders_ids:
                        self.live_order_queue.put(
                            (closed_orders_ids, order_status))
                        self.update_position = True

                elif order_status == "OPEN":
                    opened_orders_ids = confirm_opened_order_id(
                        self.session, order_id)
                    if opened_orders_ids:
                        self.live_order_queue.put(
                            (opened_orders_ids, order_status))
                        self.update_position = True

            time.sleep(0.1)

    def run(self):
        self.run_bot_thread = threading.Thread(target=self.run_bot,
                                               daemon=True)
        self.run_bot_thread.start()

    def run_bot(self):

        print("TradeBot now running!\n")

        self.bot = State.MONITORING

        while not self.bot_shutdown.is_set():

            if self.bot_shutdown.is_set():
                return

            match self.bot:

                case State.MONITORING:

                    if self.open_position:
                        self.bot = State.OPENING
                        continue
                    if self.reverse_position:
                        self.bot = State.REVERSING
                        continue
                    if self.update_position:
                        self.bot = State.EVALUATING
                        continue
                    if not self.current_positions:
                        continue
                    for position in self.current_positions:
                        if position["roundtripped"]:
                            self.bot = State.CLOSING
                            continue
                        else:
                            position["roundtripped"] = self.check_roundtrip(
                                position["symbol"], position["timestamp"],
                                position["stop_loss"],
                                position["break_even_price"],
                                position["entry_price"], position["side"])
                            time.sleep(0.5)
                            continue

                case State.REVERSING:
                    for position in self.current_positions:
                        if self.trade["symbol"] == position["symbol"]:
                            self.finalised_order_ids.append(
                                (close_position(self.session,
                                                position["symbol"],
                                                position["side"],
                                                position["size"],
                                                position_idx=0), "CLOSE"))
                            ready = wait_for_reversal(self.session,
                                                      position["symbol"])
                            eligible, balance = self.check_account_eligibility(
                                reverse=True)
                            if eligible and ready:
                                stop_loss, leverage, coins = self.calculate_optimum_position(
                                    balance / 10)
                                self.finalised_order_ids.append(
                                    (open_position(self.session,
                                                   self.trade["symbol"],
                                                   self.trade["side"],
                                                   coins,
                                                   stop_loss,
                                                   leverage,
                                                   position_idx=0), "OPEN"))
                                print(f"Reversed position successfully!\n"
                                      f"Symbol: {self.trade['symbol']}\n"
                                      f"Side: {self.trade['side']}\n"
                                      f"Leverage: {leverage}\n"
                                      f"Coins: {coins}\n"
                                      f"Stop Loss: {stop_loss}\n")
                                self.reverse_position = False
                                self.bot = State.MONITORING
                                continue

                case State.OPENING:
                    eligible, balance = self.check_account_eligibility()
                    if eligible:
                        stop_loss, leverage, coins = self.calculate_optimum_position(
                            balance / 10)
                        self.finalised_order_ids.append(
                            (open_position(self.session,
                                           self.trade["symbol"],
                                           self.trade["side"],
                                           coins,
                                           stop_loss,
                                           leverage,
                                           position_idx=0), "OPEN"))
                        print(f"Opened position successfully!\n"
                              f"Symbol: {self.trade['symbol']}\n"
                              f"Side: {self.trade['side']}\n"
                              f"Leverage: {leverage}\n"
                              f"Coins: {coins}\n"
                              f"Stop Loss: {stop_loss}\n")
                    self.open_position = False
                    self.bot = State.MONITORING
                    continue

                case State.CLOSING:
                    for position in self.current_positions:
                        if position["roundtripped"]:
                            self.finalised_order_ids.append(
                                (close_position(self.session,
                                                position["symbol"],
                                                position["side"],
                                                position["size"],
                                                position_idx=0), "CLOSE"))
                            position["roundtripped"] = False
                            print(f"Closed position successfully!\n"
                                  f"Symbol: {position['symbol']}\n"
                                  f"Side: {position['side']}\n"
                                  f"Coins: {position['size']}\n")
                    self.bot = State.MONITORING
                    continue

                case State.EVALUATING:
                    self.balance = get_balance(self.session)
                    self.current_positions = get_positions(self.session)
                    self.analyse_position()
                    self.bot = State.LOGGING
                    continue

                case State.LOGGING:
                    order_id, order_status = self.live_order_queue.get()
                    message = get_execution_overview(self.session, order_id,
                                                     order_status,
                                                     self.balance,
                                                     self.current_positions,
                                                     TradeBot.MAX_POSITIONS)
                    send(message)
                    print("Order confirmation sent to telegram!")
                    self.reset(order_id, order_status)
                    self.bot = State.MONITORING
                    continue

    def shutdown(self):

        self.bot_shutdown.set()
        threads = [
            self.price_tracker_thread, self.position_manager_thread,
            self.run_bot_thread
        ]

        for thread in threads:
            if thread and thread.is_alive():
                thread.join(timeout=10)
        print("TradeBot successfully shutdown.")
        print("Hoping the TradeBot made you cash.\n")


# STRAGETY:
# If coin is bought, close at sell signal if sell signal comes first before anything else
# If coin is rising after buy and exceeds 75% of 1.0 rtr then starts coming down, close trade if break even price is hit
# If coin is falling after buy and continues to fall, accept stop loss
# If coin is falling after buy and starts to rise and exceeds 80% of 1.0 rtr then starts coming down, close trade if break even price is hit

# QUEUE:
# self.live_order_queue.put(order) adds a task and increments unfinished_tasks.
# self.live_order_queue.join() blocks if unfinished_tasks > 0.
# self.live_order_queue.get() retrieves the task but does not unblock join().
# self.live_order_queue.task_done() decrements unfinished_tasks
# When unfinished_tasks == 0, join() unblocks.

# receiver()
# Step 1: Alert A arrives:            signal_queue = [A]        incoming_trade_queue = []
# Step 2: Alert A put in trade queue: signal_queue = []         incoming_trade_queue = [A]
# Step 3: Alert B and C arrive:       signal_queue = [B, C]     incoming_trade_queue = [A]
# Step 4: Alert A finishes task       signal_queue = [C]        incoming_trade_queue = [B]
# Step 5: Alert B finishes task       signal_queue = []         incoming_trade_queue = [C]

#position_manager()
# For reversed positions:
# Closed order ids is returned, self.live_order_queue.put(("CLOSED", closed_orders_ids)) is executed and fills the queue
# Opened order ids is returned, self.live_order_queue.put(("OPENED", opened_orders_ids)) is blocked and cannot execute as queue is full
# Queue unblocks when self.live_order_queue.get() is executed, and self.live_order_queue.put(("OPENED", opened_orders_ids)) will execute

#check_roundtrip()
# Roundtrip - The coin has already rose to near its TP (>75%) but didn't actually hit the TP and has gone back down to entry price.
# Solution: Check current price. If below entry price and currently falling, sell now. If below entry price and rising, wait and sell at first fall.
# If above entry price, if falling, sell. If rising, wait until TP or sell at next fall.

# For closed/opened only positions:
# Closed/Opened order ids is returned, self.live_order_queue.put(("CLOSED", closed_orders_ids)) is executed and fills the queue
# self.live_order_queue.join() blocks any further future execution until task in queue is done with task_done()

# .join() is blocked when the queue has an unfinished task
# .join() is unblocked when the queue task is finished from when .task_done() is executed
#
# Maker fee (non-vip) 0.02% of total position
# Taker fee (non-vip) 0.0055% of total position
# Funding fee 0.0037%
