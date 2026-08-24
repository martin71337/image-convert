"""The only layer that imports Pillow.

Everything above this package works in paths, records and enums. That boundary
is what lets the conversion engine be tested without a decoder present, and what
would let a pathway be served by something other than Pillow later without the
job runner or the interface noticing.
"""
