"""Detector parameters. Fixed a priori (P022) before any evaluation and NOT tuned
on evaluation labels; changing any of them requires a new DETECTOR_VERSION."""

DETECTOR_VERSION = "excess-power-mad-v1"
REQUEST_FORMAT = "excess-power-request-v1"
FINDING_TYPE = "excess_consumption_deviation"

# Bounds (per section, independently) and body-size protection.
MAX_DEVICE_INTERVALS_PER_SECTION = 2000
MAX_ROOM_INTERVALS_PER_SECTION = 2000
MAX_BODY_BYTES = 16 * 1024 * 1024

# Comparability.
FULL_ON_TOLERANCE = 1e-9  # an interval is "fully on" when on_fraction >= 1 - tolerance
COMFORT_DEPENDENT_TYPES = ("ac", "refrigerator")  # power depends on room conditions
TEMP_BAND_C = 1.0  # comfort-dependent: reference room temperature within ±1.0 °C
OCCUPANCY_BAND = 1.0  # comfort-dependent: reference occupancy_avg within ±1.0 person

# Robust reference distribution.
MIN_REFERENCE_SUPPORT = 12  # distinct comparable reference intervals (identical duplicates removed)
MIN_REFERENCE_SPAN_HOURS = 2.0  # first reference start → last reference end
MAD_SCALE = 1.4826  # MAD → robust standard deviation (normal consistency)
THRESHOLD_K = 4.0
ABS_FLOOR_W = 10.0  # practical minimum deviation
REL_FLOOR = 0.10  # ... or 10 % of the reference median, whichever is larger

MAX_EXCLUSIONS_LISTED = 200
