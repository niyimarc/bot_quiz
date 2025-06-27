from .base import *

DEBUG = False
ALLOWED_HOSTS = ["www.quiz.fafkiddies.com", "quiz.fafkiddies.com"]

# this is the path to the static folder where css, js and images are stored
STATIC_DIR = BASE_DIR / '/home/fafkrlee/nanskim_frontend/static/'

STATIC_URL = 'static/'
STATIC_ROOT = '/home/fafkrlee/quiz.fafkiddies.com/static/'

STATICFILES_DIRS = [
    STATIC_DIR,
]