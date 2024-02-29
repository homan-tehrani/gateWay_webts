import os
from dotenv import load_dotenv

# Site Url
AUTHENTICATION_SITE = "https://nativeauth.sirafgroup.com"
AUTHENTICATION_URL = f"{AUTHENTICATION_SITE}/user/auth/login_email/?site=project.sirafgroup.com"
GET_USER_URL = AUTHENTICATION_SITE + "/api/v1/user/userByToken/"

# URLs
CACHE_IP_ADDRESS = os.getenv('CACHE_IP_ADDRESS')
DB_NAME = os.getenv('DB_NAME')
CACHE_TIME = os.getenv('CACHE_TIME')
LOG_URL = os.getenv('LOG_URL')
