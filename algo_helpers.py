def take_profit_interpolation(entry_price, stop_loss, roundtrip_threshold):
    return entry_price + (entry_price - stop_loss) * roundtrip_threshold


def break_even_interpolation(break_even_price, stop_loss,
                             break_even_threshold):
    return break_even_price + (break_even_price -
                               stop_loss) * break_even_threshold


def price_percentage(current_price, target_price):
    return (current_price / target_price) * 100


def optimum_stop_loss(buy_price, side, trendline, support, resistance,
                      stop_loss_threshold):
    if side == "Buy":
        return buy_price - (
            (buy_price - min(trendline, support)) * stop_loss_threshold)
    else:
        return buy_price + (
            (max(trendline, resistance) - buy_price) * stop_loss_threshold)


def optimum_leverage(buy_price, stop_loss, side, max_leverage,
                     maintenance_margin, maintenance_margin_deduction,
                     theoretical_quantity):
    if side == "Buy":
        return min((0.93 * buy_price) /
                   (buy_price - stop_loss * (1 - maintenance_margin) -
                    maintenance_margin_deduction / theoretical_quantity),
                   max_leverage)
    else:
        return min((0.93 * buy_price) /
                   (stop_loss * (1 + maintenance_margin) - buy_price -
                    maintenance_margin_deduction / theoretical_quantity),
                   max_leverage)


def optimum_coin_amount(buy_price, leverage, funds, side):
    if side == "Buy":
        return (0.9174312 * leverage * funds) / buy_price
    else:
        return (1.0 * leverage * funds) / buy_price
