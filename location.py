"""Location capture: one-time browser GPS, map click, and manual coordinates.

GPS describes the observer's device, not necessarily the defect, so the user must
confirm the pin. Manual entry always works, even if the GPS component fails.
"""
from __future__ import annotations

from typing import Optional

import folium
import streamlit as st
from streamlit_folium import st_folium

from report import LocationInfo

try:
    from streamlit_geolocation import streamlit_geolocation

    GEO_AVAILABLE = True
except Exception:  # component missing or broken -> manual entry only
    GEO_AVAILABLE = False

UCSD_CENTER = (32.8801, -117.2340)
# Clearly labeled demo value (UCSD Library Walk area). Never presented as a real report.
DEMO_COORD = (32.879500, -117.237000)

_DEFAULTS = {
    "loc_lat": None,
    "loc_lon": None,
    "loc_accuracy": None,
    "loc_source": None,
    "location_confirmed": False,
    "last_gps_fix": None,
    "last_map_click": None,
}


def init_state() -> None:
    for k, v in _DEFAULTS.items():
        st.session_state.setdefault(k, v)


def valid_coords(lat: Optional[float], lon: Optional[float]) -> bool:
    return (
        isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        and -90 <= lat <= 90 and -180 <= lon <= 180
    )


def _set_pin(lat: float, lon: float, source: str, accuracy: Optional[float] = None) -> None:
    """Only call before the coordinate widgets render (or from a callback)."""
    ss = st.session_state
    ss.loc_lat = round(float(lat), 6)
    ss.loc_lon = round(float(lon), 6)
    ss.loc_source = source
    ss.loc_accuracy = accuracy
    ss.location_confirmed = False  # any move requires re-confirmation


def _on_manual_change() -> None:
    ss = st.session_state
    ss.loc_source = "manual"
    ss.loc_accuracy = None
    ss.location_confirmed = False


def _use_demo() -> None:
    _set_pin(*DEMO_COORD, source="demo_test_coordinate")


def _clear() -> None:
    ss = st.session_state
    ss.loc_lat = ss.loc_lon = ss.loc_accuracy = ss.loc_source = None
    ss.location_confirmed = False


def _gps_section() -> None:
    st.markdown("**Use my location (optional)**")
    st.caption(
        "Tap the 📍 button once to share your device's current position. Location is "
        "requested only when you tap, used only for this report, and not tracked."
    )
    if not GEO_AVAILABLE:
        st.info("Automatic GPS is unavailable here. Use the map or enter coordinates below.")
        return
    try:
        fix = streamlit_geolocation()
    except Exception:
        st.info("Automatic GPS failed to load. Use the map or enter coordinates below.")
        return
    lat = fix.get("latitude") if isinstance(fix, dict) else None
    lon = fix.get("longitude") if isinstance(fix, dict) else None
    acc = fix.get("accuracy") if isinstance(fix, dict) else None
    if valid_coords(lat, lon):
        acc = float(acc) if isinstance(acc, (int, float)) and acc >= 0 else None
        key = (lat, lon, acc)
        if key != st.session_state.last_gps_fix:  # apply each new fix exactly once
            st.session_state.last_gps_fix = key
            _set_pin(lat, lon, source="gps", accuracy=acc)
    st.caption(
        "If nothing happens after tapping, location permission may be blocked — "
        "use the map or the fields below instead."
    )


def _map_section() -> None:
    ss = st.session_state
    has_pin = valid_coords(ss.loc_lat, ss.loc_lon)
    center = (ss.loc_lat, ss.loc_lon) if has_pin else UCSD_CENTER
    st.markdown("**Tap the map to place the issue pin**")
    if not has_pin:
        st.caption("Map is centered on UC San Diego for convenience; no location is set yet.")
    fmap = folium.Map(location=center, zoom_start=18 if has_pin else 15, control_scale=True)
    if has_pin:
        folium.Marker(center, tooltip="Issue location",
                      icon=folium.Icon(color="red", icon="info-sign")).add_to(fmap)
        if ss.loc_accuracy:
            folium.Circle(center, radius=ss.loc_accuracy, color="#3186cc",
                          fill=True, fill_opacity=0.1).add_to(fmap)
    try:
        out = st_folium(fmap, key="issue_map", height=320, use_container_width=True,
                        returned_objects=["last_clicked"])
    except Exception:
        st.info("The map could not load. Enter coordinates below.")
        return
    click = (out or {}).get("last_clicked")
    if click and valid_coords(click.get("lat"), click.get("lng")):
        key = (click["lat"], click["lng"])
        if key != ss.last_map_click:  # only react to a genuinely new click
            ss.last_map_click = key
            _set_pin(click["lat"], click["lng"], source="map_click")
            st.rerun()


def render_location_picker() -> LocationInfo:
    init_state()
    ss = st.session_state
    _gps_section()
    _map_section()

    st.markdown("**Or enter coordinates**")
    c1, c2 = st.columns(2)
    with c1:
        st.number_input("Latitude", min_value=-90.0, max_value=90.0, step=0.00001,
                        format="%.6f", key="loc_lat", on_change=_on_manual_change,
                        placeholder="e.g. 32.8801")
    with c2:
        st.number_input("Longitude", min_value=-180.0, max_value=180.0, step=0.00001,
                        format="%.6f", key="loc_lon", on_change=_on_manual_change,
                        placeholder="e.g. -117.2340")
    b1, b2 = st.columns(2)
    b1.button("Use demo test coordinate", on_click=_use_demo, width="stretch",
              help="Labeled test value for demos only — not a real defect location.")
    b2.button("Clear location", on_click=_clear, width="stretch")

    has_pin = valid_coords(ss.loc_lat, ss.loc_lon)
    if has_pin:
        source_label = {
            "gps": "device GPS (your position — move the pin if the defect is elsewhere)",
            "map_click": "map tap",
            "manual": "typed coordinates",
            "demo_test_coordinate": "DEMO TEST COORDINATE — not a real location",
        }.get(ss.loc_source, "unknown")
        acc = f" · accuracy ±{ss.loc_accuracy:.0f} m" if ss.loc_accuracy else ""
        st.caption(f"Pin: {ss.loc_lat:.6f}, {ss.loc_lon:.6f} · source: {source_label}{acc}")
        if ss.loc_source == "demo_test_coordinate":
            st.warning("Demo coordinate in use. Replace it with the real location before reporting.")
    else:
        ss.location_confirmed = False
        st.caption("No location set. Use GPS, tap the map, or type coordinates.")

    st.checkbox("Confirm This Issue Location", key="location_confirmed", disabled=not has_pin,
                help="GPS shows where you are; confirm the pin marks the defect itself.")

    if not has_pin:
        return LocationInfo()
    return LocationInfo(
        latitude=ss.loc_lat,
        longitude=ss.loc_lon,
        accuracy_meters=ss.loc_accuracy,
        source=ss.loc_source,
        user_confirmed=bool(ss.location_confirmed),
    )
