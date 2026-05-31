"""
Generate a corpus of synthetic invoice .txt files for benchmarking.

The invoices vary across vendor, industry, currency, paid status, line items,
tax rates, and payment terms — enough variety that the LLM has to actually
parse rather than pattern-match a template.

Usage:
    python scripts/generate_invoices.py ./sample_invoices --count 30
    python scripts/generate_invoices.py ./sample_invoices --count 200 --seed 7
"""

from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

from tqdm import tqdm


VENDORS = [
    ("Acme Logistics LLC",          "logistics",    "USD"),
    ("Bluespruce Print Co.",        "print",        "USD"),
    ("Cascadia Cloud Services",     "saas",         "USD"),
    ("Delphi Consulting Group",     "consulting",   "EUR"),
    ("Evergreen Office Supply",     "office",       "USD"),
    ("Fjord Hardware AB",           "hardware",     "EUR"),
    ("Granite Marketing Partners",  "marketing",    "USD"),
    ("Helix Data Systems",          "saas",         "USD"),
    ("Ironwood Construction Ltd",   "construction", "GBP"),
    ("Juniper Catering Co.",        "catering",     "EUR"),
    ("Kestrel Legal Advisors",      "legal",        "USD"),
    ("Lumen Power & Gas",           "utility",      "USD"),
    ("Meridian Freight Forwarders", "logistics",    "USD"),
    ("Northwind Travel Group",      "travel",       "EUR"),
    ("Obsidian Security Inc.",      "security",     "USD"),
    ("Pinecrest Property Mgmt",     "property",     "GBP"),
    ("Quartz Analytics Ltd",        "analytics",    "GBP"),
    ("Redwood Insurance Brokers",   "insurance",    "USD"),
    ("Solstice Design Studio",      "design",       "EUR"),
    ("Tamarack Telecom",            "telecom",      "USD"),
]

LINE_ITEMS = {
    "logistics":    [("Freight handling — pallet shipment", 150, 250),
                     ("Customs documentation processing", 200, 350),
                     ("Insurance surcharge", 35, 80),
                     ("Express delivery surcharge", 90, 180),
                     ("Fuel adjustment", 25, 60)],
    "print":        [("Business card printing — 500 ct", 60, 120),
                     ("Brochure design and print run", 400, 900),
                     ("Banner — vinyl, 6ft", 110, 220),
                     ("Letterhead stock — 1000 sheets", 80, 160)],
    "saas":         [("Monthly subscription — Pro tier", 49, 199),
                     ("Additional seats (5)", 100, 250),
                     ("Premium support add-on", 75, 200),
                     ("API overage", 20, 90)],
    "consulting":   [("Strategy advisory — Q2 retainer", 4500, 9500),
                     ("Workshop facilitation — 2 days", 2200, 3800),
                     ("Executive coaching session", 350, 700)],
    "office":       [("Printer paper — 10 reams", 45, 75),
                     ("Ergonomic chair", 280, 520),
                     ("Standing desk", 380, 720),
                     ("Whiteboard markers — pack of 12", 18, 36)],
    "hardware":     [("Industrial sensor — model XR-200", 320, 580),
                     ("Cable assembly — 50m", 140, 240),
                     ("Mounting bracket (qty 8)", 80, 160)],
    "marketing":    [("Social campaign management — March", 2200, 4800),
                     ("SEO audit and report", 1100, 2400),
                     ("Content writing — 6 articles", 720, 1500)],
    "construction": [("Site preparation — phase 1", 4500, 9500),
                     ("Concrete pour — 12 cubic yards", 2400, 4200),
                     ("Electrical rough-in", 3200, 6800)],
    "catering":     [("Lunch service — 40 guests", 680, 1400),
                     ("Coffee and pastries — morning", 220, 420),
                     ("Bartender service — 4 hours", 280, 460)],
    "legal":        [("Contract review — vendor MSA", 850, 1800),
                     ("Trademark filing — class 9", 1200, 2200),
                     ("Hourly counsel — 4.5h", 1350, 2700)],
    "utility":      [("Electricity — March usage", 420, 1200),
                     ("Natural gas — March", 180, 540),
                     ("Service charge", 25, 45)],
    "travel":       [("Flight booking — SFO/LHR business", 3800, 5400),
                     ("Hotel — 4 nights, central London", 1200, 2200),
                     ("Ground transfer", 180, 320)],
    "security":     [("Penetration test — web app", 4500, 9000),
                     ("SOC 2 readiness review", 3200, 6500),
                     ("Quarterly vulnerability scan", 800, 1600)],
    "property":     [("Monthly rent — April", 2800, 5400),
                     ("Common area maintenance", 220, 480),
                     ("Parking — 2 spaces", 180, 320)],
    "analytics":    [("BI dashboard build", 2400, 4800),
                     ("Data warehouse hosting — March", 540, 1100),
                     ("Custom report development", 1200, 2400)],
    "insurance":    [("General liability — Q2 premium", 1800, 3600),
                     ("Cyber policy — annual", 4200, 8400),
                     ("Workers comp — adjustment", 320, 720)],
    "design":       [("Brand identity refresh", 3800, 7500),
                     ("Web hero illustrations (3)", 900, 1800),
                     ("Pitch deck design — 24 slides", 1600, 3200)],
    "telecom":      [("Business line — 12 lines, April", 480, 1200),
                     ("Long-distance overage", 60, 180),
                     ("Conferencing add-on", 95, 220)],
}

SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£"}
CITIES = ["Portland, OR", "Seattle, WA", "Austin, TX", "Berlin", "London",
          "Dublin", "Toronto, ON", "Amsterdam", "Manchester", "Lyon"]
STREETS = ["Main Street", "Market Avenue", "Bridge Road", "Elm Street",
           "Pine Avenue", "King Street", "Queen Road", "Park Lane"]
TERMS = {"Net 15": 15, "Net 30": 30, "Net 45": 45, "Due on receipt": 0}


def fmt(amount: float, currency: str) -> str:
    return f"{SYMBOL[currency]}{amount:,.2f}"


def render_invoice(seed: int) -> tuple[str, dict]:
    rng = random.Random(seed)
    vendor, kind, currency = rng.choice(VENDORS)
    issue = date(2026, 1, 1) + timedelta(days=rng.randint(0, 180))
    terms = rng.choice(list(TERMS))
    due = issue + timedelta(days=TERMS[terms])

    pool = LINE_ITEMS[kind]
    items = []
    subtotal = 0.0
    for desc, lo, hi in rng.sample(pool, rng.randint(1, min(4, len(pool)))):
        qty = rng.randint(1, 4)
        unit = round(rng.uniform(lo, hi), 2)
        amt = round(qty * unit, 2)
        subtotal += amt
        items.append((desc, qty, unit, amt))

    tax_rate = rng.choice([0.0, 0.0, 0.05, 0.075, 0.085, 0.10, 0.20])
    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)
    paid = rng.random() < 0.65
    inv_no = f"INV-{issue.year}-{issue.month:02d}-{rng.randint(100, 9999):04d}"

    lines = [
        vendor.upper(),
        f"{rng.randint(100, 9999)} {rng.choice(STREETS)}",
        rng.choice(CITIES),
        "",
        f"INVOICE {inv_no}",
        f"Issued: {issue.strftime('%B %d, %Y')}",
        f"Due:    {due.strftime('%B %d, %Y')}",
        "",
        "Bill To:",
        "Lumient Inc.",
        "PO Box 2929, San Francisco, CA 94110",
        "",
        "-" * 68,
        f"{'Description':<42}{'Qty':>5}{'Unit':>10}{'Amount':>11}",
        "-" * 68,
    ]
    for desc, qty, unit, amt in items:
        lines.append(f"{desc[:42]:<42}{qty:>5}{fmt(unit, currency):>10}{fmt(amt, currency):>11}")
    lines.append("-" * 68)
    lines.append(f"{'Subtotal:':>57}{fmt(subtotal, currency):>11}")
    if tax > 0:
        label = f"Tax ({tax_rate*100:g}%):"
        lines.append(f"{label:>57}{fmt(tax, currency):>11}")
    lines += [
        f"{'TOTAL DUE:':>57}{fmt(total, currency):>11} {currency}",
        "",
        f"Status: {'PAID' if paid else 'UNPAID'}",
        f"Payment terms: {terms}",
        "",
        "Thank you for your business.",
    ]

    meta = {
        "vendor": vendor,
        "amount": total,
        "currency": currency,
        "due_date": due.isoformat(),
        "paid": paid,
        "invoice_no": inv_no,
    }
    return "\n".join(lines), meta


def slugify(s: str) -> str:
    s = s.lower().replace(" ", "_").replace(".", "").replace(",", "").replace("&", "and")
    return "".join(c for c in s if c.isalnum() or c == "_")[:30]


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic invoice .txt files")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    master = random.Random(args.seed)
    seeds = [master.randint(0, 10_000_000) for _ in range(args.count)]

    unpaid = 0
    currencies: dict[str, int] = {}
    for i, seed in enumerate(tqdm(seeds, desc="generating", unit="invoice"), start=1):
        text, meta = render_invoice(seed)
        if not meta["paid"]:
            unpaid += 1
        currencies[meta["currency"]] = currencies.get(meta["currency"], 0) + 1
        path = args.out_dir / f"{i:03d}_{slugify(meta['vendor'])}_{meta['invoice_no']}.txt"
        path.write_text(text, encoding="utf-8")

    print(f"Generated {args.count} invoices in {args.out_dir}/")
    print(f"  unpaid:     {unpaid} ({unpaid/args.count*100:.0f}%)")
    print(f"  currencies: {', '.join(f'{k}={v}' for k, v in sorted(currencies.items()))}")


if __name__ == "__main__":
    main()
