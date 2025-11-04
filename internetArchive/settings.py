import os
from os.path import join, dirname
from dotenv import load_dotenv

dotenv_path = join(dirname(__file__), ".env")
load_dotenv(dotenv_path)

INTERNET_ARCHIVE_TOKENS = list(
    filter(
        lambda x: x != "" and ":" in x,
        os.environ.get("INTERNET_ARCHIVE_TOKENS", "").split(","),
    )
)
assert (
    len(INTERNET_ARCHIVE_TOKENS) > 0
), "You must provide at least one Internet Archive token"
ADDITIONAL_SAVE_HOSTS = list(
    filter(lambda x: x != "", os.environ.get("ADDITIONAL_HOSTS", "").split(","))
)
CORE_API_HOST = "https://core.acm.illinois.edu"
MAX_REQUESTS_PER_WINDOW = 12
WINDOW_SECONDS = 60.0
