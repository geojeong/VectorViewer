"""VectorViewer - open a vector dataset in the default web browser.

This file intentionally contains the whole application.  The release executable is
expected to be registered as the handler for .shp, .gpkg and .geojson files.
"""

from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import uuid
import webbrowser


APP_NAME = "VectorViewer"
SUPPORTED_EXTENSIONS = {".shp", ".gpkg", ".geojson"}


class VectorViewerError(Exception):
    """An error that can be shown directly to the user."""


def _show_error(message: str) -> None:
    """Show an error without adding a GUI toolkit to the release executable."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
            return
        except Exception:
            pass
    print(f"{APP_NAME}: {message}", file=sys.stderr)


def _import_geospatial_modules():
    try:
        import geopandas
        import pyogrio
    except ImportError as exc:
        raise VectorViewerError(
            "필수 패키지가 없습니다. 다음 명령으로 설치해 주세요.\n\n"
            "python -m pip install geopandas pyogrio shapely pyproj"
        ) from exc
    return geopandas, pyogrio


def _layer_names(path: Path, pyogrio) -> list[str | None]:
    if path.suffix.lower() != ".gpkg":
        return [None]

    try:
        rows = pyogrio.list_layers(path)
    except Exception as exc:
        raise VectorViewerError(f"GeoPackage의 레이어 목록을 읽지 못했습니다.\n{exc}") from exc

    # list_layers returns pairs of (layer name, geometry type).  Attribute-only
    # tables are not map layers, so they are deliberately excluded.
    names = [str(row[0]) for row in rows if len(row) > 1 and row[1] is not None]
    if not names:
        raise VectorViewerError("표시할 공간 레이어가 GeoPackage에 없습니다.")
    return names


def _json_safe(value):
    """Replace non-standard NaN/Infinity values before embedding JSON in HTML."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _read_layers(path: Path) -> tuple[list[dict], int]:
    geopandas, pyogrio = _import_geospatial_modules()
    output: list[dict] = []
    feature_count = 0

    for layer_name in _layer_names(path, pyogrio):
        try:
            frame = pyogrio.read_dataframe(path, layer=layer_name)
        except Exception as exc:
            label = layer_name or path.name
            raise VectorViewerError(f"'{label}' 레이어를 읽지 못했습니다.\n{exc}") from exc

        if not isinstance(frame, geopandas.GeoDataFrame) or frame.geometry.name not in frame:
            continue

        frame = frame.loc[~frame.geometry.isna()].copy()
        if frame.crs is None:
            if path.suffix.lower() == ".geojson":
                # RFC 7946 GeoJSON coordinates use WGS 84 longitude/latitude.
                frame = frame.set_crs("EPSG:4326")
            else:
                raise VectorViewerError(
                    f"'{layer_name or path.name}' 레이어에 좌표계 정보가 없습니다."
                )

        try:
            if not frame.crs.equals("EPSG:4326"):
                frame = frame.to_crs("EPSG:4326")
            collection = json.loads(frame.to_json(drop_id=True))
        except Exception as exc:
            label = layer_name or path.name
            raise VectorViewerError(f"'{label}' 레이어를 WGS 84로 변환하지 못했습니다.\n{exc}") from exc

        collection = _json_safe(collection)
        count = len(collection.get("features", []))
        feature_count += count
        output.append(
            {
                "name": layer_name or path.stem,
                "data": collection,
            }
        )

    if not output:
        raise VectorViewerError("파일에서 표시할 벡터 피처를 찾지 못했습니다.")
    return output, feature_count


def _javascript_json(value) -> str:
    """Serialize data so it is safe inside an inline script element."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _build_html(source: Path, layers: list[dict], feature_count: int) -> str:
    payload = _javascript_json(
        {
            "fileName": source.name,
            "featureCount": feature_count,
            "layers": layers,
        }
    )
    page_title = html.escape(f"{source.name} - {APP_NAME}", quote=True)

    template = r'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__PAGE_TITLE__</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
  <style>
    html, body, #map { width: 100%; height: 100%; margin: 0; }
    body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
    .viewer-info {
      position: fixed; z-index: 1000; left: 12px; bottom: 24px;
      max-width: min(520px, calc(100vw - 48px)); padding: 9px 12px;
      border-radius: 7px; background: rgba(255,255,255,.94);
      box-shadow: 0 1px 6px rgba(0,0,0,.28); color: #202124; font-size: 13px;
    }
    .viewer-info strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .attribute-wrap { max-height: 300px; overflow: auto; }
    .attribute-table { border-collapse: collapse; min-width: 260px; font-size: 12px; }
    .attribute-table th, .attribute-table td {
      padding: 5px 7px; border-bottom: 1px solid #e1e4e8; text-align: left;
      vertical-align: top; overflow-wrap: anywhere;
    }
    .attribute-table th { width: 34%; background: #f6f8fa; color: #333; }
    .empty-properties { color: #666; padding: 4px 0; }
    .leaflet-popup-content { margin: 11px 13px; }
  </style>
</head>
<body>
  <div id="map" aria-label="벡터 지도"></div>
  <div class="viewer-info">
    <strong id="file-name"></strong>
    <span id="feature-count"></span>
  </div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
          integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <script>
    "use strict";
    const viewerData = __VECTOR_DATA__;
    const colors = ["#d81b60", "#1e88e5", "#43a047", "#fb8c00", "#8e24aa", "#00897b"];
    const map = L.map("map", { preferCanvas: true }).setView([20, 0], 2);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function displayValue(value) {
      if (value === null || value === undefined) return "";
      if (typeof value === "object") return JSON.stringify(value);
      return String(value);
    }

    function popupHtml(properties) {
      const entries = Object.entries(properties || {});
      if (!entries.length) return '<div class="empty-properties">속성값이 없습니다.</div>';
      const rows = entries.map(([key, value]) =>
        `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(displayValue(value))}</td></tr>`
      ).join("");
      return `<div class="attribute-wrap"><table class="attribute-table">${rows}</table></div>`;
    }

    const overlays = {};
    const allBounds = L.latLngBounds([]);
    viewerData.layers.forEach((item, index) => {
      const color = colors[index % colors.length];
      const layer = L.geoJSON(item.data, {
        style: { color, weight: 3, opacity: .9, fillColor: color, fillOpacity: .22 },
        pointToLayer: (_feature, latlng) => L.circleMarker(latlng, {
          radius: 6, color: "#fff", weight: 1.5, fillColor: color, fillOpacity: .95
        }),
        onEachFeature: (feature, featureLayer) => {
          featureLayer.bindPopup(() => popupHtml(feature.properties), { maxWidth: 560 });
        }
      }).addTo(map);
      overlays[item.name] = layer;
      const bounds = layer.getBounds();
      if (bounds.isValid()) allBounds.extend(bounds);
    });

    if (Object.keys(overlays).length > 1) L.control.layers(null, overlays, { collapsed: false }).addTo(map);
    if (allBounds.isValid()) map.fitBounds(allBounds, { padding: [28, 28], maxZoom: 17 });
    document.getElementById("file-name").textContent = viewerData.fileName;
    document.getElementById("feature-count").textContent = `${viewerData.featureCount.toLocaleString()}개 피처`;
  </script>
</body>
</html>
'''
    return template.replace("__PAGE_TITLE__", page_title).replace("__VECTOR_DATA__", payload)


def _write_page(contents: str) -> Path:
    output_dir = Path(tempfile.gettempdir()) / APP_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    page = output_dir / f"{uuid.uuid4().hex}.html"
    page.write_text(contents, encoding="utf-8")
    return page


def _open_page(page: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(page))  # type: ignore[attr-defined]
            return
        if webbrowser.open_new_tab(page.as_uri()):
            return
    except Exception as exc:
        raise VectorViewerError(f"웹 브라우저를 열지 못했습니다.\n{exc}") from exc
    raise VectorViewerError("기본 웹 브라우저를 찾지 못했습니다.")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv

    # A release executable is a file handler, not a standalone interactive app.
    if not arguments:
        return 0
    if len(arguments) != 1:
        _show_error("한 번에 하나의 벡터 파일만 열 수 있습니다.")
        return 2

    source = Path(arguments[0]).expanduser()
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        _show_error("지원 형식은 SHP, GPKG, GeoJSON입니다.")
        return 2
    if not source.is_file():
        _show_error(f"파일을 찾을 수 없습니다.\n{source}")
        return 2

    try:
        layers, feature_count = _read_layers(source)
        page = _write_page(_build_html(source, layers, feature_count))
        _open_page(page)
    except VectorViewerError as exc:
        _show_error(str(exc))
        return 1
    except Exception as exc:
        _show_error(f"예상하지 못한 오류가 발생했습니다.\n{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
