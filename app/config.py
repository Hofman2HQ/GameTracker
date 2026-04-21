import os
from dotenv import load_dotenv

load_dotenv()

RAWG_API_KEY = os.getenv('RAWG_API_KEY', '')
RAWG_BASE_URL = 'https://api.rawg.io/api'

DB_URL = os.getenv('DATABASE_URL', 'sqlite:///./gametracker.db')

STATUSES = ['PLAN', 'PLAYING', 'COMPLETED', 'DROPPED']
