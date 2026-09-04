"""Single conversion helper for FRED money-stock levels.

FRED WALCL / TGA / RRP / SWPT print in millions of dollars. The app works in
billions internally; display uses trillions with one decimal.
"""


def m_to_bn(millions):
    """$M → $B. Returns None for None."""
    return None if millions is None else millions / 1000.0


def fmt_T(bn):
    """$B → '$5.77T' with one decimal. 'n/a' for None."""
    return "n/a" if bn is None else f"${bn / 1000.0:.2f}T"


def fmt_B(bn, digits=2):
    """$B → '$0.13B'. 'n/a' for None."""
    return "n/a" if bn is None else f"${bn:,.{digits}f}B"


def to_T(vals):
    """Series in $B → $T for chart axes."""
    return [v / 1000.0 for v in vals]


def fmt_dB(bn, digits=0):
    """Signed $B delta, e.g. '-$38B/4w'. 'n/a' for None."""
    return "n/a" if bn is None else f"${bn:+,.{digits}f}B/4w"
