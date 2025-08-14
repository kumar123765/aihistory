#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import csv
import random
import re
import time
from typing import List, Dict
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://en.wikipedia.org/wiki/{month}_{day}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HistMonthBot/2.1)"}
SESSION = requests.Session()

VALID_MONTHS = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
]

EXCLUDE_OBSERVANCES = [
    "festival","observance","holiday","feast","day of","saint ","eid","diwali","holi","janmashtami","navroz",
    "christmas","easter","good friday","ramadan","ramzan","gurpurab","baisakhi","pongal","onam","durga puja",
    "ganesh chaturthi","mahashivratri","mahavir jayanti","buddha purnima","mahotsav"
]

INDIA_KEYWORDS = [
    "india","indian","bharat","delhi","mumbai","bombay","calcutta","kolkata","madras","chennai","bengal","punjab",
    "assam","hyderabad","mysore","travancore","awadh","gujarat","maharashtra","isro","drdo","incospar","iit","iisc",
    "inc ","congress","bjp","nehru","gandhi","ambedkar","bhagat singh","subhas","tilak","patel","swaraj","satyagraha",
    "quit india","swadeshi","dandi","ina","azad hind","hockey","cricket"
]

def normalize_month(m: str) -> str:
    m = (m or "").strip()
    if m.isdigit():
        idx = int(m)
        if 1 <= idx <= 12:
            return VALID_MONTHS[idx-1]
    for v in VALID_MONTHS:
        if v.lower() == m.lower():
            return v
    return m.title()

def http_get(url: str, tries: int = 3, backoff: float = 1.0):
    for i in range(tries):
        try:
            resp = SESSION.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                return resp
            print(f"[WARN] GET {url} -> HTTP {resp.status_code} (try {i+1}/{tries})")
        except Exception as e:
            print(f"[WARN] GET {url} failed: {e} (try {i+1}/{tries})")
        time.sleep(backoff * (i + 1))
    return None

def fetch_day_sections(month: str, day: int, include_births: bool, include_deaths: bool) -> List[Dict]:
    """Scrape Events (+ optional Births/Deaths) from Wikipedia Month-Day page."""
    url = BASE_URL.format(month=month, day=day)
    resp = http_get(url)
    if not resp:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    out = []
    flags = {"events": True, "births": include_births, "deaths": include_deaths}
    found_any = False

    for h in soup.find_all(["h2","h3"]):
        span = h.find("span", class_="mw-headline")
        if not span:
            continue
        name = span.get_text(strip=True).lower()
        if name in flags and flags[name]:
            found_any = True
            ul = h.find_next_sibling("ul")
            while ul and ul.name == "ul":
                for li in ul.find_all("li", recursive=False):
                    txt = " ".join(li.get_text(" ", strip=True).split())
                    if not txt:
                        continue
                    low = txt.lower()
                    if any(term in low for term in EXCLUDE_OBSERVANCES):
                        continue  # drop observances/festivals
                    # most items start with "YYYY – description"
                    m = re.match(r"^(\d{1,4})\s*[–-]\s*(.*)$", txt)
                    desc = m.group(2) if m else txt
                    # title from first anchor if present
                    a = li.find("a")
                    href = url
                    title = ""
                    if a and a.has_attr("href"):
                        href = a["href"]
                        if href.startswith("/"):
                            href = "https://en.wikipedia.org" + href
                        title = a.get_text(strip=True)
                    if not title:
                        title = desc.split(".")[0][:120]
                    out.append({"title": title, "desc": desc, "src": href})
                ns = ul.find_next_sibling()
                if ns and ns.name == "ul":
                    ul = ns
                else:
                    break
    if not found_any:
        print(f"[WARN] No Events/Births/Deaths sections found on {url}")
    return out

def india_score(text: str) -> float:
    low = text.lower()
    score = 0.0
    if any(k in low for k in INDIA_KEYWORDS):
        score += 50.0
    score += min(len(text) / 200.0, 10.0)
    return score

def select_for_day(raw: List[Dict], min_count: int, max_count: int, ind_low: float, ind_high: float) -> List[Dict]:
    if not raw:
        return []
    # basic dedupe by (title, desc)
    seen = set()
    items = []
    for r in raw:
        key = (r["title"], r["desc"])
        if key in seen:
            continue
        seen.add(key)
        s = india_score(f"{r['title']} {r['desc']}")
        items.append({**r, "score": s, "is_india": s >= 50.0})
    # sort by India-ness, then score
    items.sort(key=lambda x: (x["is_india"], x["score"]), reverse=True)
    total = max(min_count, min(max_count, len(items)))
    india_target_low = int(total * ind_low)
    india_target_high = int(total * ind_high)

    india_items = [i for i in items if i["is_india"]]
    global_items = [i for i in items if not i["is_india"]]

    selected = []
    selected.extend(india_items[:india_target_high])
    need = total - len(selected)
    if need > 0:
        selected.extend(global_items[:need])

    # ensure lower India bound
    ind_count = sum(1 for i in selected if i["is_india"])
    if ind_count < india_target_low and len(india_items) > ind_count:
        replace = india_target_low - ind_count
        gi = len(selected) - 1
        src = ind_count
        while replace > 0 and gi >= 0 and src < len(india_items):
            if not selected[gi]["is_india"]:
                selected[gi] = india_items[src]
                src += 1
                replace -= 1
            gi -= 1

    # final order
    selected.sort(key=lambda x: (x["is_india"], x["score"]), reverse=True)
    return selected[:total]

def save_csv(month_label: str, per_day: Dict[int, List[Dict]], outfile: str):
    with open(outfile, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Title", "Description", "Source"])
        for day in sorted(per_day.keys()):
            for ev in per_day[day]:
                title = ev["title"]
                desc = ev["desc"]
                if len(desc) > 500:
                    desc = desc[:497] + "..."
                date_str = f"{day:02d} {month_label}"
                w.writerow([date_str, title, desc, ev["src"]])
    print(f"[OK] Wrote {outfile}")

def run_month(month_name: str, min_count: int, max_count: int, india_low: float, india_high: float, include_births: bool, include_deaths: bool, outfile: str):
    month_label = normalize_month(month_name)
    if month_label not in VALID_MONTHS:
        raise SystemExit(f"[ERROR] Unknown month '{month_name}'. Use names like 'August' or numbers 1-12.")
    print(f"[INFO] Building {month_label}: min={min_count}, max={max_count}, India={india_low:.0%}-{india_high:.0%}, births={include_births}, deaths={include_deaths}")
    days_in_month = [31, 29 if month_label == "February" else 31, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][VALID_MONTHS.index(month_label)]
    per_day = {}
    for day in range(1, days_in_month + 1):
        raw = fetch_day_sections(month_label, day, include_births, include_deaths)
        if not raw:
            print(f"[WARN] No data for {month_label} {day}")
            continue
        chosen = select_for_day(raw, min_count, max_count, india_low, india_high)
        per_day[day] = chosen
        time.sleep(0.4 + random.random()*0.3)  # polite delay
    save_csv(month_label, per_day, outfile)

def main():
    ap = argparse.ArgumentParser(description="Build monthly historical events CSV with India:Global mix (cloud-friendly).")
    ap.add_argument("--month", type=str, required=True, help="Month name or number (e.g., 'august' or '8').")
    ap.add_argument("--min", type=int, default=20, help="Minimum events per day (default 20).")
    ap.add_argument("--max", type=int, default=25, help="Maximum events per day (default 25).")
    ap.add_argument("--india-low", type=float, default=0.60, help="Lower bound of India share (default 0.60).")
    ap.add_argument("--india-high", type=float, default=0.70, help="Upper bound of India share (default 0.70).")
    ap.add_argument("--include-births", action="store_true", help="Include notable births (default off).")
    ap.add_argument("--include-deaths", action="store_true", help="Include notable deaths (default off).")
    ap.add_argument("--outfile", type=str, default="events.csv", help="Output CSV filename.")
    args = ap.parse_args()

    run_month(args.month, args.min, args.max, args.india_low, args.india_high, args.include_births, args.include_deaths, args.outfile)

if __name__ == "__main__":
    main()
