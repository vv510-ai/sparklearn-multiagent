"""Compatibility entrypoint; vocabulary and other recalls share one scheduler."""
from .review_scheduler import RATINGS, SCHEDULER, VERSION, schedule

__all__ = ["RATINGS", "SCHEDULER", "VERSION", "schedule"]
