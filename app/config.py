import os
from dotenv import load_dotenv

load_dotenv()

RAWG_API_KEY = os.getenv('RAWG_API_KEY', '7038320ea036447db7d54309ac42cd54')
RAWG_BASE_URL = 'https://api.rawg.io/api'

DB_URL = os.getenv('DATABASE_URL', 'sqlite:///./gametracker.db')

STATUSES = ['PLAN', 'PLAYING', 'COMPLETED', 'DROPPED']
