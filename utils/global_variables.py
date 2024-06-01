import os
from dotenv import load_dotenv

# Site Url
AUTHENTICATION_SITE = os.getenv('AUTHENTICATION_SITE')
AUTHENTICATION_URL = f"{AUTHENTICATION_SITE}/user/auth/login_email/?site=project.sirafgroup.com"
GET_USER_URL = AUTHENTICATION_SITE + "/api/v1/user/userByToken/"

# URLs
CACHE_IP_ADDRESS = os.getenv('CACHE_IP_ADDRESS')
DB_NAME = os.getenv('DB_NAME')
CACHE_TIME = os.getenv('CACHE_TIME')
LOG_URL = os.getenv('LOG_URL')


# Rabbitmq 
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST')
RABBITMQ_PORT = os.getenv('RABBITMQ_PORT')
RABBITMQ_USERNAME = os.getenv('RABBITMQ_USERNAME')
RABBITMQ_PASSWORD = os.getenv('RABBITMQ_PASSWORD')
RABBITMQ_VHOST = os.getenv('RABBITMQ_VHOST')

