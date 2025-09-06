from .base import *

DEBUG = False
ALLOWED_HOSTS = ["www.quizbackend.speedspro.us", "quizbackend.speedspro.us"]

# this is the path to the static folder where css, js and images are stored
STATIC_DIR = BASE_DIR / '/home/speebndt/quiz_backend/static/'

STATIC_URL = 'static/'
STATIC_ROOT = '/home/speebndt/quizbackend.speedspro.us/static/'

STATICFILES_DIRS = [
    STATIC_DIR,
]