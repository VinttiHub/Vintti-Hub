"""Deterministic checks that back the reference-feedback AI flagging.

Everything here runs BEFORE the LLM call and decides the recency verdict on its
own. The model only writes the prose explaining it, so the same reference always
gets the same colour.

Two jobs:
  1. Read the candidate's work history out of `resume.work_experience` (TEXT
     holding a JSON array) and collapse it into a per-company timeline.
  2. Match the company the reference says they worked together at against that
     timeline, and classify how recent it is.
"""

import json
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher


# --- Dates -----------------------------------------------------------------
# resume.js writes YYYY-MM-15, ai_routes._normalize_resume_date writes YYYY-MM-01
# and returns the raw string untouched when it doesn't recognise the format — so
# "Jan 2022", "01/2022" and "2022" all live in production rows. We parse all of
# them; anything left over is marked undated rather than dropped, because
# dropping the entry that matches the reference turns a green into a red.

PRESENT_RE = re.compile(
    r'^(present|current|ongoing|now|to date|hasta la fecha|actualidad|presente|en curso)$',
    re.I,
)

MONTH_MAP = {
    # EN
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8,
    'sept': 9, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    # ES
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
    'ene': 1, 'abr': 4, 'ago': 8, 'set': 9, 'dic': 12,
}
# Longest first so "septiembre" wins over "sep".
_MONTH_KEYS = sorted(MONTH_MAP, key=len, reverse=True)


def _strip_accents(text):
    return ''.join(
        ch for ch in unicodedata.normalize('NFD', text)
        if unicodedata.category(ch) != 'Mn'
    )


def is_present(raw):
    """True when the value means 'still working here' (or is simply empty)."""
    s = str(raw or '').strip()
    return not s or bool(PRESENT_RE.match(s))


def parse_soft_date(raw):
    """Port of resume.js normalizeISO15. Returns (year, month) or None.

    None means empty, "Present", or genuinely unparseable — callers must
    distinguish those via is_present().
    """
    s = str(raw or '').strip()
    if not s or PRESENT_RE.match(s):
        return None

    s = s.split('T')[0].strip()

    m = re.match(r'^(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?$', s)
    if m:
        return int(m.group(1)), min(12, max(1, int(m.group(2))))

    m = re.match(r'^(\d{1,2})[-/](\d{4})$', s)
    if m:
        return int(m.group(2)), min(12, max(1, int(m.group(1))))

    m = re.match(r'^([^\d\s]+)\.?\s+(\d{4})$', s)
    if m:
        key = _strip_accents(m.group(1).lower().replace('.', ''))
        for name in _MONTH_KEYS:
            if key.startswith(name):
                return int(m.group(2)), MONTH_MAP[name]

    m = re.match(r'^(\d{4})$', s)
    if m:
        return int(m.group(1)), 6

    return None


# --- Company names ---------------------------------------------------------

_LEGAL_SUFFIXES = {
    'inc', 'llc', 'ltd', 'limited', 'sa', 'sas', 'srl', 'sl', 'corp', 'corporation',
    'co', 'company', 'gmbh', 'bv', 'nv', 'plc', 'holdings', 'holding', 'group',
    'llp', 'lp', 'pty', 'ag', 'oy', 'ab', 'as', 'spa', 'sarl', 'kk', 'pte',
}
# Dropped so "Cognizant" matches "Cognizant Technology Solutions".
_GENERIC_TOKENS = {
    'technology', 'technologies', 'tech', 'solutions', 'services', 'service',
    'consulting', 'consultancy', 'consultants', 'international', 'global',
    'worldwide', 'systems', 'partners', 'associates', 'the', 'and', 'de', 'del',
    'y', 'of',
}
_BLANK_VALUES = {'', '-', '--', 'n/a', 'na', 'none', 'null', 'no aplica', 'ninguna', '.'}


def is_blank_company(name):
    return _strip_accents(str(name or '').strip().lower()) in _BLANK_VALUES


def company_tokens(name):
    """Normalized, meaningful tokens of a company name."""
    s = _strip_accents(str(name or '').lower())
    s = re.sub(r'[^a-z0-9]+', ' ', s).strip()
    if not s:
        return []
    tokens = [t for t in s.split() if t not in _LEGAL_SUFFIXES]
    meaningful = [t for t in tokens if t not in _GENERIC_TOKENS]
    return meaningful or tokens


def normalize_company(name):
    return ' '.join(company_tokens(name))


def companies_match(a, b):
    """Token-set containment, with a narrow typo net.

    Deliberately NOT a similarity ratio: no SequenceMatcher threshold separates
    the classes. "Stripe"/"Stride" scores 0.833 and "Sabre"/"Saber" 0.800 (must
    NOT match), while "Amazon"/"Amazon Web Services" scores 0.522 and
    "Meta"/"Meta Platforms" 0.471 (must match). Any cutoff catching the latter
    catches the former.
    """
    ta, tb = set(company_tokens(a)), set(company_tokens(b))
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    # "Meta" ⊆ "Meta Platforms", "Amazon" ⊆ "Amazon Web Services".
    if ta <= tb or tb <= ta:
        return True
    na, nb = ' '.join(sorted(ta)), ' '.join(sorted(tb))
    # Same letters, different spacing: "BairesDev" vs "Baires Dev".
    if na.replace(' ', '') == nb.replace(' ', ''):
        return True
    # Typo net: same token count, near-identical spelling. Rejects
    # "Sabre"/"Saber" (0.800) and "Stripe"/"Stride" (0.833).
    if len(ta) == len(tb) and SequenceMatcher(None, na, nb).ratio() >= 0.90:
        return True
    return False


# --- Work history ----------------------------------------------------------

def parse_work_experience(raw):
    """`resume.work_experience` is TEXT holding a JSON array string."""
    if not raw:
        return []
    if isinstance(raw, list):
        entries = raw
    else:
        try:
            entries = json.loads(raw)
        except (TypeError, ValueError):
            return []
    return [e for e in entries if isinstance(e, dict)]


def build_company_timeline(entries):
    """Collapse work entries into one span per company, most recent first.

    The resume prompt deliberately emits one entry per job title at the same
    company (ai_routes.py ~1524), so raw indexes 0 and 1 are routinely the same
    employer and "previous job" would be meaningless without this grouping.
    """
    spans = {}
    for entry in entries:
        company = str(entry.get('company') or '').strip()
        if not company:
            continue
        key = normalize_company(company)
        if not key:
            continue

        current = bool(entry.get('current')) or is_present(entry.get('end_date'))
        start = parse_soft_date(entry.get('start_date'))
        end = None if current else parse_soft_date(entry.get('end_date'))

        span = spans.get(key)
        if not span:
            span = {
                'key': key,
                'company': company,
                'titles': [],
                'start': start,
                'end': end,
                'current': current,
            }
            spans[key] = span
        else:
            span['current'] = span['current'] or current
            if start and (not span['start'] or start < span['start']):
                span['start'] = start
            if end and (not span['end'] or end > span['end']):
                span['end'] = end

        title = str(entry.get('title') or entry.get('position') or '').strip()
        if title and title not in span['titles']:
            span['titles'].append(title)

    def sort_key(span):
        if span['current']:
            return (2, (9999, 12))
        if span['end']:
            return (1, span['end'])
        if span['start']:
            return (1, span['start'])
        return (0, (0, 0))  # undated last

    return sorted(spans.values(), key=sort_key, reverse=True)


def span_years(span):
    """(first_year, last_year) for a span; last_year is this year when current."""
    start = span['start'][0] if span['start'] else None
    if span['current']:
        end = date.today().year
    else:
        end = span['end'][0] if span['end'] else None
    return start, end


def format_span(span):
    start, end = span_years(span)
    if not start and not end:
        return 'dates unknown'
    if span['current']:
        return f"{start or '?'} – present"
    return f"{start or '?'} – {end or '?'}"


# --- The verdict -----------------------------------------------------------

FLAG_BY_RECENCY = {
    'current': 'green',
    'most_recent': 'green',
    'previous': 'green',
    'older': 'amber',
    'no_history': 'amber',
    'unknown': 'amber',
    'period_mismatch': 'red',
    'not_found': 'red',
}

# People misremember start/end years by a few months; 1 year of slack keeps a
# genuine overlap from reading as a contradiction.
_YEAR_SLACK = 1


def _years_overlap(stated_from, stated_to, span):
    """None = can't tell (missing dates on either side)."""
    if not stated_from and not stated_to:
        return None
    cv_start, cv_end = span_years(span)
    if not cv_start and not cv_end:
        return None

    a_lo = stated_from or stated_to
    a_hi = stated_to or stated_from
    b_lo = cv_start or cv_end
    b_hi = cv_end or cv_start
    return max(a_lo, b_lo) <= min(a_hi, b_hi) + _YEAR_SLACK


def match_reference_to_history(shared_company, from_year, to_year, work_entries):
    """Classify how recent — and how verifiable — a reference is.

    Returns a dict the LLM is given as already-decided fact and the UI renders
    directly. The model never picks the colour.
    """
    timeline = build_company_timeline(work_entries)
    stated_period = None
    if from_year or to_year:
        stated_period = f"{from_year or '?'} – {to_year or '?'}"

    result = {
        'recency': 'unknown',
        'flag': 'amber',
        'stated_company': str(shared_company or '').strip() or None,
        'stated_period': stated_period,
        'matched_company': None,
        'matched_period': None,
        'matched_titles': [],
        'position_in_history': None,
        'history_companies': [
            {'company': s['company'], 'period': format_span(s)} for s in timeline
        ],
    }

    if not timeline:
        # No generated CV means nothing to verify against. That is a data gap,
        # not a contradiction, so it must not read as a red flag.
        result['recency'] = 'no_history'
        result['flag'] = FLAG_BY_RECENCY['no_history']
        return result

    if is_blank_company(shared_company):
        result['recency'] = 'unknown'
        result['flag'] = FLAG_BY_RECENCY['unknown']
        return result

    matched_index = next(
        (i for i, span in enumerate(timeline) if companies_match(shared_company, span['company'])),
        None,
    )
    if matched_index is None:
        result['recency'] = 'not_found'
        result['flag'] = FLAG_BY_RECENCY['not_found']
        return result

    span = timeline[matched_index]
    result['matched_company'] = span['company']
    result['matched_period'] = format_span(span)
    result['matched_titles'] = span['titles']
    result['position_in_history'] = matched_index + 1

    if _years_overlap(from_year, to_year, span) is False:
        result['recency'] = 'period_mismatch'
        result['flag'] = FLAG_BY_RECENCY['period_mismatch']
        return result

    if matched_index == 0:
        recency = 'current' if span['current'] else 'most_recent'
    elif matched_index == 1:
        recency = 'previous'
    else:
        recency = 'older'

    result['recency'] = recency
    result['flag'] = FLAG_BY_RECENCY[recency]
    return result
