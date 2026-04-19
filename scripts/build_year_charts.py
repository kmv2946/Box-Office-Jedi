"""
Box Office Jedi — Build per-year charts (DEPRECATED)
====================================================
This script was an experiment that aggregated the weekend archive into
per-year domestic charts. It produced bad data because:

 1. It grouped films by the year of their earliest weekend-archive entry,
    which misclassifies December-release holdovers into the following year.
 2. For pre-2020 records where The Numbers didn't populate total_gross,
    it summed a film's weekend grosses as a fallback — which systematically
    underestimates lifetime gross for films with long legs.

The per-year charts in data/years/*.json are now filled in manually (one
canonical source per file). Do not run this script.
"""
import sys
print(__doc__)
print("This script is disabled. Edit data/years/<YYYY>.json directly.", file=sys.stderr)
sys.exit(1)
