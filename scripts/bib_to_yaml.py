"""
Convert _data/publication.bib → _data/publications.yml

Usage:
    python scripts/bib_to_yaml.py

To hide a specific entry from the website, add to its BibTeX fields:
    website = {hide}

Sections generated: journals (@article), conferences (@inproceedings),
patents (@misc with "Patent" in note).
Invited talks and workshops are excluded by default.
"""

import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
BIB_PATH = ROOT / "_data" / "publication.bib"
YAML_PATH = ROOT / "_data" / "publications.yml"

# ---------------------------------------------------------------------------
# Minimal BibTeX parser (no external dependency)
# ---------------------------------------------------------------------------

def parse_bib(text: str) -> list[dict]:
    """Return a list of dicts, one per BibTeX entry."""
    entries = []
    # Match @type{key, ... }  (handles nested braces up to 2 levels)
    pattern = re.compile(
        r"@(\w+)\s*\{([^,]*),\s*((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}",
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        entry_type = m.group(1).lower()
        entry_key = m.group(2).strip()
        body = m.group(3)

        fields = {}
        # Parse field = {value} or field = "value"
        field_pat = re.compile(
            r"(\w+)\s*=\s*(?:\{((?:[^{}]|\{[^{}]*\})*)\}|\"([^\"]*)\")",
            re.DOTALL,
        )
        for fm in field_pat.finditer(body):
            key = fm.group(1).lower()
            val = (fm.group(2) if fm.group(2) is not None else fm.group(3)).strip()
            fields[key] = val

        fields["_type"] = entry_type
        fields["_key"] = entry_key
        entries.append(fields)

    return entries


# ---------------------------------------------------------------------------
# LaTeX cleanup
# ---------------------------------------------------------------------------

def clean_latex(s: str) -> str:
    """Remove common LaTeX markup from a string."""
    s = s.replace("\\&", "&")
    s = s.replace("\\textbf{", "").replace("}", "")
    s = s.replace("\\dag", "†")
    s = s.replace("\\ddag", "‡")
    s = s.replace("--", "–")
    s = s.replace("~", " ")
    # Remove remaining backslash commands like \emph
    s = re.sub(r"\\[a-zA-Z]+\s?", "", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_authors(raw: str) -> str:
    """Clean author string: remove LaTeX, convert 'Last, First' to 'First Last'.

    Preserves equal-contribution markers (* and †) attached to author names.
    """
    raw = clean_latex(raw)
    # Split by 'and' separators
    parts = [a.strip() for a in re.split(r"\s+and\s+", raw) if a.strip()]
    authors = []
    for part in parts:
        # "Last, First" → "First Last"
        if "," in part:
            last, first = part.split(",", 1)
            last = last.strip()
            first = first.strip()
            # Move markers (*, †, ‡) from last name to end: "Lee*" → "Lee" + "*"
            marker = ""
            for ch in ("*", "†", "‡"):
                if ch in last:
                    marker += ch
                    last = last.replace(ch, "")
                if ch in first:
                    marker += ch
                    first = first.replace(ch, "")
            name = f"{first} {last}".strip()
            if marker:
                name += marker
            authors.append(name)
        else:
            authors.append(part)
    return ", ".join(authors)


def venue_from_entry(entry: dict) -> str:
    """Extract venue string from journal or booktitle."""
    raw = entry.get("journal") or entry.get("booktitle") or ""
    return clean_latex(raw)


def short_venue(entry: dict) -> str:
    """Build the venue line shown on the website (venue, year)."""
    v = venue_from_entry(entry)
    year = entry.get("year", "")
    if v and year:
        return f"{v}, {year}"
    return v or year


# ---------------------------------------------------------------------------
# Categorize entries
# ---------------------------------------------------------------------------

def is_hidden(entry: dict) -> bool:
    return entry.get("website", "").strip().lower() == "hide"


def is_patent(entry: dict) -> bool:
    note = entry.get("note", "").lower()
    return entry["_type"] == "misc" and "patent" in note


def is_journal(entry: dict) -> bool:
    return entry["_type"] == "article"


def is_conference(entry: dict) -> bool:
    if entry["_type"] != "inproceedings":
        return False
    # Exclude workshops (booktitle contains "workshop" or "LBR session")
    bt = entry.get("booktitle", "").lower()
    if "workshop" in bt or "lbr session" in bt:
        return False
    return True


# ---------------------------------------------------------------------------
# YAML generation
# ---------------------------------------------------------------------------

def yaml_escape(s: str) -> str:
    """Wrap in double quotes, escaping internal double quotes."""
    return '"' + s.replace('"', '\\"') + '"'


def entry_to_yaml(entry: dict, id_str: str) -> str:
    title = clean_latex(entry.get("title", ""))
    authors = clean_authors(entry.get("author", ""))
    venue = short_venue(entry)
    year = entry.get("year", "")
    doi = entry.get("doi", "").strip()
    note = clean_latex(entry.get("note", ""))

    lines = [
        f"  - id: {yaml_escape(id_str)}",
        f"    title: {yaml_escape(title)}",
        f"    authors: {yaml_escape(authors)}",
        f"    venue: {yaml_escape(venue)}",
        f"    year: {year}",
    ]
    if doi:
        # Normalize doi to full URL
        if not doi.startswith("http"):
            doi = f"https://doi.org/{doi}"
        lines.append(f"    doi: {yaml_escape(doi)}")
    if note:
        lines.append(f"    note: {yaml_escape(note)}")

    return "\n".join(lines)


def build_yaml(entries: list[dict]) -> str:
    journals = []
    conferences = []
    patents = []

    for e in entries:
        if is_hidden(e):
            continue
        if is_journal(e):
            journals.append(e)
        elif is_conference(e):
            conferences.append(e)
        elif is_patent(e):
            patents.append(e)
        # else: invited talks, workshops, etc. — skip

    # Sort each section: newest first, then alphabetically by key
    def sort_key(e):
        return (-int(e.get("year", 0)), e["_key"])

    journals.sort(key=sort_key)
    conferences.sort(key=sort_key)
    patents.sort(key=sort_key)

    sections = []

    # Journals
    sections.append("journals:")
    for i, e in enumerate(journals, 1):
        jid = f"J{len(journals) - i + 1}"
        sections.append(entry_to_yaml(e, jid))

    sections.append("")

    # Conferences
    sections.append("conferences:")
    for i, e in enumerate(conferences, 1):
        cid = f"C{len(conferences) - i + 1}"
        sections.append(entry_to_yaml(e, cid))

    sections.append("")

    # Patents
    sections.append("patents:")
    for i, e in enumerate(patents, 1):
        pid = f"P{len(patents) - i + 1}"
        sections.append(entry_to_yaml(e, pid))

    return "\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not BIB_PATH.exists():
        print(f"ERROR: {BIB_PATH} not found", file=sys.stderr)
        sys.exit(1)

    text = BIB_PATH.read_text(encoding="utf-8")
    entries = parse_bib(text)
    yaml_content = build_yaml(entries)

    YAML_PATH.write_text(yaml_content, encoding="utf-8")
    print(f"Generated {YAML_PATH}")

    # Summary
    for line in yaml_content.split("\n"):
        if line.endswith(":") and not line.startswith(" "):
            count = yaml_content.count(f"\n  - id:")
            break
    journals_n = yaml_content.split("conferences:")[0].count("  - id:")
    rest = yaml_content.split("conferences:")[1] if "conferences:" in yaml_content else ""
    conferences_n = rest.split("patents:")[0].count("  - id:") if "patents:" in rest else rest.count("  - id:")
    patents_n = rest.split("patents:")[1].count("  - id:") if "patents:" in rest else 0
    print(f"  Journals: {journals_n}, Conferences: {conferences_n}, Patents: {patents_n}")


if __name__ == "__main__":
    main()
