import argparse
import csv
import requests
from bs4 import BeautifulSoup
import random
import time
from datetime import datetime

# Simple Wikipedia scraper for "On This Day" events
BASE_URL = "https://en.wikipedia.org/wiki/{month}_{day}"

def fetch_events(month: str, day: int):
    """Fetch historical events from Wikipedia for a given date."""
    url = BASE_URL.format(month=month, day=day)
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    events = []
    # Wikipedia sections: Events, Births, Deaths
    for section in soup.find_all("span", {"class": "mw-headline"}):
        sec_title = section.get_text()
        if sec_title in ["Events", "Births", "Deaths"]:
            ul = section.find_parent().find_next_sibling("ul")
            while ul and ul.name == "ul":
                for li in ul.find_all("li", recursive=False):
                    text = " ".join(li.get_text().split())
                    year = None
                    if text[:4].isdigit():
                        year = text[:4]
                    events.append({
                        "year": year,
                        "text": text,
                        "type": sec_title
                    })
                ul = ul.find_next_sibling()
                if ul and ul.name != "ul":
                    break
    return events

def select_events(events, min_count, max_count, india_low, india_high, include_births, include_deaths):
    """Filter & balance India/Global events."""
    india_keywords = ["India", "Indian", "Delhi", "Mumbai", "Kolkata", "Chennai", "Bengal", "Hindustan", "Modi", "Gandhi", "Congress", "BJP", "Mughal", "Hindutva", "Ram", "Ayodhya", "Himalaya", "Indira", "Rajiv", "Hockey", "Cricket"]
    events_filtered = []

    # Remove births/deaths if not requested
    for e in events:
        if e["type"] == "Births" and not include_births:
            continue
        if e["type"] == "Deaths" and not include_deaths:
            continue
        events_filtered.append(e)

    india_events = [e for e in events_filtered if any(k in e["text"] for k in india_keywords)]
    global_events = [e for e in events_filtered if e not in india_events]

    total_target = random.randint(min_count, max_count)
    india_target = int(total_target * random.uniform(india_low, india_high))
    global_target = total_target - india_target

    chosen = random.sample(india_events, min(len(india_events), india_target)) + \
             random.sample(global_events, min(len(global_events), global_target))

    random.shuffle(chosen)
    return chosen

def save_csv(month, results, outfile):
    """Save results to CSV."""
    with open(outfile, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Title", "Description", "Source"])
        for day, events in results.items():
            for e in events:
                title = e["text"].split(" – ")[-1]
                desc = e["text"]
                date_str = f"{month} {day}"
                source = f"https://en.wikipedia.org/wiki/{month}_{day}"
                writer.writerow([date_str, title, desc, source])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", type=str, help="Month name (e.g., august)")
    parser.add_argument("--all-months", action="store_true", help="Fetch for all 12 months")
    parser.add_argument("--min", type=int, default=20)
    parser.add_argument("--max", type=int, default=25)
    parser.add_argument("--india-low", type=float, default=0.60)
    parser.add_argument("--india-high", type=float, default=0.70)
    parser.add_argument("--include-births", action="store_true")
    parser.add_argument("--include-deaths", action="store_true")
    parser.add_argument("--outfile", type=str, default="history.csv")
    args = parser.parse_args()

    months = [args.month] if args.month else []
    if args.all_months:
        months = ["January", "February", "March", "April", "May", "June", "July",
                  "August", "September", "October", "November", "December"]

    results = {}
    for month in months:
        for day in range(1, 32):
            try:
                events = fetch_events(month, day)
                if not events:
                    continue
                chosen = select_events(
                    events, args.min, args.max,
                    args.india_low, args.india_high,
                    args.include_births, args.include_deaths
                )
                results[day] = chosen
                time.sleep(1)  # polite delay
            except Exception as e:
                print(f"Error fetching {month} {day}: {e}")
                continue

    save_csv(months[0] if len(months) == 1 else "full_year", results, args.outfile)

if __name__ == "__main__":
    main()
