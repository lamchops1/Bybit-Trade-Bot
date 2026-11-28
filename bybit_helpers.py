import time

from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_DOWN

reporter = {}


def report_online(thread):
    reporter[thread] = time.time()


def get_balance(session):
    try:
        response = session.get_wallet_balance(accountType="UNIFIED",
                                              coin="USDT")
        if response["retCode"] != 0:
            raise RuntimeError(response)

        account = response["result"]["list"][0]
        for coin in account["coin"]:
            if coin["coin"] == "USDT":
                return {
                    "equity": coin["equity"],  # Total value of account
                    "wallet_balance": coin[
                        "walletBalance"]  # Current available funds for new trades
                }

    except Exception as e:
        raise RuntimeError(f"Failed to retrieve balance: {e}") from e


def get_positions(session):
    try:
        response = session.get_positions(category="linear", settleCoin="USDT")
        if response["retCode"] != 0:
            raise RuntimeError(response)

        positions = response["result"]["list"]

        open_positions = []

        for position in positions:

            open_positions.append({
                "symbol":
                position["symbol"],
                "side":
                position["side"],  # Long/short but output is "Buy" or "Sell"
                "position_idx":
                position["positionIdx"],
                "size":
                float(position["size"]),  # Quantity of coins
                "leverage":
                float(position["leverage"]),
                "entry_price":
                float(
                    position["avgPrice"]),  # Price of coin at opened position 
                "unrealised_pnl":
                float(position["unrealisedPnl"]),
                "break_even_price":
                float(position["breakEvenPrice"]),
                "stop_loss":
                float(position["stopLoss"]),
                "liquidation_price":
                position["liqPrice"],
                "roundtripped":
                False,
                "timestamp":
                int(position["openTime"])
            })

        return open_positions

    except Exception as e:
        raise RuntimeError(f"Failed to retrieve open positions: {e}") from e


# Linear = derivatives, Spot = Buy and Sell cryptocurrency, Options = Cryptocurrency Options
def get_price(session, symbol):
    try:
        response = session.get_tickers(category="linear", symbol=symbol)
        if response["retCode"] != 0:
            raise RuntimeError(response)

        ticker = response["result"]["list"][0]

        return {
            "last_price": float(ticker["lastPrice"]),
            "mark_price": float(ticker["markPrice"]),
            "index_price": float(ticker["indexPrice"])
        }

    except Exception as e:
        raise RuntimeError(f"Failed to retrieve price of {symbol}: {e}") from e


def get_current_time(session):
    try:
        response = session.get_server_time()
        if response["retCode"] != 0:
            raise RuntimeError(response)

        current_time = int(response["result"]["timeNano"]) // 1000000
        return current_time

    except Exception as e:
        raise RuntimeError(
            f"Failed to retrieve current Bybit time: {e}") from e


# Index 1 = Opening price, 2 = Highest, 3 = Lowest, 4 = Closing price, 5 = Trade volume
def get_past_low_high_prices(session, symbol, interval, start_time, end_time):
    try:

        response = session.get_kline(category="linear",
                                     symbol=symbol,
                                     interval=str(interval),
                                     start=start_time,
                                     end=end_time,
                                     limit=300)
        if response["retCode"] != 0:
            raise RuntimeError(response)

        candles = response["result"]["list"]

        if not candles:
            return None

        candles = sorted(candles, key=lambda x: int(x[0]))

        lowest_candle = min(candles, key=lambda x: float(x[3]))
        highest_candle = max(candles, key=lambda x: float(x[2]))

        return {
            "lowest_price": float(lowest_candle[3]),
            "highest_price": float(highest_candle[2]),
            "lowest_timestamp": int(lowest_candle[0]),
            "highest_timestamp": int(highest_candle[0]),
            "candles": candles
        }

    except Exception as e:
        raise RuntimeError(
            f"Failed to retrieve past prices of {symbol}: {e}") from e


def get_executions(session, symbol):
    try:
        response = session.get_executions(category="linear",
                                          symbol=symbol,
                                          limit=50)
        if response["retCode"] != 0:
            raise RuntimeError(response)
        return response

    except Exception as e:
        raise RuntimeError(
            f"Failed to retrieve closed positions of {symbol}: {e}") from e


def check_autoclosed_order_id(session, positions, max_positions):
    try:
        response = session.get_closed_pnl(category="linear",
                                          limit=max_positions)
        if response["retCode"] != 0:
            raise RuntimeError(response)

        closed_orders = response["result"]["list"]

        if not closed_orders:
            return (False, "")

        autoclosed_orders = []

        for closed_order in closed_orders:
            for position in positions:
                if (closed_order["symbol"] == position["symbol"]
                        and closed_order["side"] != position["side"]
                        and int(closed_order["createdTime"])
                        >= position["timestamp"]):
                    autoclosed_orders.append(
                        (closed_order["orderId"], "CLOSE"))

        return autoclosed_orders

    except Exception as e:
        raise RuntimeError(f"Failed to retrieve closed positions: {e}") from e


def confirm_closed_order_id(session, order_id):
    try:
        response = session.get_order_history(category="linear",
                                             orderId=order_id)
        if response["retCode"] != 0:
            raise RuntimeError(response)

        orders = response["result"]["list"]
        if not orders:
            return None

        order = orders[0]

        if order["orderStatus"] in ("Filled"):
            return order["orderId"]
        else:
            return None

    except Exception as e:
        raise RuntimeError(f"Failed to retrieve order status: {e}") from e


def confirm_opened_order_id(session, order_id):
    try:
        response = session.get_order_history(category="linear",
                                             orderId=order_id)
        if response["retCode"] != 0:
            raise RuntimeError(response)

        orders = response["result"]["list"]
        if not orders:
            return None

        order = orders[0]

        if order["orderStatus"] in ("New", "Filled", "PartiallyFilled"):
            return order["orderId"]
        else:
            return None

    except Exception as e:
        raise RuntimeError(f"Failed to retrieve order status: {e}") from e


def close_position(session, symbol, side, qty, position_idx=0):
    try:
        side = "Sell" if side == "Buy" else "Buy"
        response = session.place_order(category="linear",
                                       symbol=symbol,
                                       side=side,
                                       orderType="Market",
                                       qty=qty,
                                       positionIdx=position_idx,
                                       reduceOnly=True)
        if response["retCode"] != 0:
            raise RuntimeError(response["retMsg"])

        return response["result"]["orderId"]

    except Exception as e:
        raise RuntimeError(f"Failed to close position : {e}") from e


def open_position(session,
                  symbol,
                  side,
                  qty,
                  stop_loss,
                  leverage,
                  position_idx=0):

    try:
        print("Symbol:", symbol)
        print("Calculated quantity:", qty)
        print("Leverage:", leverage)

        response = session.set_margin_mode(setMarginMode="ISOLATED_MARGIN")
        if response["retCode"] != 0:
            raise Exception(response["retMsg"])

        leverage_response = session.set_leverage(category="linear",
                                                 symbol=symbol,
                                                 buyLeverage=str(leverage),
                                                 sellLeverage=str(leverage))
        if leverage_response["retCode"] != 0:
            raise Exception(leverage_response["retMsg"])

        info = session.get_instruments_info(category="linear", symbol=symbol)
        if info["retCode"] != 0:
            raise Exception(info["retMsg"])

        filters = info["result"]["list"][0]["lotSizeFilter"]

        step = Decimal(filters["qtyStep"])

        print("Original quantity:", qty)
        print("Quantity step:", step)

        min_qty = Decimal(filters["minOrderQty"])
        qty = Decimal(str(qty))
        qty = (qty / step).to_integral_value(rounding=ROUND_DOWN) * step

        if qty < min_qty:
            print(f"Calculated quantity ({qty}) is below "
                  f"Bybit minimum ({min_qty}). Skipping trade.")
            return "no-trade-dummy-order-id"

        response = session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=str(qty),
            positionIdx=position_idx,  # One way mode
            stopLoss=str(stop_loss),
            tpslMode="Full",
            slOrderType="Market",
            slTriggerBy="MarkPrice")

        if response["retCode"] != 0:
            raise Exception(f"Order failed: {response}")

        return response["result"]["orderId"]

    except Exception as e:
        raise RuntimeError(f"Failed to open position : {e}") from e


def wait_for_reversal(session, symbol, position_idx=0, timeout=10):

    start = time.time()
    while time.time() - start < timeout:

        positions = get_positions(session)

        waiting = any(
            p["symbol"] == symbol and p["position_idx"] == position_idx
            and float(p["size"]) > 0 for p in positions)

        time.sleep(0.2)

        if not waiting:
            return True


def get_position_constraints(session, entry_price, symbol, side, funds):
    try:
        response = session.get_risk_limit(category="linear", symbol=symbol)
        if response["retCode"] != 0:
            raise Exception(response["retMsg"])

        leverage_tiers = response["result"]["list"]

        PROPOSED_LEVERAGE = 60

        factor = 0.9174312 if side == "Buy" else 1.0
        theoretical_quantity = (factor * PROPOSED_LEVERAGE * funds /
                                entry_price)
        theoretical_position_value = theoretical_quantity * entry_price

        applicable_tier = None

        for tier in sorted(leverage_tiers,
                           key=lambda x: float(x["riskLimitValue"])):
            if theoretical_position_value <= float(tier["riskLimitValue"]):
                applicable_tier = tier
                break

        mmr = float(applicable_tier["maintenanceMargin"])
        mm_deduction = float(applicable_tier["mmDeduction"] or 0)
        max_leverage = float(applicable_tier["maxLeverage"])

        return (max_leverage, mmr, mm_deduction, theoretical_quantity)

    except Exception as e:
        raise RuntimeError(f"Failed to validate position : {e}") from e


def get_execution_overview(session, order_id, order_status, balance, positions,
                           max_positions):

    open_positions = len(positions)
    total_balance = round(float(balance["equity"]), 3)

    try:

        if order_status == "CLOSE" or order_status == "ROUNDTRIP CLOSE":

            response = session.get_order_history(category="linear",
                                                 orderId=order_id)
            if response["retCode"] != 0:
                raise RuntimeError(response)

            orders = response["result"]["list"]
            order = orders[0]

            symbol = order["symbol"]
            currency = symbol.removesuffix("USDT")

            pnl_response = session.get_closed_pnl(category="linear",
                                                  symbol=symbol,
                                                  limit=max_positions)
            if pnl_response["retCode"] != 0:
                raise RuntimeError(pnl_response)

            closed_orders = pnl_response["result"]["list"]
            closed_orders.sort(key=lambda x: int(x["createdTime"]),
                               reverse=True)

            closed_order = None

            for order in closed_orders:
                if order["orderId"] == order_id:
                    closed_order = order
                    break

            entry_price = float(closed_order["avgEntryPrice"])
            exit_price = float(closed_order["avgExitPrice"])
            side = closed_order["side"]
            leverage = float(closed_order["leverage"])
            pnl = float(closed_order["closedPnl"])
            quantity = float(closed_order["closedSize"])
            time = datetime.fromtimestamp(
                int(int(closed_order["updatedTime"])) / 1000,
                tz=ZoneInfo("Australia/Melbourne"))

            result = ("💸💸 PROFIT" if pnl > 0 else
                      "⛔⛔ LOSS" if pnl < 0 else "⚖️⚖️ BREAK EVEN")

            return (f"{result}: ${pnl} USD\n"
                    f"=============================\n"
                    f"🔒 Position: {order_status}\n"
                    f"🆔 Order ID: {order_id}\n"
                    f"💰 Coin: {symbol}\n"
                    f"🏷️ Side: {side}\n"
                    f"⚡ Leverage: {leverage}x\n"
                    f"🏁 Entry Price: {entry_price} USDT\n"
                    f"🏆 Exit Price: {exit_price} USDT\n"
                    f"⚖ Quantity: {quantity} {currency}\n"
                    f"🕒 Time: {time} VIC Time\n"
                    f"===========================\n"
                    f"🤑 Total Balance: ${total_balance} USD 🤑\n"
                    f"===========================\n"
                    f"👉 Current Open Positions: {open_positions}\n")

        else:

            response = session.get_order_history(category="linear",
                                                 orderId=order_id)
            if response["retCode"] != 0:
                raise RuntimeError(response)

            orders = response["result"]["list"]
            order = orders[0]

            opened_order = None

            for position in positions:

                if (position["symbol"] == order["symbol"]
                        and position["side"] == order["side"]
                        and position["position_idx"] == order["positionIdx"]):
                    opened_order = position
                    break

            if opened_order is None:
                raise RuntimeError(
                    f"Could not find open position for order {order_id}")

            symbol = opened_order["symbol"]
            side = opened_order["side"]
            leverage = opened_order["leverage"]
            entry_price = opened_order["entry_price"]
            stop_loss = opened_order["stop_loss"]
            liquidation_price = opened_order["liquidation_price"]
            currency = symbol.removesuffix("USDT")
            quantity = opened_order["size"]
            if side == "Buy":
                one_rtr_profit = round(
                    ((entry_price +
                      (entry_price - stop_loss)) - entry_price) * quantity, 4)
                stop_loss_loss = round((stop_loss - entry_price) * quantity, 4)
                funds = round(
                    (quantity * entry_price) / (0.9174312 * leverage), 3)

            else:
                one_rtr_profit = round(
                    (entry_price - (entry_price +
                                    (entry_price - stop_loss))) * quantity, 4)
                stop_loss_loss = round((entry_price - stop_loss) * quantity, 4)
                funds = round((quantity * entry_price) / (1 * leverage), 3)

            time = datetime.fromtimestamp(int(int(opened_order["timestamp"])) /
                                          1000,
                                          tz=ZoneInfo("Australia/Melbourne"))

            return (f"🔒 Position: {order_status}\n"
                    f"🆔 Order ID: {order_id}\n"
                    f"💰 Coin: {symbol}\n"
                    f"🏷️ Side: {side}\n"
                    f"⚡ Leverage: {leverage}x\n"
                    f"💳 Money Spent: ${funds} USD\n"
                    f"🏁 Entry Price: {entry_price} USDT\n"
                    f"🛑 Stop Loss Price: {stop_loss} USDT\n"
                    f"☠️ Liquidation Price: {liquidation_price} USDT\n"
                    f"⚖ Quantity: {quantity} {currency}\n"
                    f"🕒 Time: {time} VIC Time\n"
                    f"1️ 1.0 RTR Profit: ${one_rtr_profit} USD\n"
                    f"🚫 Stop Loss: ${stop_loss_loss} USD\n"
                    f"===========================\n"
                    f"🤑 Total Balance: ${total_balance} USD 🤑\n"
                    f"===========================\n"
                    f"👉 Current Open Positions: {open_positions}\n")

    except Exception as e:
        raise RuntimeError(f"Failed to obtain position summary : {e}") from e


def get_live_summary(session):

    try:
        response = session.get_wallet_balance(accountType="UNIFIED",
                                              coin="USDT")
        if response["retCode"] != 0:
            raise RuntimeError(response)

        account_balance = None

        account = response["result"]["list"][0]
        for coin in account["coin"]:
            if coin["coin"] == "USDT":
                account_balance = round(float(coin["equity"]), 3)
                break

        response = session.get_positions(category="linear", settleCoin="USDT")
        if response["retCode"] != 0:
            raise RuntimeError(response)

        positions = response["result"]["list"]

        summary = [f"🤑Live Account Balance: ${account_balance} USD🤑 \n\n"]

        for position in positions:

            symbol = position["symbol"]

            response = session.get_tickers(category="linear", symbol=symbol)
            if response["retCode"] != 0:
                raise RuntimeError(response)

            ticker = response["result"]["list"][0]
            current_price = float(ticker["lastPrice"])

            side = position["side"]
            leverage = float(position["leverage"])
            unrealised_profit = float(position["unrealisedPnl"])
            realised_profit = float(position["curRealisedPnl"])
            stop_loss = float(position["stopLoss"])
            qty = float(position["size"])
            buy_price = float(position["avgPrice"])

            live_profit = round(unrealised_profit + realised_profit, 3)
            live_rtr = round(
                (current_price - buy_price) / (buy_price - stop_loss), 2)

            if side == "Buy":
                funds = round((qty * buy_price) / (0.9174312 * leverage), 3)

                summary.append(f"💰 Coin: {symbol}\n"
                               f"💳 Money Spent: ${funds} USD\n"
                               f"📈 Live Profit: ${live_profit} USD\n"
                               f"🚀 Live RTR: {live_rtr}x\n\n")
            else:
                funds = round((qty * buy_price) / (1.0 * leverage), 3)

                summary.append(f"💰 Coin: {symbol}\n"
                               f"💳 Money Spent: ${funds} USD\n"
                               f"📈 Live Profit: ${live_profit} USD\n"
                               f"🚀 Live RTR: {live_rtr}x\n\n")

        return "".join(summary)

    except Exception as e:
        raise RuntimeError(
            f"Failed to retrieve Telegram requested live summary: {e}") from e


def get_live_positions(session):
    try:
        response = session.get_positions(category="linear", settleCoin="USDT")
        if response["retCode"] != 0:
            raise RuntimeError(response)

        positions = response["result"]["list"]

        if not positions:
            return (f"No open positions ")

        live_positions = []

        for position in positions:
            symbol = position["symbol"]

            response = session.get_tickers(category="linear", symbol=symbol)
            if response["retCode"] != 0:
                raise RuntimeError(response)

            ticker = response["result"]["list"][0]
            current_price = float(ticker["lastPrice"])

            side = position["side"]
            leverage = float(position["leverage"])
            stop_loss = float(position["stopLoss"])
            qty = float(position["size"])
            buy_price = float(position["avgPrice"])
            liquidation_price = float(position["liqPrice"])

            live_positions.append(
                f"💰 Symbol: {symbol}\n"
                f"🏷️ Side: {side}\n"
                f"⚡ Leverage: {leverage}x\n"
                f"🏁 Entry Price: ${buy_price} USD\n"
                f"💲 Live Price: ${current_price} USD\n"
                f"🛑 Stop Loss: ${stop_loss} USD\n"
                f"☠️ Liquidation Price: ${liquidation_price} USD\n"
                f"⚖ Quantity: {qty}\n\n")

        return "".join(live_positions)

    except Exception as e:
        raise RuntimeError(
            f"Failed to retrieve Telegram requested live positions: {e}"
        ) from e


def get_live_open_positions(session):
    try:
        response = session.get_positions(category="linear", settleCoin="USDT")

        positions = response["result"]["list"]

        return [
            position["symbol"] for position in positions
            if float(position["size"]) > 0
        ]

    except Exception as e:
        raise RuntimeError(
            f"Failed to retrieve Telegram requested live positions: {e}"
        ) from e


def close_live_position(session, symbol):
    try:
        response = session.get_positions(category="linear", symbol=symbol)
        if response["retCode"] != 0:
            return False, response.get("retMsg", "Failed to retrieve position")

        positions = response["result"]["list"]

        open_positions = [p for p in positions if float(p["size"]) > 0]

        for position in open_positions:
            size = position["size"]
            side = position["side"]
            position_idx = int(position["positionIdx"])
            side = "Sell" if side == "Buy" else "Buy"

            order = session.place_order(category="linear",
                                        symbol=symbol,
                                        side=side,
                                        orderType="Market",
                                        qty=size,
                                        positionIdx=position_idx,
                                        reduceOnly=True)

    except Exception as e:
        print(f"Close position error: {e}")
        return False, str(e)
