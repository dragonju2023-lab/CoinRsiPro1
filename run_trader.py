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
DROP_THRESHOLD = 0.10
RISE_TARGET = 0.06
STOP_LOSS = 0.015
TRAILING_STOP = 0.03
RSI_THRESHOLD = 30
VOLUME_MULTIPLIER = 2.0

def get_rsi(close_prices, period=14):
    try:
        delta = close_prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    except: return pd.Series([50])

def safe_buy(coin, amount, price):
    try:
        order = bithumb.buy_market_order(f"{coin}_KRW", amount * price)
        log_msg = f"BUY | {coin} | {amount:.6f}개 | {price:,.0f}원 | -10%+RSI+볼륨"
        logger.info(log_msg)
        send_kakao(f"매수 {coin} {amount:.4f}개 @ {price:,.0f}원")
        return True
    except Exception as e:
        logger.error(f"BUY 실패 {coin}: {e}")
        return False

def get_top20_coins_exclude_btc():
    """BTC 제외, 시총 상위 10 + 거래량 상위 10 → 거래량/시총 비율 높은 상위 20개"""
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            'vs_currency': 'usd',
            'order': 'market_cap_desc',
            'per_page': 100,
            'page': 1
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}")

        data = response.json()
        # BTC 제외
        coins = [c for c in data if c['id'] != 'bitcoin']

        # 1. 시총 상위 10
        market_cap_top10 = coins[:10]

        # 2. 거래량 상위 10
        volume_top10 = sorted(coins, key=lambda x: x.get('total_volume', 0), reverse=True)[:10]

        # 3. 합쳐서 중복 제거
        candidates = {c['symbol'].upper(): c for c in (market_cap_top10 + volume_top10)}
        candidates_list = list(candidates.values())

        # 4. 거래량 / 시총 비율로 정렬 (활발한 코인 우선)
        ranked = sorted(
            candidates_list,
            key=lambda x: (x.get('total_volume', 0) or 0) / (x.get('market_cap', 1) or 1),
            reverse=True
        )[:20]

        # 5. 빗썸 상장 여부 확인
        bithumb_tickers = set(pybithumb.get_tickers())
        final_coins = []
        for coin in ranked:
            symbol = coin['symbol'].upper()
            if symbol in bithumb_tickers:
                final_coins.append(symbol)
            if len(final_coins) >= 20:
                break

        if not final_coins:
            raise Exception("빗썸 상장 코인 없음")

        logger.info(f"BTC 제외 상위 20개 선별 완료: {final_coins}")
        send_kakao(f"상위 20개 선별: {', '.join(final_coins[:5])}... (총 {len(final_coins)}개)")
        return final_coins

    except Exception as e:
        logger.error(f"상위 20개 선별 실패: {e}")
        fallback = ['ETH', 'XRP', 'DOGE', 'ADA', 'SOL', 'LINK', 'DOT', 'AVAX', 'MATIC', 'LTC',
                    'BCH', 'ETC', 'UNI', 'ICP', 'APT', 'HBAR', 'ATOM', 'VET', 'FIL', 'NEAR']
        logger.warning(f"fallback 사용: {fallback[:10]}...")
        return fallback
    
def safe_sell(coin, amount, price, reason="목표"):
    try:
        order = bithumb.sell_market_order(f"{coin}_KRW", amount * price)
        pos = my_positions[coin]
        pnl = (price / pos['buy_price'] - 1) * 100
        profit = (price - pos['buy_price']) * amount
        log_msg = f"SELL | {coin} | {amount:.6f}개 | {price:,.0f}원 | {reason} | 수익 {pnl:+.2f}% | {profit:,.0f}원"
        logger.warning(log_msg)
        send_kakao(f"매도 {coin} {reason} +{pnl:.2f}% → {profit:,.0f}원!")
        del my_positions[coin]
        return True
    except Exception as e:
        logger.error(f"SELL 실패 {coin}: {e}")
        return False

def run_trader():
    logger.info("=== 누나 프로급 트레이더 v2.0 시작 ===")
    send_kakao("봇 시작! 1분마다 살아있어! 체크할게~")

    loop_count = 0
    while True:
        loop_count += 1
        try:
            logger.debug(f"--- 루프 {loop_count} 시작 ---")

            if loop_count % 1 == 0:
                logger.info(f"살아있어! 루프 {loop_count}회 | 시간: {datetime.now().strftime('%H:%M:%S')}")

            target_coins = get_top20_coins_exclude_btc()
            if not target_coins:
                logger.warning("target_coins 비어있음! 강제 선별 다시 실행")
                target_coins = ['BTC', 'ETH', 'XRP', 'DOGE']

            daily_data = {}
            for coin in target_coins:
                try:
                    logger.debug(f"[{coin}] 데이터 수집 중...")
                    # 파라미터 3개만 사용!
                    ohlcv = pybithumb.get_ohlcv(coin, "KRW", "day")
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

                logger.debug(f"[{coin}] 매수 조건: change<={-DROP_THRESHOLD:.1%}? {change <= -DROP_THRESHOLD}, "
                            f"vol>={VOLUME_MULTIPLIER}x? {volume_ok}, RSI<{RSI_THRESHOLD}? {rsi_ok}")

                if (change <= -DROP_THRESHOLD and volume_ok and rsi_ok
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

            logger.debug(f"--- 루프 {loop_count} 종료 | 포지션: {len(my_positions)}개 ---")
            time.sleep(60)

        except Exception as e:
            logger.error(f"루프 전체 에러: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_trader()