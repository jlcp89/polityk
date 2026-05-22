"""ETL parsers for Memoria Electoral PDFs and other tabular sources.

Per ADR-004 (Python owns heavy parsing) and ADR-017 (polls schema). The 2019
Memoria is the first Memoria Electoral cycle wired through this package;
2007/2011/2015 parsers (issue #21) reuse the typed-error contract defined in
:mod:`pipeline.parsers.memoria_2019`. Poll PDFs (e.g. CID Gallup) are parsed
into ``polls`` + ``poll_responses`` rows by :mod:`pipeline.parsers.cid_gallup`.
"""

__all__: tuple[str, ...] = ()
