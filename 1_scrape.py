from curl_cffi import requests
from bs4 import BeautifulSoup
import json
import os
import polyline
import random
import re
import sys
import time

BOUNDS = {
    "north": 51.62,
    "east": 0.0190, 
    "south": 51.4400,
    "west": -0.2830
}

# Fetch these using dev tools in your browser.
BUILD_ID = "xxx" 
COOKIE_STRING = "xxx"

OUTPUT_FILE = "listings.json"
SLUG = "london"
MAX_RESULTS_PER_BOX = 200  

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0"

HTML_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": f"https://www.zoopla.co.uk/to-rent/map/property/{SLUG}/",
    "Cookie": COOKIE_STRING.strip().replace('\n', '')
}

API_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": f"https://www.zoopla.co.uk/to-rent/map/property/{SLUG}/",
    "Cookie": COOKIE_STRING.strip().replace('\n', ''),
    "x-nextjs-data": "1"
}

seen_ids = set()
total_captured = 0
file_handle = None

def log(msg):
    sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    sys.stderr.flush()

def get_polyenc(n, s, e, w):
    points = [(n, w), (n, e), (s, e), (s, w), (n, w)]
    return polyline.encode(points)

def fetch_deep_property_data(property_url):
    try:
        time.sleep(random.uniform(1.2, 2.5))
        
        res = requests.get(property_url, headers=HTML_HEADERS, impersonate="firefox133", allow_redirects=True)
        
        if res.status_code != 200:
            log(f"      [!] HTTP {res.status_code} fetching HTML")
            return None
            
        if "<title>Just a moment...</title>" in res.text or "cf-turnstile" in res.text:
            log(f"      [!] CLOUDFLARE CHALLENGE BLOCK DETECTED on HTML fetch.")
            return None

        deep_data = {
            "full_description_raw": "",
            "full_description_clean": "",
            "bullet_features": [],
            "floor_plan_urls": []
        }

        html_text = res.text

        # STRATEGY 1: Next.js app router (rebuild RSC chunks)
        chunks = re.findall(r'self\.__next_f\.push\(\[\d+,\s*"(.*?)"\]\)', html_text)
        if chunks:
            rsc_payload = ""
            for chunk in chunks:
                try:
                    rsc_payload += json.loads(f'"{chunk}"')
                except: pass
            
            desc_match = re.search(r'"detailedDescription":"((?:[^"\\]|\\.)*)"', rsc_payload)
            if desc_match:
                try:
                    raw_desc = json.loads('"' + desc_match.group(1) + '"')                    
                    if str(raw_desc).startswith('$') and len(str(raw_desc)) < 10:
                        raw_desc = ""
                    
                    if raw_desc:
                        deep_data["full_description_raw"] = raw_desc
                        clean = re.sub(r'<br\s*/?>', '\n', raw_desc)
                        clean = re.sub(r'<[^>]+>', '', clean)
                        deep_data["full_description_clean"] = clean.strip()
                except: pass
            
            feat_match = re.search(r'"features":\{"bullets":(\[.*?\])(?:,"|\})', rsc_payload)
            if feat_match:
                try:
                    deep_data["bullet_features"] = json.loads(feat_match.group(1))
                except: pass

            fp_match = re.search(r'"floorPlan":\{"image":(\[.*?\])(?:,"|\})', rsc_payload)
            if fp_match:
                try:
                    fps = json.loads(fp_match.group(1))
                    deep_data["floor_plan_urls"] = [f"https://lid.zoocdn.com/1024/768/{fp['filename']}" for fp in fps if 'filename' in fp]
                except: pass

        # STRATEGY 2: Legacy Next.js Pages (__NEXT_DATA__)
        if not deep_data["full_description_clean"]:
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    details = data.get('props', {}).get('pageProps', {}).get('listingDetails', {})
                    if details:
                        raw_desc = details.get('detailedDescription', '')
                        
                        if not (str(raw_desc).startswith('$') and len(str(raw_desc)) < 10):
                            deep_data["full_description_raw"] = raw_desc
                            clean = re.sub(r'<br\s*/?>', '\n', raw_desc)
                            clean = re.sub(r'<[^>]+>', '', clean)
                            deep_data["full_description_clean"] = clean.strip()
                            
                        deep_data["bullet_features"] = details.get('features', [])
                        fps = details.get('floorPlan', [])
                        if fps:
                            deep_data["floor_plan_urls"] = [f"https://lid.zoocdn.com/1024/768/{fp['filename']}" for fp in fps if 'filename' in fp]
                except: pass

        # STRATEGY 3: SEO fallback (best for the essay if Next.js abstracted it to a pointer)
        if not deep_data["full_description_clean"]:
            soup = BeautifulSoup(html_text, 'html.parser')
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    ld_data = json.loads(script.string)
                    if isinstance(ld_data, list):
                        for item in ld_data:
                            if item.get('@type') in ['RealEstateListing', 'Residence']:
                                deep_data["full_description_clean"] = item.get('description', '')
                                deep_data["full_description_raw"] = item.get('description', '')
                                break
                    elif isinstance(ld_data, dict):
                        if ld_data.get('@type') in ['RealEstateListing', 'Residence']:
                            deep_data["full_description_clean"] = ld_data.get('description', '')
                            deep_data["full_description_raw"] = ld_data.get('description', '')
                except: pass

        return deep_data

    except Exception as e:
        log(f"      [!] Deep fetch exception: {e}")
        return None

def fetch_box(n, s, e, w, depth=0):
    global total_captured
    poly_code = get_polyenc(n, s, e, w)
    
    url = f"https://www.zoopla.co.uk/_next/data/{BUILD_ID}/to-rent/map/property/{SLUG}.json"
    
    params = {
        "price_frequency": "per_month",
        "price_max": "3000",
        "search_source": "to-rent",
        "radius": "0",
        "polyenc": poly_code,
        "hidePoly": "true",
        "search-path": ["property", SLUG]
    }

    try:
        time.sleep(random.uniform(1.0, 2.0))
        response = requests.get(url, headers=API_HEADERS, params=params, impersonate="firefox133")
        
        if response.status_code != 200:
            log(f"{'  ' * depth}[!] Map API HTTP {response.status_code}. Bad Build ID or Cookies.")
            return

        data = response.json()
        props = data.get('pageProps', {})
        
        pagination = props.get('pagination', {})
        total_results = pagination.get('totalResults')
        if total_results is None:
            total_results = props.get('analyticsTaxonomy', {}).get('pagination', {}).get('totalResults', 0)
        
        listings = props.get('listings', [])

        log(f"{'  ' * depth}Box bounds (depth {depth}): {total_results} properties in area.")

        if total_results > MAX_RESULTS_PER_BOX and depth < 6:
            log(f"{'  ' * depth}-> Subdividing into 4...")
            mid_lat = (n + s) / 2.0
            mid_lng = (e + w) / 2.0
            
            fetch_box(n, mid_lat, mid_lng, w, depth + 1) # NW
            fetch_box(n, mid_lat, e, mid_lng, depth + 1) # NE
            fetch_box(mid_lat, s, mid_lng, w, depth + 1) # SW
            fetch_box(mid_lat, s, e, mid_lng, depth + 1) # SE
        else:
            new_in_box = 0
            for index, item in enumerate(listings):
                lid = item.get('listingId')
                
                if lid and lid not in seen_ids:
                    seen_ids.add(lid)
                    
                    gallery = item.get('gallery', [])
                    item['high_res_image_urls'] = [f"https://lid.zoocdn.com/1024/768/{img}" for img in gallery]
                    
                    detail_uri = item.get('listingUris', {}).get('detail', '')
                    property_url = f"https://www.zoopla.co.uk{detail_uri}" if detail_uri else ""
                    item['property_url'] = property_url
                    
                    if property_url:
                        log(f"{'  ' * depth}   Fetching details {index+1}/{len(listings)}: ID {lid}...")
                        deep_data = fetch_deep_property_data(property_url)
                        if deep_data:
                            item.update(deep_data)
                    
                    item['_scraped_at'] = time.time()
                    
                    file_handle.write(json.dumps(item) + "\n")
                    file_handle.flush()
                    
                    new_in_box += 1
                    total_captured += 1
                    
            if new_in_box > 0:
                log(f"{'  ' * depth}-> Finished box. Captured {new_in_box} new properties (Total: {total_captured})")
            
    except Exception as e:
        log(f"{'  ' * depth}[!] Error processing box: {e}")

def main():
    global file_handle
    log(f"Target area: {BOUNDS}")
    log("--- Scraping...")
    
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r') as f:
            for line in f:
                try:
                    seen_ids.add(json.loads(line).get('listingId'))
                except: pass
        log(f"--- Resumed. {len(seen_ids)} existing listings already processed.")

    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        file_handle = f
        fetch_box(BOUNDS['north'], BOUNDS['south'], BOUNDS['east'], BOUNDS['west'])

    log(f"--- Total unique listings: {len(seen_ids)}")
    log("--- Done.")

if __name__ == "__main__":
    main()