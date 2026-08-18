"""GCPM: GEOS-Chem PM2.5 calculator.

The implementation lives in `core`; this module names the public surface so
`from GCPM import AerosolCalculator` keeps working and internals stay reachable
at `GCPM.core` for anyone who needs them.
"""
from .core import (DEFAULTS, SPECIES_DB, AerosolCalculator, AeroMassFine,
                   AOD_Total)

__all__ = ["AerosolCalculator", "AeroMassFine", "AOD_Total",
           "SPECIES_DB", "DEFAULTS"]

__version__ = "0.1.0"
