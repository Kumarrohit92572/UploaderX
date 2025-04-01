import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot Configuration
API_ID = int(os.getenv("21567814"))
API_HASH = os.getenv("cd7dc5431d449fd795683c550d7bfb7e")
BOT_TOKEN = os.getenv("7531978030:AAG2-YGULattMW4I2SulEk1YSc99mvqLRmo")

# User Configuration
OWNER_ID = int(os.getenv("6126688051"))
AUTH_USERS = [int(user_id) for user_id in os.getenv("AUTH_USERS").split()]

# Worker Configuration
WORKERS = int(os.getenv("WORKERS", "6"))

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")

# Download Configuration
DOWNLOAD_DIR = "tmpvideos"
os.makedirs(DOWNLOAD_DIR, exist_ok=True) 
