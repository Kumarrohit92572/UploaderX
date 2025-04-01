import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot Configuration
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# User Configuration
OWNER_ID = int(os.getenv("OWNER_ID"))
AUTH_USERS = [int(user_id) for user_id in os.getenv("AUTH_USERS").split()]

# Worker Configuration
WORKERS = int(os.getenv("WORKERS", "6"))

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")

# Download Configuration
DOWNLOAD_DIR = "tmpvideos"
os.makedirs(DOWNLOAD_DIR, exist_ok=True) 