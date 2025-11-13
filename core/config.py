# core/config.py
import os
from threading import Lock
from dotenv import load_dotenv
load_dotenv()

CONFIG = {
    "DROP_THRESHOLD": 0.05,
    "RISE_TARGET": 0.04,
    "STOP_LOSS": 0.015,
    "TRAILING_STOP": 0.03,
    "RSI_THRESHOLD": 40,
    "VOLUME_MULTIPLIER": 2.0,
    "position_size": 20000,

    'bithumb': {
        'api_key': os.getenv('BITHUMB_API_KEY'),
        'secret_key': os.getenv('BITHUMB_SECRET_KEY')
    },
    'trade': {
        'max_positions': 5
    },
    'kakao_token': os.getenv('KAKAO_TOKEN')
}

_lock = Lock()

def update_config(key, value):
    with _lock:
        if key in CONFIG:
            CONFIG[key] = value
        else:
            print(f"[CONFIG] 잘못된 키: {key}")

def get_config():
    with _lock:
        return CONFIG.copy()

# === 시장별 전략 ===
MARKET_STRATEGIES = {
    "상승장": {
        "DROP_THRESHOLD": 0.03,
        "RSI_THRESHOLD": 50,
        "VOLUME_MULTIPLIER": 1.3,
        "RISE_TARGET": 0.06
    },
    "하락장": {
        "DROP_THRESHOLD": 0.08,
        "RSI_THRESHOLD": 30,
        "VOLUME_MULTIPLIER": 2.5,
        "RISE_TARGET": 0.04,
        "STOP_LOSS": 0.02
    },
    "폭등장": {
        "DROP_THRESHOLD": 0.02,
        "RSI_THRESHOLD": 55,
        "VOLUME_MULTIPLIER": 3.0,
        "RISE_TARGET": 0.08
    },
    "횡보장": {
        "DROP_THRESHOLD": 0.04,
        "RSI_THRESHOLD": 45,
        "VOLUME_MULTIPLIER": 1.8,
        "RISE_TARGET": 0.05
    }
}        