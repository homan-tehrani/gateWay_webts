import memcache
from utils.global_variables import CACHE_IP_ADDRESS

cache = memcache.Client([CACHE_IP_ADDRESS])
