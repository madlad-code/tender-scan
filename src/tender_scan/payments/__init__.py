"""M4 — open supplier-ledger loaders.

One loader per source, a shared output schema, and all normalisation inside
the loader. See `base.py` for the contract and the encoding rules.

Two of the three sources the spec names do not publish a supplier ledger as
open data: `opendata.sundsvall.se`, `catalog.sundsvall.se`, `data.sundsvall.se`
and `open.sundsvall.se` do not resolve, and Helsingborg's
`oppnadata.helsingborg.se` and `helsingborg.opendatasoft.com` return 404 with
nothing in the national catalogue. Those two have to go through module 3's
offentlighetsprincipen route instead. Göteborg and Västerås publish the same
ledger shape and stand in here.
"""

from tender_scan.payments.base import (
    Loader,
    LoaderError,
    RawRow,
    SourceFile,
    http_fetch,
    to_payments,
)
from tender_scan.payments.goteborg import GoteborgLoader
from tender_scan.payments.vasteras import VasterasLoader
from tender_scan.payments.vgr import VgrLoader

LOADERS: dict[str, type[Loader]] = {
    VgrLoader.key: VgrLoader,
    GoteborgLoader.key: GoteborgLoader,
    VasterasLoader.key: VasterasLoader,
}

__all__ = [
    "LOADERS",
    "GoteborgLoader",
    "Loader",
    "LoaderError",
    "RawRow",
    "SourceFile",
    "VasterasLoader",
    "VgrLoader",
    "http_fetch",
    "to_payments",
]
