# run_trader.py
import time
from datetime import datetime
import pybithumb
import logging
import pandas as pd
from core.config import get_config

# === 로깅 ===
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler('trader.log', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# === 빗썸 ===
cfg = get_config()
try:
    bithumb = pybithumb.Bithumb(cfg['bithumb']['api_key'], cfg['bithumb']['secret_key'])
    logger.info("빗썸 API 연결 성공!")
except Exception as e:
    logger.error(f"빗썸 API 연결 실패: {e}")
    exit()

# === 상태 ===
my_positions = {}
max_positions = 5
selected_coins = ['BTC', 'ETH', 'XRP', 'DOGE', 'ADA', 'SOL', 'LINK', 'DOT', 'AVAX', 'MATIC']
logger.info(f"강제 선별 코인: {selected_coins}")

# === RSI 계산 ===
def get_rsi(close_prices, period=14):
    try:
        delta = close_prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    except:
        return pd.Series([50])

# === 추세 판단 ===
def get_trend_signal(coin):
    try:
        df = pybithumb.get_ohlcv(coin, "KRW", "day")
        if len(df) < 50: return "데이터 부족"
        df = df.tail(50)
        ma20 = df['close'].rolling(20).mean().iloc[-1]
        ma50 = df['close'].rolling(50).mean().iloc[-1]
        current = df['close'].iloc[-1]
        if current > ma20 > ma50: return "상승장"
        elif current < ma20 < ma50: return "하락장"
        else: return "횡보장"

    except Exception as e:
        logger.error(f"[{coin}] 추세 분석 오류: {e}")
        return "알수없음"

# === 빗썸 잔고 조회 + 자동 매도 ===
def get_bithumb_positions():
    try:
        balances = bithumb.get_balance('ALL')
        coins = balances['data']
        positions = {}
        for key, value in coins.items():
            if key.startswith('available_'):
                ticker = key.replace('available_', '').upper()
                amount = float(value)
                if ticker not in ['P', 'KRW', 'BTC', 'SOLO'] and amount > 0.0001:
                    price = pybithumb.get_current_price(ticker)
                    if price:
                        positions[ticker] = {'amount': amount, 'current_price': price}
        logger.info(f"빗썸 실제 보유: {positions}")
        return positions
    except Exception as e:
        logger.error(f"잔고 조회 실패: {e}")
        return {}

def auto_sell_positions():
    try:
        real_positions = get_bithumb_positions()
        if not real_positions: return

        for coin, data in real_positions.items():
            if coin not in my_positions:
                my_positions[coin] = {
                    'buy_price': data['current_price'],
                    'amount': data['amount'],
                    'highest': data['current_price'],
                    'trail_active': False
                }
                logger.info(f"잔고 감지 | {coin} | {data['amount']:.6f}개 | 기준가: {data['current_price']:,.0f}원")

        for coin, pos in list(my_positions.items()):
            current = pybithumb.get_current_price(coin)
            if not current: continue
            pnl = (current / pos['buy_price'] - 1)

            if current > pos['highest']:
                pos['highest'] = current
                if pnl >= cfg["TRAILING_STOP"] and not pos['trail_active']:
                    pos['trail_active'] = True

            if pnl >= cfg["RISE_TARGET"]:
                safe_sell(coin, pos['amount'], current, "목표")
            elif pnl <= -cfg["STOP_LOSS"]:
                safe_sell(coin, pos['amount'], current, "손절")
            elif pos['trail_active'] and current <= pos['highest'] * (1 - cfg["TRAILING_STOP"]):
                safe_sell(coin, pos['amount'], current, "트레일링")
    except Exception as e:
        logger.error(f"자동 매도 오류: {e}")

# === 매수 ===
def safe_buy(coin, amount, price):
    if coin not in set(pybithumb.get_tickers()):
        logger.warning(f"BUY 스킵 {coin}: 미상장")
        return False

    for _ in range(3):
        try:
            krw = bithumb.get_balance(coin)[2]
            logger.info(f"{coin} 잔고!!: krw = {krw} | price={price} | amount={amount} | price*amount={price*amount}")
            if krw >= amount * price:
                order = bithumb.buy_market_order(coin, amount, 'KRW')
                logger.info(f"{coin}8 order: {order}")
                if order and isinstance(order, tuple) and len(order) >= 3:
                    log_msg = f"BUY | {coin} | {amount:.6f}개 | {price:,.0f}원 | 주문번호: {order[2]}"
                    logger.info(log_msg)
                    return True
            else:
                logger.error(f"BUY 실패! {coin}: 잔고 부족")
                return False
        except Exception as e:
            logger.error(f"BUY 실패 {coin}: {e}")
        time.sleep(1)
    return False

# === 매도 ===
def safe_sell(coin, amount, price, reason="목표"):
    for _ in range(3):
        try:
            bal = bithumb.get_balance(coin)[0]
            if bal >= amount:
                order = bithumb.sell_market_order(coin, amount, 'KRW')
                if order and isinstance(order, tuple) and len(order) >= 3:
                    pnl = (price / my_positions[coin]['buy_price'] - 1) * 100
                    profit = (price - my_positions[coin]['buy_price']) * amount
                    logger.warning(f"SELL | {coin} | {amount:.6f}개 | {price:,.0f}원 | {reason} | +{pnl:.2f}% | {profit:,.0f}원")
                    del my_positions[coin]
                    return True
            else:
                logger.error(f"SELL 실패 {coin}: 보유 부족")
                return False
        except Exception as e:
            logger.error(f"SELL 실패 {coin}: {e}")
        time.sleep(1)
    return False

# === 메인 루프 ===
def run_trader():
    logger.info("=== 뻥그 프로급 트레이더 시작 ===")
    loop_count = 0
    last_update_day = None

    while True:
        loop_count += 1
        try:
            cfg = get_config()  # 실시간 설정
            DROP_THRESHOLD = cfg["DROP_THRESHOLD"]
            RISE_TARGET = cfg["RISE_TARGET"]
            STOP_LOSS = cfg["STOP_LOSS"]
            TRAILING_STOP = cfg["TRAILING_STOP"]
            RSI_THRESHOLD = cfg["RSI_THRESHOLD"]
            VOLUME_MULTIPLIER = cfg["VOLUME_MULTIPLIER"]
            position_size = cfg["position_size"]

            if datetime.now().day != last_update_day:
                selected_coins = ['ETH', 'XRP', 'DOGE', 'ADA', 'SOL', 'LINK', 'DOT', 'AVAX', 'MATIC', 'LTC']
                last_update_day = datetime.now().day

            current_tickers = set(pybithumb.get_tickers())
            target_coins = [c for c in selected_coins if c in current_tickers]

            logger.info(f"살아있어! 루프 {loop_count}회 | 시간: {datetime.now():%H:%M:%S}")

            daily_data = {}
            for coin in target_coins:
                try:
                    ohlcv = pybithumb.get_ohlcv(coin, "KRW", "day")
                    if ohlcv is None or len(ohlcv) < 3: continue
                    df = ohlcv.tail(3)
                    yesterday = df['close'].iloc[-2]
                    current = pybithumb.get_current_price(coin)
                    if not current: continue
                    daily_change = (current - yesterday) / yesterday
                    volume_ratio = df['volume'].iloc[-1] / df['volume'].iloc[-2] if df['volume'].iloc[-2] > 0 else 0
                    minute_df = pybithumb.get_ohlcv(coin, "KRW", "minute1").tail(100)
                    rsi = get_rsi(minute_df['close']).iloc[-1] if len(minute_df) >= 14 else 50

                    daily_data[coin] = {
                        'current': current, 'change': daily_change,
                        'volume_ratio': volume_ratio, 'rsi': rsi
                    }
                    # logger.debug(f"[{coin}] change={daily_change:+.1%}, vol={volume_ratio:.1f}x, RSI={rsi:.1f}")

                except Exception as e:
                    logger.error(f"[{coin}] 데이터 오류: {e}")
                    continue

            for coin, data in daily_data.items():
                price = data['current']
                change = data['change']
                volume_ok = data['volume_ratio'] >= VOLUME_MULTIPLIER
                rsi_ok = data['rsi'] < RSI_THRESHOLD

                # === 추세 신호 확인 (여기 추가!) ===
                trend_signal = get_trend_signal(coin)
                if not trend_signal:
                    logger.debug(f"[{coin}] 추세 신호 없음 → 매수 스킵")
                    continue

                logger.debug(f"[{coin}] 매수 조건: {trend_signal}, change:{change:.1%}<={-DROP_THRESHOLD:.1%}? {change <= -DROP_THRESHOLD}, "
                            f"vol:{data['volume_ratio']}>={VOLUME_MULTIPLIER}x? {volume_ok}, RSI:{data['rsi']}<{RSI_THRESHOLD}? {rsi_ok}")

                if (change <= -DROP_THRESHOLD and rsi_ok and trend_signal in "상승장" 
                    and coin not in my_positions and len(my_positions) < max_positions):
                    amount = position_size / price
                    if safe_buy(coin, amount, price):
                        my_positions[coin] = {
                            'buy_price': price, 'amount': amount,
                            'highest': price, 'trail_active': False
                        }

                elif coin in my_positions:
                    pos = my_positions[coin]
                    pnl = (price / pos['buy_price'] - 1)
                    if price > pos['highest']:
                        pos['highest'] = price
                        if pnl >= TRAILING_STOP and not pos['trail_active']:
                            pos['trail_active'] = True

                    if pnl >= RISE_TARGET:
                        safe_sell(coin, pos['amount'], price, "목표")
                    elif pnl <= -STOP_LOSS:
                        safe_sell(coin, pos['amount'], price, "손절")
                    elif pos['trail_active'] and price <= pos['highest'] * (1 - TRAILING_STOP):
                        safe_sell(coin, pos['amount'], price, "트레일링")

            auto_sell_positions()
            time.sleep(60)

        except Exception as e:
            logger.error(f"루프 전체 에러: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_trader()