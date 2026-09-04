"""Static print calendar: upcoming official releases. Editable list, no scraping.

Sources (confirm on official calendars before acting):
  NFP Sep 4      — BLS Employment Situation, first Friday
  CPI Sep 11     — BLS CPI release calendar
  FOMC Sep 15-16 — Federal Reserve meeting calendar (statement + SEP + presser)
  BOJ Sep 17-18  — Bank of Japan MPM schedule
  Clarity cloture Sep 15 — UNOFFICIAL, procedural chatter only; kept labeled as such
"""

PRINTS = [
    ("2026-09-04", "NFP"),
    ("2026-09-11", "CPI"),
    ("2026-09-15", "FOMC (starts; decision Sep 16)"),
    ("2026-09-15", "Clarity cloture (unofficial)"),
    ("2026-09-17", "BOJ (starts; decision Sep 18)"),
]
