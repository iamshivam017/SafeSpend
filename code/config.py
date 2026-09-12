"""Path configuration, resolved relative to this file (repo-root independent)."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = REPO_ROOT / "dataset"
MEDIA_IMAGES_DIR = DATASET_DIR / "media" / "images"

REQUESTS_CSV = DATASET_DIR / "requests.csv"
SAMPLE_REQUESTS_CSV = DATASET_DIR / "sample_requests.csv"
FINANCIAL_PROFILES_CSV = DATASET_DIR / "financial_profiles.csv"
FINANCIAL_EVENTS_CSV = DATASET_DIR / "financial_events.csv"
REQUEST_PAYMENT_OPTIONS_CSV = DATASET_DIR / "request_payment_options.csv"
EXCHANGE_RATES_CSV = DATASET_DIR / "exchange_rates.csv"
MESSAGES_CSV = DATASET_DIR / "messages.csv"
IMAGES_CSV = DATASET_DIR / "images.csv"
OUTPUT_TEMPLATE_CSV = DATASET_DIR / "output.csv"  # reference template only, never ground truth

OUTPUT_CSV = REPO_ROOT / "output.csv"  # final generated predictions (repo root, official)

ALL_DATASET_FILES = (REQUESTS_CSV, SAMPLE_REQUESTS_CSV, FINANCIAL_PROFILES_CSV,
                     FINANCIAL_EVENTS_CSV, REQUEST_PAYMENT_OPTIONS_CSV,
                     EXCHANGE_RATES_CSV, MESSAGES_CSV, IMAGES_CSV, OUTPUT_TEMPLATE_CSV)
