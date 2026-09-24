"""Trend-detector parameters. Frozen (P024) before any evaluation and NOT tuned
on evaluation labels; changing any of them requires a new DETECTOR_VERSION."""

DETECTOR_VERSION = "gradual-power-trend-v1"
REQUEST_FORMAT = "drift-request-v1"
FINDING_TYPE = "sustained_upward_power_trend"
FINDING_TITLE = "Sustained upward power trend under matched observed conditions"
BUILDING_TIMEZONE = "Asia/Kolkata"  # contract v1: the only building timezone

# Context baselines (reference section only).
MIN_CONTEXT_REFERENCE_DAYS = 3  # distinct reference days behind each context median
COMFORT_TEMP_BIN_C = 1.0  # comfort-dependent context: 1 °C temperature bin + occupied yes/no

# Supported day (local calendar date).
MIN_DAY_OBSERVATIONS = 3
MIN_DAY_ON_SECONDS = 3600  # >= 1 h of fully-on comparable time

# Temporal support.
MIN_REFERENCE_DAYS = 5
MIN_REFERENCE_SPAN_DAYS = 7
MIN_EVALUATION_DAYS = 10
MIN_EVALUATION_SPAN_DAYS = 14
MIN_EVALUATION_DAY_COVERAGE = 0.5  # supported days / calendar days in the evaluation span

# Practical effect + persistence.
MIN_RELATIVE_CHANGE = 0.10  # Theil–Sen change over the evaluation span, relative to the reference level
MIN_ABSOLUTE_CHANGE_W = 10.0
FINAL_THIRD_ELEVATED_RATIO = 1.05  # days counted as elevated in the final third
FINAL_THIRD_ELEVATED_SHARE = 0.75

# Step / offset / spike classification.
STEP_MIN_SEGMENT_DAYS = 3
STEP_MIN_CHANGE = 0.10  # level change across the best split
STEP_MAX_WITHIN_SEGMENT = 0.03  # each segment's own Theil–Sen change must stay below this
OFFSET_MIN_RATIO = 1.10  # elevated median level without a trend
SPIKE_RATIO = 1.25  # isolated day at or above this is reported as a spike

MAX_EXCLUSIONS_LISTED = 200
