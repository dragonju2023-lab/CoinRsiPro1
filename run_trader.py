# run_trader.py
import time
from datetime import datetime
import pybithumb
import requests
import logging
import pandas as pd
from core.config import CONFIG


# === 로깅 (파일 + 콘솔 동시 출력 + 디버그 ON) ===
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 파일 핸들러
file_handler = logging.FileHandler('trader.log', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
file_handler.setFormatter(file_formatter)

# 콘솔 핸들러
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)  # 콘솔은 INFO 이상만
console_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
console_handler.setFormatter(console_formatter)

# 핸들러 추가
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# === 빗썸 ===
try:
    bithumb = pybithumb.Bithumb(CONFIG['bithumb']['api_key'], CONFIG['bithumb']['secret_key'])
    logger.info("빗썸 API 연결 성공!")
except Exception as e:
    logger.error(f"빗썸 API 연결 실패: {e}")
    exit()

# === 상태 ===
my_positions = {}
position_size = CONFIG['trade']['position_size']
max_positions = CONFIG['trade'].get('max_positions', 5)
selected_coins = []
KAKAO_TOKEN = CONFIG.get('kakao_token')

# === 카카오 토큰 안전 체크 ===
if not KAKAO_TOKEN:
    logger.warning("KAKAO_TOKEN 없음 → 카톡 알림 OFF")
    def send_kakao(msg): logger.info(f"[카톡 OFF] {msg}")
else:
    def send_kakao(msg):
        try:
            requests.post(
                "https://kapi.kakao.com/v2/api/talk/memo/default/send",
                headers={"Authorization": f"Bearer {KAKAO_TOKEN}"},
                json={"object_type": "text", "text": msg}
            )
        except Exception as e:
            logger.error(f"카톡 전송 실패: {e}")

# === 즉시 테스트용 강제 선별 ===
selected_coins = ['BTC', 'ETH', 'XRP', 'DOGE', 'ADA', 'SOL', 'LINK', 'DOT', 'AVAX', 'MATIC']
logger.info(f"강제 선별 코인: {selected_coins}")
send_kakao("누나야! 강제 선별 완료! 10개 코인으로 즉시 시작!")

# === 업그레이드 설정 ===
DROP_THRESHOLD = 0.05
RISE_TARGET = 0.06
STOP_LOSS = 0.015
TRAILING_STOP = 0.03
RSI_THRESHOLD = 40
VOLUME_MULTIPLIER = 0.5

def get_rsi(close_prices, period=14):
    try:
        delta = close_prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    except: return pd.Series([50])

def get_top20_coins_exclude_btc():
    try:
        # 1. CoinGecko 상위 100개
        url = "https://api.coingecko.com/api/v3/coins/markets"
        data = requests.get(url, params={
            'vs_currency': 'usd', 'per_page': 100, 'page': 1
        }, timeout=10).json()
        coins = [c for c in data if c['id'] != 'bitcoin']

        # 2. 거래량/시총 비율 정렬
        ranked = sorted(coins, key=lambda x: x.get('total_volume', 0) / x.get('market_cap', 1), reverse=True)[:30]

        # 3. 빗썸 실시간 티커 + 가격 검증
        valid_coins = []
        for coin in ranked:
            symbol = coin['symbol'].upper()
            try:
                price = pybithumb.get_current_price(symbol)
                if price and price > 0:
                    valid_coins.append(symbol)
                    if len(valid_coins) >= 20:
                        break
            except:
                continue

        logger.info(f"최종 상장 코인 20개: {valid_coins}")
        return valid_coins if valid_coins else ['ETH', 'XRP', 'DOGE', 'ADA', 'SOL']

    except Exception as e:
        logger.error(f"코인 선별 실패: {e}")
        return ['ETH', 'XRP', 'DOGE', 'ADA', 'SOL']
        
# === 빗썸 자동 재연결 ===
last_connect_time = 0
RECONNECT_INTERVAL = 1800

def get_bithumb():
    global bithumb, last_connect_time
    if time.time() - last_connect_time > RECONNECT_INTERVAL:
        bithumb = pybithumb.Bithumb(CONFIG['bithumb']['api_key'], CONFIG['bithumb']['secret_key'])
        last_connect_time = time.time()
        logger.info("빗썸 재연결")
    return bithumb

# === 매수 (간결 + 안정) ===
def safe_buy(coin, amount, price):
    # 실시간 상장 여부 재확인
    if coin not in set(pybithumb.get_tickers()):
        logger.warning(f"BUY 스킵 {coin}: 실시간 미상장")
        return False

    client = get_bithumb()
    for _ in range(3):
        try:
            krw = bithumb.get_balance(coin)[2]
            logger.info(f"{coin} 잔고!!!: {bithumb.get_balance(coin)}")
            logger.info(f"{coin} 잔고!!: {krw} | {price} | {amount} | {price*amount}")

            if krw >= amount * price:
                order = bithumb.buy_market_order(coin, amount , 'KRW')
                logger.info(f"{coin}8 order: {order}")
                if order and order != 0 and isinstance(order, dict) and 'order_id' in order:
                    # === 로그 형식 통일 (대시보드 인식용!) ===
                    log_msg = f"BUY | {coin} | {amount:.6f}개 | {price:,.0f}원 | 주문번호: {order[2]}"
                    logger.info(log_msg)

                    return True
            else:
                logger.error(f"BUY 실패! {coin}: 잔고 부족 ")
                return False
        except Exception as e:
            logger.error(f"BUY 실패 {coin}: {e}")
            return False
        
        time.sleep(1)


# === 매도 (간결 + 안정) ===
def safe_sell(coin, amount, price, reason="목표"):
    client = get_bithumb()
    for _ in range(3):
        try:
            bal = client.get_balance(coin)[0]
            if bal >= amount:
                order = client.sell_market_order(coin, amount, 'KRW' )
                if order and order != 0 and isinstance(order, dict) and 'order_id' in order:
                    pnl = (price / my_positions[coin]['buy_price'] - 1) * 100
                    profit = (price - my_positions[coin]['buy_price']) * amount
                    logger.warning(f"SELL | {coin} | {amount:.6f}개 | {price:,.0f}원 | {reason} | +{pnl:.2f}% | {profit:,.0f}원")
                    del my_positions[coin]
                    return True
            else:
                logger.error(f"SELL 실패 {coin}: 보유 부족")
                return False
        except: 
            logger.error(f"SELL 실패 {coin}: API 응답 없음")
            return False
        
        time.sleep(1)

# === 빗썸 잔고 조회 + 자동 매도 로직 ===
def get_bithumb_positions():
    """빗썸에서 실제 보유 중인 코인 반환"""
    try:
        balances = bithumb.get_balance('ALL')
        coins = balances['data']  # ← 여기!
        positions = {}

        for key, value in coins.items():
            if key.startswith('available_'):       
                ticker = key.replace('available_', '').upper()
                amount = float(value)
                if ticker not in 'P' and ticker not in 'KRW' and ticker not in 'BTC' and  ticker not in 'SOLO' and amount > 0.0: 
                    price = pybithumb.get_current_price(ticker)
                    if price:
                        positions[ticker] = {
                            'amount': amount,
                            'current_price': price
                        }

        logger.info(f"빗썸 실제 보유 코인: {positions}")

        return positions
    except Exception as e:
        logger.error(f"잔고 조회 실패: {e}")
        return {}

def auto_sell_positions():
    """보유 코인 중 +6% 도달 시 자동 매도"""
    try:
        # 1. 빗썸 실제 보유 코인 가져오기
        real_positions = get_bithumb_positions()
        if not real_positions:
            return

        # 2. my_positions에 없으면 추가 (매수 시점 모름 → 현재가 기준)
        for coin, data in real_positions.items():
            if coin not in my_positions:
                # 매수 가격 모름 → 현재가 기준으로 시작
                my_positions[coin] = {
                    'buy_price': data['current_price'],  # 현재가로 시작
                    'amount': data['amount'],
                    'highest': data['current_price'],
                    'trail_active': False
                }
                logger.info(f"잔고 감지 | {coin} | {data['amount']:.6f}개 | 기준가: {data['current_price']:,.0f}원")

        # 3. 기존 로직과 동일하게 수익률 체크
        for coin, pos in list(my_positions.items()):
            current = pybithumb.get_current_price(coin)
            if not current: continue
            pnl = (current / pos['buy_price'] - 1)

            # 최고가 갱신
            if current > pos['highest']:
                pos['highest'] = current
                if pnl >= TRAILING_STOP and not pos['trail_active']:
                    pos['trail_active'] = True

            # 매도 조건
            if pnl >= RISE_TARGET:
                safe_sell(coin, pos['amount'], current, "목표+6%")
            elif pnl <= -STOP_LOSS:
                safe_sell(coin, pos['amount'], current, "손절-1.5%")
            elif pos['trail_active'] and current <= pos['highest'] * (1 - TRAILING_STOP):
                safe_sell(coin, pos['amount'], current, "트레일링+3%")

    except Exception as e:
        logger.error(f"자동 매도 로직 오류: {e}")

def run_trader():
    logger.info("=== 누나 프로급 트레이더 v2.0 시작 ===")
    send_kakao("봇 시작! 1분마다 살아있어! 체크할게~")


    loop_count = 0
    last_update_day = None

    while True:
        loop_count += 1
        try:
            # 매일 새로 코인 갱신
            if datetime.now().day != last_update_day:
                selected_coins = get_top20_coins_exclude_btc()
                last_update_day = datetime.now().day

            # 실시간 티커 재확인
            current_tickers = set(pybithumb.get_tickers())
            target_coins = [c for c in selected_coins if c in current_tickers]

            logger.debug(f"--- 루프 {loop_count} 시작 ---")

            if loop_count % 1 == 0:
                logger.info(f"살아있어! 루프 {loop_count}회 | 시간: {datetime.now().strftime('%H:%M:%S')}")

            target_coins = selected_coins
            if not target_coins:
                logger.warning("target_coins 비어있음! 강제 선별 다시 실행")
                target_coins = ['BTC', 'ETH', 'XRP', 'DOGE']

            daily_data = {}
            for coin in target_coins:
                try:
                    logger.debug(f"[{coin}] 데이터 수집 중...")
                    # 파라미터 3개만 사용!
                    ohlcv = pybithumb.get_ohlcv(coin, "KRW", "day")
                    # logger.info(f"ohlcv {ohlcv}")
                    if ohlcv is None or len(ohlcv) < 3:
                        logger.warning(f"[{coin}] 일봉 데이터 부족")
                        continue
                    df = ohlcv.tail(3)  # 최근 3개만 사용
                    yesterday = df['close'].iloc[-2]
                    current = pybithumb.get_current_price(coin)
                    if not current:
                        logger.warning(f"[{coin}] 현재가 없음")
                        continue
                    daily_change = (current - yesterday) / yesterday
                    volume_ratio = df['volume'].iloc[-1] / df['volume'].iloc[-2] if df['volume'].iloc[-2] > 0 else 0
                    
                    # 1분봉도 3파라미터
                    minute_df = pybithumb.get_ohlcv(coin, "KRW", "minute1")
                    minute_df = minute_df.tail(100)  # 최근 100개
                    rsi = get_rsi(minute_df['close']).iloc[-1] if len(minute_df) >= 14 else 50

                    daily_data[coin] = {
                        'current': current, 'yesterday': yesterday,
                        'change': daily_change, 'volume_ratio': volume_ratio, 'rsi': rsi
                    }
                    logger.debug(f"[{coin}] change={daily_change:+.1%}, vol={volume_ratio:.1f}x, RSI={rsi:.1f}")
                except Exception as e:
                    logger.error(f"[{coin}] 데이터 오류: {e}")
                    continue

            if not daily_data:
                logger.warning("모든 코인 데이터 실패 → 60초 대기")
                time.sleep(60)
                continue

            for coin, data in daily_data.items():
                price = data['current']
                change = data['change']
                volume_ok = data['volume_ratio'] >= VOLUME_MULTIPLIER
                rsi_ok = data['rsi'] < RSI_THRESHOLD

                logger.debug(f"[{coin}] 매수 조건: change:{change:.1%}<={-DROP_THRESHOLD:.1%}? {change <= -DROP_THRESHOLD}, "
                            f"vol:{data['volume_ratio']}>={VOLUME_MULTIPLIER}x? {volume_ok}, RSI:{data['rsi']}<{RSI_THRESHOLD}? {rsi_ok}")

                if (change <= -DROP_THRESHOLD and rsi_ok
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
                        safe_sell(coin, pos['amount'], price, "목표+6%")
                    elif pnl <= -STOP_LOSS:
                        safe_sell(coin, pos['amount'], price, "손절-1.5%")
                    elif pos['trail_active'] and price <= pos['highest'] * (1 - TRAILING_STOP):
                        safe_sell(coin, pos['amount'], price, "트레일링+3%")

            # === 잔고 기반 자동 매도 (여기 추가!) ===
            auto_sell_positions()
                
            logger.debug(f"--- 루프 {loop_count} 종료 | 포지션: {len(my_positions)}개 ---")
            time.sleep(60)

        except Exception as e:
            logger.error(f"루프 전체 에러: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_trader()