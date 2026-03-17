# tolerable_zoopla

This repository provides a set of scripts to scrape property listings from Zoopla and generate a standalone HTML map for viewing them.

### Why this exists

Zoopla imposes artificial restrictions on its map view, such as only displaying 25 properties regardless of zoom level, in a (failed) attempt to prevent scraping. This is a pain in the ass.

These scripts allow you to bypass those restrictions by scraping all listings and displaying them on a lightweight map. All counted, the HTML it produces - which includes both the scraped listings and the map tiles - should be under 1MB.

There are no API limits, no tracking, and no 25-pin cap. You can see every property at once.

### How to use it

1. **Scrape:** Run `python 1_scrape.py` to scrape Zoopla. This requires supplying a `BUILD_ID` and `COOKIE` fetched from your browser. (For the `BUILD_ID` you'll need to open the map browser, pan or zoom a little, click 'show properties in this area', and look at the `GET /_next/...` request that results.)
2. **Compress:** Run `python pif.py` to turn your JSON data into the binary format. This strips away all the fluff, leaving only the essential facts: price, location, bedrooms, and bathrooms.
3. **Download maps:** Run `sh 3_dl_maps.sh` (requires Java 21) to download a lightweight map of London, stripped of unnecessary stuff like building bound polygons. The entire map is roughly 450KB, allowing it to load near-instantly and be used on low-resource mobile devices.
4. **View:** Everything is combined into a single HTML file that works in any browser without requiring an active connection to a property portal.

### Requirements

- Python 3.x
- Java 21+ (to build the custom map file)
- `wget`

### Laws

You will notice that `listings.json` is not included in this repository. 

Raw JSON files from property portals often contain proprietary descriptions and metadata that cross into copyright violation. To stay on the right side of the law, I have only included `listings.bin`. This file is a purely mathematical, lossy abstraction of the data. It contains no human-readable text and no descriptions—just the coordinates and basic stats required to put a dot on a map.

