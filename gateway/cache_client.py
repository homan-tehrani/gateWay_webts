import memcache
from utils.global_variables import CACHE_IP_ADDRESS

memcache_client = memcache.Client([CACHE_IP_ADDRESS])
