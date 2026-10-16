"""The adapter: engine_seam.py drives the legacy engine (stdlib only); providers.py wraps it for SocioVerse2.

providers.py is not imported here, so the seam works in a Python that has no socioverse2 installed.
"""

from .engine_seam import LegacySeam, SeamPaused, legacy_root

__all__ = ["LegacySeam", "SeamPaused", "legacy_root"]
