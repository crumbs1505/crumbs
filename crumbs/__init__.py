"""crumbs - local, token-efficient cross-repo context for LLMs.

crumbs indexes repositories into compact "context crumbs" (file maps and symbol
signatures, not full file bodies) stored locally. An assistant can query these
crumbs to understand many repos at once without reading -- and paying tokens for
-- the entire source tree.
"""

__version__ = "0.3.1"
