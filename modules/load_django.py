import os
import sys
import django

PROJECT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

PROJECT_NAME = "ighcom_project"

sys.path.insert(0, PROJECT_PATH)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"{PROJECT_NAME}.settings")

django.setup()

