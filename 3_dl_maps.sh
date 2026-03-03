#!/bin/bash
set -e

BBOX="-0.25,51.46,-0.05,51.57" # order: min_lon, min_lat, max_lon, max_lat
MAX_ZOOM=12
OSM_URL="https://download.geofabrik.de/europe/united-kingdom/england/greater-london-latest.osm.pbf"
JAR_URL="https://github.com/onthegomap/planetiler/releases/latest/download/planetiler.jar"

echo "--- Downloading tools and data..."
[ -f planetiler.jar ] || wget -O planetiler.jar "$JAR_URL"
[ -f london.osm.pbf ] || wget -O london.osm.pbf "$OSM_URL"

mkdir -p data/sources/
[ -f data/sources/london.osm.pbf ] || ln london.osm.pbf data/sources/london.osm.pbf

cat <<EOF > london.yaml
schema_name: London
attribution: '<a href="https://www.openstreetmap.org/copyright">&copy; OSM</a>'
sources:
  osm:
    type: osm
    url: "london.osm.pbf"
layers:
  - id: water
    features:
      - source: osm
        geometry: polygon
        include_when:
          natural: [water]
          waterway: [riverbank, dock]
          landuse: [reservoir, basin]
  - id: roads
    features:
      - source: osm
        geometry: line
        min_zoom: 7
        include_when:
          highway: [motorway, trunk]
      - source: osm
        geometry: line
        min_zoom: 9
        include_when:
          highway: [primary, secondary]
      - source: osm
        geometry: line
        min_zoom: 11
        include_when:
          highway: [tertiary]
      - source: osm
        geometry: line
        min_zoom: 12
        include_when:
          highway: [residential, road]
  - id: labels
    features:
      - source: osm
        geometry: point
        min_zoom: 9
        include_when:
          place: [city, town, suburb]
        attributes:
          - key: name
            tag_value: name
EOF

echo "--- Generating PMTiles..."
java -Xmx2g -jar planetiler.jar london.yaml \
  --output=london.pmtiles \
  --bounds="$BBOX" \
  --maxzoom=$MAX_ZOOM \
  --precision=1 \
  --simplify-tolerance=2 \
  --min-feature-size=2 \
  --exclude-ids \
  --force

echo "--- Written to: london.pmtiles"
echo "--- Done."