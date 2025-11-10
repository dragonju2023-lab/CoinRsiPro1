# core/config.py
import os
from dotenv import load_dotenv
load_dotenv()

CONFIG = {
    'bithumb': {
        'api_key': os.getenv('BITHUMB_API_KEY'),
        'secret_key': os.getenv('BITHUMB_SECRET_KEY')
    },
    'trade': {
        'position_size': 20000,
        'max_positions': 5
    },
    'kakao_token': os.getenv('KAKAO_TOKEN')
}