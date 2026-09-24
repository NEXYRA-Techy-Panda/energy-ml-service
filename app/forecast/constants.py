"""Fixed baseline parameters. Chosen a priori (P013) and NOT tuned on any
holdout; changing them requires a new BASELINE_VERSION."""

BASELINE_VERSION = "hourly-profile-median-v1"
METHOD = "statistical_baseline"

HORIZONS = ("next_24h", "next_7d", "next_calendar_month")

# Contract bound (API.md): at most 2,160 hourly history points (90 days).
MAX_HISTORY_POINTS = 2160
MAX_BODY_BYTES = 2 * 1024 * 1024

# v1 building timezone (CONTRACT.md §1: Asia/Kolkata is the only value).
SUPPORTED_TIMEZONES = ("Asia/Kolkata",)

# Eligibility: minimum OBSERVED (non-missing) history hours per horizon.
MIN_OBSERVED_HOURS = {
    "next_24h": 7 * 24,  # one full week
    "next_7d": 14 * 24,  # two weeks
    "next_calendar_month": 28 * 24,  # four weeks
}

# Minimum observations required at each level of the fallback hierarchy.
MIN_SUPPORT = {
    "weekday_hour": 2,  # same local ISO weekday and local hour
    "day_class_hour": 3,  # same working/non-working class and local hour
    "hour_of_day": 3,  # same local hour, any day (disclosed fallback)
}

# Last observation older than this before the origin → STALE_HISTORY warning.
STALE_AFTER_HOURS = 7 * 24
