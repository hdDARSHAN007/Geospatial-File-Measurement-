"""CRS helpers: labels, projected-CRS selection, unit conversion, transformers."""
from __future__ import annotations

import math
from functools import lru_cache

from pyproj import CRS, Transformer

# Polar stereographic zones used where UTM is not defined (UTM covers 80S-84N).
EPSG_ARCTIC_POLAR = 3413  # WGS 84 / NSIDC Sea Ice Polar Stereographic North
EPSG_ANTARCTIC_POLAR = 3031  # WGS 84 / Antarctic Polar Stereographic


def crs_label(crs: CRS | None) -> str | None:
    """Human-readable CRS id: 'EPSG:4326' when known, else the CRS name."""
    if crs is None:
        return None
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.name


def select_projected_epsg(lon: float, lat: float) -> int:
    """Pick a metric CRS suited to a location given in degrees.

    * Between 80S and 84N: the UTM zone containing the point (WGS 84).
    * Beyond that: a polar stereographic CRS.

    UTM keeps distortion small (scale error <= ~0.1%) inside a zone, which is
    why it is a good default for survey-sized features.
    """
    if lat >= 84:
        return EPSG_ARCTIC_POLAR
    if lat < -80:
        return EPSG_ANTARCTIC_POLAR
    zone = int(math.floor((lon + 180.0) / 6.0)) % 60 + 1
    return (32600 if lat >= 0 else 32700) + zone


def linear_unit_factor(crs: CRS) -> float:
    """Metres per CRS axis unit (1.0 for metre-based CRSs, 0.3048 for feet...)."""
    try:
        factor = crs.axis_info[0].unit_conversion_factor
        return float(factor) if factor else 1.0
    except (IndexError, AttributeError):
        return 1.0


@lru_cache(maxsize=256)
def get_transformer(src_wkt: str, dst_epsg: int) -> Transformer:
    """Cached transformer. always_xy keeps coordinates in (lon, lat) order."""
    return Transformer.from_crs(
        CRS.from_wkt(src_wkt), CRS.from_epsg(dst_epsg), always_xy=True
    )
