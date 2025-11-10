# dashboard_web.py
import streamlit as st
import pandas as pd
import re
import pybithumb
import subprocess
import psutil
import os
import signal
from datetime import datetime
import time

# === 봇 프로세스 관리 ===
BOT_PROCESS = None
PID_FILE = "bot_pid.txt"

def start_bot():
    global BOT_PROCESS
    if BOT_PROCESS is not None and BOT_PROCESS.poll() is None:
        return "이미 실행 중입니다!"
    
    try:
        BOT_PROCESS = subprocess.Popen(
            ["python", "run_trader.py"],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        with open(PID_FILE, "w") as f:
            f.write(str(BOT_PROCESS.pid))
        return f"봇 시작 완료! PID: {BOT_PROCESS.pid}"
    except Exception as e:
        return f"시작 실패: {e}"

def stop_bot():
    global BOT_PROCESS
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            if os.name == "nt":
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            else:
                os.kill(pid, signal.SIGTERM)
            os.remove(PID_FILE)
            return "봇 안전 종료 완료!"
        except Exception as e:
            return f"종료 실패: {e}"
    else:
        return "실행 중인 봇 없음"

def is_bot_running():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            return psutil.pid_exists(pid)
        except:
            return False
    return False

# === Streamlit 대시보드 ===
st.set_page_config(page_title="누나 프로급 트레이더", layout="wide")
st.title("누나 전용 실시간 트레이딩 대시보드")

# === 봇 제어 패널 ===
st.sidebar.header("봇 제어")
col_start, col_stop = st.sidebar.columns(2)

with col_start:
    if st.button("봇 시작", type="primary"):
        with st.spinner("봇 시작 중..."):
            result = start_bot()
            st.success(result)

with col_stop:
    if st.button("봇 종료", type="secondary"):
        with st.spinner("봇 종료 중..."):
            result = stop_bot()
            st.warning(result)

# === 봇 상태 ===
status = "실행 중" if is_bot_running() else "정지됨"
color = "green" if is_bot_running() else "red"
st.sidebar.markdown(f"**봇 상태**: <span style='color:{color}'>{status}</span>", unsafe_allow_html=True)

st.markdown("---")

# === 실시간 갱신 ===
placeholder = st.empty()

while True:
    with placeholder.container():
        col1, col2 = st.columns(2)
        
        # === 보유 코인 ===
        with col1:
            st.subheader("보유 코인")
            df = pd.DataFrame()
            try:
                with open('trader.log', 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                trades = []
                for line in lines:
                    if 'BUY' in line or 'SELL' in line:
                        parts = re.split(r'\s*\|\s*', line.strip())
                        if len(parts) < 5: continue
                        try:
                            date = parts[0]
                            action = parts[1]
                            coin = parts[2]
                            amount = float(parts[3].split('개')[0])
                            price = int(parts[4].split('원')[0].replace(',', ''))
                            reason = parts[5] if len(parts) > 5 else ""
                            trades.append({'date': date, 'action': action, 'coin': coin,
                                          'amount': amount, 'price': price, 'reason': reason})
                        except: continue
                df = pd.DataFrame(trades)
            except: pass

            if not df.empty:
                buys = df[df['action'] == 'BUY']
                sells = df[df['action'] == 'SELL']
                positions = {}
                for _, buy in buys.iterrows():
                    coin = buy['coin']
                    bdate = buy['date']
                    sold = sells[(sells['coin'] == coin) & (sells['date'] > bdate)]
                    if sold.empty:
                        current = pybithumb.get_current_price(coin)
                        if not current: current = buy['price']
                        pnl = (current / buy['price'] - 1) * 100
                        positions[coin] = {
                            'amount': buy['amount'], 'buy': buy['price'],
                            'current': current, 'pnl': pnl
                        }
                
                if positions:
                    for c, p in positions.items():
                        st.metric(
                            label=f"{c}",
                            value=f"{p['amount']:,.4f}개",
                            delta=f"{p['pnl']:+.2f}%"
                        )
                else:
                    st.info("보유 코인 없음")
            else:
                st.info("아직 거래 없음")

        # === 일자별 수익 ===
        with col2:
            st.subheader("일자별 수익")
            if not df.empty:
                sells = df[df['action'] == 'SELL']
                buys = df[df['action'] == 'BUY'].set_index(['coin', 'date'])
                profits = []
                for _, sell in sells.iterrows():
                    coin = sell['coin']
                    sdate = sell['date']
                    buy_match = buys.loc[(coin, slice(None))].sort_index().iloc[-1:]
                    if not buy_match.empty:
                        buy = buy_match.iloc[0]
                        profit = (sell['price'] - buy['price']) * sell['amount']
                        profits.append({'date': sdate[:10], 'profit': profit})
                
                if profits:
                    daily = pd.DataFrame(profits).groupby('date')['profit'].sum()
                    st.line_chart(daily.tail(7))
                else:
                    st.info("수익 기록 없음")
            else:
                st.info("아직 수익 없음")

        # === 실시간 로그 ===
        st.subheader("실시간 로그")
        try:
            with open('trader.log', 'r', encoding='utf-8') as f:
                lines = f.readlines()[-10:]
                log_text = "".join(lines)
                st.code(log_text, language=None)
        except:
            st.info("로그 없음")

    time.sleep(5)