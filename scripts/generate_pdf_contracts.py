"""
Generate a corpus of synthetic vendor contract PDF files for demo purposes.

Each contract is a realistic multi-page PDF with varied fields: expiry dates,
auto-renewal clauses, annual values, governing law, GDPR clauses, and liability
caps  - engineered to make the docstore demo queries compelling.

Usage:
    uv run --extra scripts python scripts/generate_pdf_contracts.py ./sample_contracts
    uv run --extra scripts python scripts/generate_pdf_contracts.py ./sample_contracts --count 150 --seed 42

Output:
    ./sample_contracts/contract_NNNN_<vendor_slug>.pdf  (one per contract)
    ./sample_contracts/ground_truth.jsonl               (extracted fields)
"""

from __future__ import annotations

import argparse
import json
import random
import textwrap
from datetime import date, timedelta
from pathlib import Path

from tqdm import tqdm

try:
    from fpdf import FPDF
except ImportError:
    raise SystemExit(
        "fpdf2 is required. Install with: uv pip install fpdf2  "
        "or: uv run --extra scripts python scripts/generate_pdf_contracts.py ..."
    )


# ── Vendor pool ────────────────────────────────────────────────────────────────

VENDORS = [
    ("Apex Cloud Technologies",    "saas",         "USD", "Delaware"),
    ("Blueridge Data Systems",     "data",         "USD", "California"),
    ("Cascade Consulting Group",   "services",     "USD", "Washington"),
    ("Delphi Software Ltd",        "license",      "GBP", "England"),
    ("Ember Analytics Inc.",       "saas",         "USD", "New York"),
    ("Fieldstone Marketing Co.",   "marketing",    "USD", "Texas"),
    ("Granite IT Services",        "services",     "USD", "Illinois"),
    ("Helix Data Processing BV",   "data",         "EUR", "Netherlands"),
    ("Irongate Security Corp.",    "services",     "USD", "Virginia"),
    ("Juniper SaaS Solutions",     "saas",         "USD", "California"),
    ("Kestrel Legal Technology",   "saas",         "GBP", "England"),
    ("Lakeview Facilities Mgmt",   "facilities",   "USD", "Ohio"),
    ("Meridian Cloud Partners",    "saas",         "USD", "Georgia"),
    ("Northstar Compliance Ltd",   "services",     "GBP", "Scotland"),
    ("Obsidian Infrastructure",    "services",     "USD", "Colorado"),
    ("Pinnacle Data Analytics",    "data",         "USD", "Massachusetts"),
    ("Quartz HR Platform",         "saas",         "USD", "California"),
    ("Redwood Managed Services",   "facilities",   "USD", "Oregon"),
    ("Solaris Digital Agency",     "marketing",    "EUR", "Germany"),
    ("Talon Cybersecurity Inc.",   "services",     "USD", "Maryland"),
    ("Uplift DevOps Platform",     "saas",         "USD", "Colorado"),
    ("Vantage Research Partners",  "services",     "EUR", "France"),
    ("Westbrook Payroll Systems",  "saas",         "USD", "Utah"),
    ("Xenon Cloud Storage Ltd",    "saas",         "GBP", "England"),
    ("Yarrow Data Consultancy",    "data",         "EUR", "Belgium"),
]

CONTRACT_TYPE_NAMES = {
    "saas":       "Software as a Service Agreement",
    "data":       "Data Processing Agreement",
    "services":   "Professional Services Agreement",
    "license":    "Software License Agreement",
    "marketing":  "Marketing Services Agreement",
    "facilities": "Facilities Management Agreement",
}

ANNUAL_VALUE_RANGES = {
    "saas":       (12_000,  120_000),
    "data":       (24_000,   96_000),
    "services":   (48_000,  360_000),
    "license":    (18_000,  240_000),
    "marketing":  (36_000,  180_000),
    "facilities": (60_000,  300_000),
}

CURRENCY_SYMBOL = {"USD": "USD ", "EUR": "EUR ", "GBP": "GBP "}

GOVERNING_LAW_OPTIONS = {
    "USD": ["Delaware", "California", "New York", "Texas", "Illinois",
            "Colorado", "Massachusetts", "Virginia", "Washington"],
    "GBP": ["England and Wales", "Scotland"],
    "EUR": ["Germany", "Netherlands", "France", "Belgium"],
}

NOTICE_PERIODS = [30, 60, 90]

BOILERPLATE = {
    "intro": (
        "This {contract_type} (\"Agreement\") is entered into as of {effective_date} "
        "(\"Effective Date\") by and between {client}, a corporation organized under "
        "the laws of {client_state} (\"Client\"), and {vendor} (\"Vendor\")."
    ),
    "services": (
        "Vendor shall provide the services or software described herein in accordance "
        "with the terms of this Agreement and any Statements of Work or Order Forms "
        "executed by the parties. Vendor shall perform all obligations in a professional "
        "and workmanlike manner consistent with industry standards."
    ),
    "payment": (
        "Client shall pay Vendor the fees set forth in each Order Form or Statement of "
        "Work within thirty (30) days of invoice. All amounts are in {currency} unless "
        "otherwise specified. Late payments shall accrue interest at 1.5% per month. "
        "The annual contract value under this Agreement is {annual_value}."
    ),
    "term": (
        "This Agreement commences on the Effective Date and continues until {expiry_date} "
        "(\"Initial Term\"), unless earlier terminated in accordance with the terms herein. "
        "{renewal_clause}"
    ),
    "renewal_auto": (
        "This Agreement shall automatically renew for successive one-year periods unless "
        "either party provides written notice of non-renewal at least {notice_period} days "
        "prior to the end of the then-current term."
    ),
    "renewal_manual": (
        "Upon expiration of the Initial Term, this Agreement may be renewed only by "
        "mutual written agreement of both parties executed prior to the expiry date."
    ),
    "liability": (
        "EXCEPT FOR A PARTY'S INDEMNIFICATION OBLIGATIONS, GROSS NEGLIGENCE, OR WILLFUL "
        "MISCONDUCT, NEITHER PARTY SHALL BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, "
        "OR CONSEQUENTIAL DAMAGES. EACH PARTY'S TOTAL AGGREGATE LIABILITY SHALL NOT EXCEED "
        "{liability_cap} IN THE AGGREGATE DURING THE TERM OF THIS AGREEMENT."
    ),
    "confidentiality": (
        "Each party agrees to hold the other party's Confidential Information in strict "
        "confidence, using the same degree of care it uses to protect its own confidential "
        "information, but in no event less than reasonable care. This obligation shall "
        "survive termination for a period of three (3) years."
    ),
    "gdpr": (
        "DATA PROTECTION. To the extent Vendor processes Personal Data (as defined under "
        "Regulation (EU) 2016/679, the \"GDPR\") on behalf of Client, Vendor agrees to: "
        "(a) process Personal Data only on documented instructions from Client; "
        "(b) implement appropriate technical and organizational measures to protect Personal "
        "Data; (c) not engage sub-processors without Client's prior written consent; "
        "(d) assist Client in fulfilling data subject rights; and (e) delete or return all "
        "Personal Data upon termination. This clause constitutes a Data Processing Addendum "
        "for the purposes of Article 28 GDPR."
    ),
    "governing_law": (
        "This Agreement shall be governed by and construed in accordance with the laws of "
        "{governing_law}, without regard to its conflict of law provisions. Any disputes "
        "arising out of or relating to this Agreement shall be resolved by binding "
        "arbitration in accordance with the rules of the relevant arbitration body."
    ),
    "entire_agreement": (
        "This Agreement, together with all exhibits, schedules, and Order Forms, constitutes "
        "the entire agreement between the parties with respect to its subject matter and "
        "supersedes all prior negotiations, representations, or agreements. No modification "
        "shall be effective unless in writing and signed by both parties."
    ),
}

CLIENT_STATES = ["Delaware", "California", "New York"]


# ── PDF rendering ──────────────────────────────────────────────────────────────

class ContractPDF(FPDF):
    def __init__(self, vendor: str, contract_type: str):
        super().__init__()
        self._vendor = vendor
        self._contract_type = contract_type
        self.set_margins(25, 20, 25)
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 6, f"{self._vendor}  - {self._contract_type}", align="L")
        self.cell(0, 6, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 10, "CONFIDENTIAL", align="C")
        self.set_text_color(0, 0, 0)

    def title_page(self, contract_type: str, vendor: str, client: str,
                   effective_date: str, expiry_date: str, contract_no: str):
        self.add_page()
        self.ln(10)
        self.set_font("Helvetica", "B", 18)
        self.cell(0, 12, contract_type.upper(), align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(6)
        self.set_font("Helvetica", size=11)
        self.set_text_color(80, 80, 80)
        self.cell(0, 8, f"Contract No.: {contract_no}", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(16)

        self.set_draw_color(200, 200, 200)
        self.set_fill_color(248, 248, 248)
        self.set_text_color(0, 0, 0)

        def kv(label: str, value: str):
            self.set_font("Helvetica", "B", 10)
            self.cell(55, 9, label, border="B", fill=True)
            self.set_font("Helvetica", size=10)
            self.cell(0, 9, value, border="B", fill=True, new_x="LMARGIN", new_y="NEXT")

        kv("Vendor:", vendor)
        kv("Client:", client)
        kv("Effective Date:", effective_date)
        kv("Expiry Date:", expiry_date)
        self.ln(8)

    def section(self, number: int, title: str, body: str):
        self.set_font("Helvetica", "B", 11)
        self.set_fill_color(240, 240, 240)
        self.cell(0, 9, f"{number}.  {title.upper()}", fill=True,
                  new_x="LMARGIN", new_y="NEXT")
        self.ln(2)
        self.set_font("Helvetica", size=10)
        self.multi_cell(0, 6, body)
        self.ln(5)

    def signature_block(self, vendor: str, client: str, date_str: str):
        self.ln(8)
        self.set_font("Helvetica", "B", 10)
        self.cell(85, 8, "FOR THE VENDOR:", new_x="RIGHT")
        self.cell(0, 8, "FOR THE CLIENT:", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)
        self.set_font("Helvetica", size=10)
        self.set_draw_color(0, 0, 0)

        def sig_line(label: str, value: str, x_offset: float = 0):
            self.set_x(self.l_margin + x_offset)
            self.cell(30, 6, f"{label}:")
            self.cell(55, 6, value, border="B")

        sig_line("Name", "")
        self.set_x(self.l_margin + 90)
        self.cell(30, 6, "Name:")
        self.cell(55, 6, "", border="B", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

        sig_line("Title", "")
        self.set_x(self.l_margin + 90)
        self.cell(30, 6, "Title:")
        self.cell(55, 6, "", border="B", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

        sig_line("Date", date_str)
        self.set_x(self.l_margin + 90)
        self.cell(30, 6, "Date:")
        self.cell(55, 6, date_str, border="B", new_x="LMARGIN", new_y="NEXT")


def fmt_currency(amount: float, currency: str) -> str:
    sym = CURRENCY_SYMBOL[currency]
    if amount >= 1_000_000:
        return f"{sym}{amount/1_000_000:.2f}M"
    if amount >= 1_000:
        return f"{sym}{amount:,.0f}"
    return f"{sym}{amount:.2f}"


# ── Contract generation ────────────────────────────────────────────────────────

def render_contract(seed: int, index: int, force: dict | None = None) -> tuple[bytes, dict]:
    rng = random.Random(seed)
    vendor, kind, currency, vendor_country = rng.choice(VENDORS)

    contract_type = CONTRACT_TYPE_NAMES[kind]
    client = "Lumient Inc."
    client_state = rng.choice(CLIENT_STATES)

    # Dates
    start_year = 2025
    effective = date(start_year, rng.randint(1, 12), rng.randint(1, 28))

    # Demo engineering: distribute expiry dates to make queries interesting
    if force and force.get("expiry_q3"):
        # Force expiry in Q3 2026 (July–September)
        expiry = date(2026, rng.randint(7, 9), rng.randint(1, 28))
    elif force and force.get("expiry_q4"):
        expiry = date(2026, rng.randint(10, 12), rng.randint(1, 28))
    else:
        # Spread across 2026–2028
        months_ahead = rng.randint(6, 36)
        expiry = effective + timedelta(days=months_ahead * 30)
        if expiry.day > 28:
            expiry = expiry.replace(day=28)

    # Auto-renewal
    if force and "auto_renews" in force:
        auto_renews = force["auto_renews"]
    else:
        auto_renews = rng.random() < 0.55
    notice_period = rng.choice(NOTICE_PERIODS) if auto_renews else 90

    # GDPR clause
    if force and "has_gdpr" in force:
        has_gdpr = force["has_gdpr"]
    else:
        has_gdpr = kind == "data" or rng.random() < 0.12

    # Financial
    lo, hi = ANNUAL_VALUE_RANGES[kind]
    annual_value = round(rng.uniform(lo, hi) / 1000) * 1000
    liability_cap = annual_value * rng.choice([1, 2, 3])

    governing_law = rng.choice(GOVERNING_LAW_OPTIONS[currency])

    contract_no = f"CTR-{effective.year}-{index:04d}"

    # Build text fragments
    renewal_clause = (
        BOILERPLATE["renewal_auto"].format(notice_period=notice_period)
        if auto_renews
        else BOILERPLATE["renewal_manual"]
    )

    intro_text = BOILERPLATE["intro"].format(
        contract_type=contract_type,
        effective_date=effective.strftime("%B %d, %Y"),
        client=client,
        client_state=client_state,
        vendor=vendor,
    )
    payment_text = BOILERPLATE["payment"].format(
        currency=currency,
        annual_value=fmt_currency(annual_value, currency),
    )
    term_text = BOILERPLATE["term"].format(
        expiry_date=expiry.strftime("%B %d, %Y"),
        renewal_clause=renewal_clause,
    )
    liability_text = BOILERPLATE["liability"].format(
        liability_cap=fmt_currency(liability_cap, currency),
    )
    governing_text = BOILERPLATE["governing_law"].format(
        governing_law=governing_law,
    )

    # Build PDF
    pdf = ContractPDF(vendor=vendor, contract_type=contract_type)
    pdf.title_page(
        contract_type=contract_type,
        vendor=vendor,
        client=client,
        effective_date=effective.strftime("%B %d, %Y"),
        expiry_date=expiry.strftime("%B %d, %Y"),
        contract_no=contract_no,
    )

    # Body page
    pdf.add_page()
    section_num = 1

    pdf.section(section_num, "Parties and Recitals", intro_text)
    section_num += 1

    pdf.section(section_num, "Services", BOILERPLATE["services"])
    section_num += 1

    pdf.section(section_num, "Fees and Payment", payment_text)
    section_num += 1

    pdf.section(section_num, "Term and Renewal", term_text)
    section_num += 1

    pdf.section(section_num, "Confidentiality", BOILERPLATE["confidentiality"])
    section_num += 1

    pdf.section(section_num, "Limitation of Liability", liability_text)
    section_num += 1

    if has_gdpr:
        pdf.section(section_num, "Data Protection (GDPR)", BOILERPLATE["gdpr"])
        section_num += 1

    pdf.section(section_num, "Governing Law", governing_text)
    section_num += 1

    pdf.section(section_num, "Entire Agreement", BOILERPLATE["entire_agreement"])
    section_num += 1

    pdf.signature_block(vendor, client, effective.strftime("%B %d, %Y"))

    pdf_bytes = bytes(pdf.output())

    meta = {
        "vendor": vendor,
        "contract_type": contract_type,
        "effective_date": effective.isoformat(),
        "expiry_date": expiry.isoformat(),
        "annual_value": annual_value,
        "currency": currency,
        "auto_renews": auto_renews,
        "notice_period_days": notice_period if auto_renews else None,
        "governing_law": governing_law,
        "has_gdpr_clause": has_gdpr,
        "liability_cap": liability_cap,
        "parties": [client, vendor],
        "contract_no": contract_no,
    }
    return pdf_bytes, meta


# ── Corpus generation ──────────────────────────────────────────────────────────

def _force_flags(i: int, count: int) -> dict | None:
    """
    Engineer the distribution so demo queries are compelling.

    For count=150:
    - First ~27%: expiry in Q3 2026 (July–Sept) → "which contracts expire this quarter?"
    - Next ~20%:  auto_renews=False             → "which don't auto-renew?"
    - Next ~10%:  has_gdpr=True                 → GDPR compliance query
    - Rest: fully random
    """
    q3_cutoff = max(1, round(count * 0.27))
    no_renew_cutoff = q3_cutoff + max(1, round(count * 0.20))
    gdpr_cutoff = no_renew_cutoff + max(1, round(count * 0.10))

    if i < q3_cutoff:
        return {"expiry_q3": True}
    if i < no_renew_cutoff:
        return {"auto_renews": False}
    if i < gdpr_cutoff:
        return {"has_gdpr": True}
    return None


def generate_corpus(out_dir: Path, count: int = 30, seed: int = 42) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("contract_*.pdf"):
        stale.unlink()

    master = random.Random(seed)
    seeds = [master.randint(0, 10_000_000) for _ in range(count)]

    records = []
    for i, contract_seed in enumerate(
        tqdm(seeds, desc="generating contracts", unit="contract"), start=1
    ):
        force = _force_flags(i - 1, count)
        pdf_bytes, meta = render_contract(contract_seed, i, force=force)

        slug = (
            meta["vendor"].lower()
            .replace(" ", "_")
            .replace(".", "")
            .replace(",", "")[:24]
        )
        filename = f"contract_{i:04d}_{slug}.pdf"
        path = out_dir / filename
        path.write_bytes(pdf_bytes)
        records.append({"file": filename, "data": meta})

    gt_path = out_dir / "ground_truth.jsonl"
    with open(gt_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    return records


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate synthetic vendor contract PDFs for docstore demos"
    )
    ap.add_argument("out_dir", type=Path, help="Output directory for PDFs")
    ap.add_argument("--count", type=int, default=30, help="Number of contracts (default 30)")
    ap.add_argument("--seed", type=int, default=42, help="Random seed")
    args = ap.parse_args()

    records = generate_corpus(args.out_dir, args.count, args.seed)

    # Summary stats
    q3_start = date(2026, 7, 1)
    q3_end = date(2026, 9, 30)
    auto_renew = sum(1 for r in records if r["data"]["auto_renews"])
    gdpr = sum(1 for r in records if r["data"]["has_gdpr_clause"])
    expiry_q3 = sum(
        1 for r in records
        if q3_start <= date.fromisoformat(r["data"]["expiry_date"]) <= q3_end
    )
    currencies: dict[str, int] = {}
    for r in records:
        c = r["data"]["currency"]
        currencies[c] = currencies.get(c, 0) + 1

    print(f"\nGenerated {args.count} contracts in {args.out_dir}/")
    print(f"  expiring Q3 2026:  {expiry_q3} ({expiry_q3/args.count*100:.0f}%)")
    print(f"  auto-renewing:     {auto_renew} ({auto_renew/args.count*100:.0f}%)")
    print(f"  with GDPR clause:  {gdpr} ({gdpr/args.count*100:.0f}%)")
    print(f"  currencies:        {', '.join(f'{k}={v}' for k, v in sorted(currencies.items()))}")
    print(f"  ground truth:      {args.out_dir / 'ground_truth.jsonl'}")
    print()
    print("Demo queries to try after extraction:")
    print(f"  docstore query contracts --filter 'expiry_date<2026-10-01' --store {args.out_dir}/.docstore")
    print(f"  docstore query contracts --filter 'auto_renews=true' --count --store {args.out_dir}/.docstore")
    print(f"  docstore query contracts --group-by currency --sum annual_value --store {args.out_dir}/.docstore")
    print(f"  docstore ask 'which GDPR contracts expire before our Q3 compliance audit?' --schema contracts --store {args.out_dir}/.docstore")


if __name__ == "__main__":
    main()
