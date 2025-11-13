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
from core.config import get_config, update_config, MARKET_STRATEGIES

st.set_page_config(page_title="뻥그 대시보드", layout="wide")
st.title("뻥그 전용 실시간 트레이딩 대시보드")

# === 봇 제어 ===
st.sidebar.header("봇 제어")
if st.sidebar.button("시작", type="primary"):
    subprocess.Popen(["python", "run_trader.py"])
    st.success("봇 시작!")
if st.sidebar.button("종료", type="secondary"):
    os.system("taskkill /f /im python.exe") if os.name == "nt" else os.system("pkill -f run_trader.py")
    st.warning("봇 종료!")

# === 시장별 전략 버튼 ===
st.sidebar.header("시장별 전략 (1클릭 적용)")
cols = st.sidebar.columns(2)
if cols[0].button("상승장"):
    for k, v in MARKET_STRATEGIES["상승장"].items():
        update_config(k, v)
    st.success("상승장 전략 적용!")
if cols[1].button("하락장"):
    for k, v in MARKET_STRATEGIES["하락장"].items():
        update_config(k, v)
    st.success("하락장 전략 적용!")
if cols[0].button("폭등장"):
    for k, v in MARKET_STRATEGIES["폭등장"].items():
        update_config(k, v)
    st.success("폭등장 전략 적용!")
if cols[1].button("횡보장"):
    for k, v in MARKET_STRATEGIES["횡보장"].items():
        update_config(k, v)
    st.success("횡보장 전략 적용!")

# === 수동 조정 ===
st.sidebar.header("수동 조정")
cfg = get_config()
with st.sidebar.form("manual_form"):
    drop = st.slider("급락 기준", 0.01, 0.20, cfg["DROP_THRESHOLD"], 0.01)
    rsi = st.slider("RSI 기준", 20, 60, cfg["RSI_THRESHOLD"], 1)
    vol = st.slider("거래량 배수", 1.0, 5.0, cfg["VOLUME_MULTIPLIER"], 0.1)
    rise = st.slider("수익 목표", 0.01, 0.15, cfg["RISE_TARGET"], 0.01)
    if st.form_submit_button("적용"):
        update_config("DROP_THRESHOLD", drop)
        update_config("RSI_THRESHOLD", rsi)
        update_config("VOLUME_MULTIPLIER", vol)
        update_config("RISE_TARGET", rise)
        st.success("수동 설정 적용!")

# === 실시간 대시보드 ===
placeholder = st.empty()
while True:
    with placeholder.container():
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("보유 코인")
            # 로그 파싱 생략 (기존 코드 유지)
            st.info("보유 코인 없음")
        with col2:
            st.subheader("시장 상태")
            st.metric("현재 전략", "상승장")
        st.subheader("실시간 로그")
        try:
            with open('trader.log', 'r', encoding='utf-8') as f:
                lines = f.readlines()[-100:]  # 최근 100줄 (성능 UP)

            log_text = "".join(lines)

            # 고정 높이 + 스크롤바 + 모노스페이스 폰트
            st.markdown(
                f"""
                <div style="
                    height: 400px;
                    overflow-y: auto;
                    padding: 12px;
                    background-color: #1e1e1e;
                    border-radius: 10px;
                    font-family: 'Courier New', monospace;
                    font-size: 13px;
                    color: #d4d4d4;
                    border: 1px solid #444;
                    white-space: pre;
                    line-height: 1.4;
                ">
                {''.join([line.replace('<', '&lt;').replace('>', '&gt;') for line in lines])}
                </div>
                """,
                unsafe_allow_html=True
            )
        except: pass
    time.sleep(5)

