"""Explicit vocabularies; no category guesses from a lone letter or number."""
from datetime import date
import re

ENTRIES = {
    'single': ('single','1','однократная','однократный','une entree'),
    'double': ('double','2','двукратная','двукратный','deux entrees'),
    'multiple': ('mult','multiple','многократная','многократный','multiples'),
}
VISA_TYPES = {
    'student': ('student','study','учебная','учеба','учёба','etudiant'),
    'tourist': ('tourist','tourism','туристическая','туризм'),
    'business': ('business','деловая'), 'private': ('private','частная'),
    'work': ('work','employment','рабочая'), 'transit': ('transit','транзитная'),
    'other': ('other','другая'),
}

def normalize_choice(raw, mapping):
    text=' '.join(raw.casefold().strip().split())
    found={key for key,aliases in mapping.items() for alias in aliases
           if re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',text)}
    return next(iter(found)) if len(found)==1 else 'unknown'

def normalize_date(raw, full_year=None):
    """Day-first visual formats; a two-digit year requires an explicit year anchor.

    No rolling century window. The MRZ resolver uses a matching full visual date.
    """
    raw=raw.strip()
    try:
        if re.fullmatch(r'[0-9]{8}',raw):
            day,month,year=int(raw[:2]),int(raw[2:4]),int(raw[4:])
        elif re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',raw):
            year,month,day=map(int,raw.split('-'))
        elif re.fullmatch(r'[0-9]{2}([./ -])[0-9]{2}\1(?:[0-9]{4}|[0-9]{2})',raw):
            ds,ms,ys=re.split(r'[./ -]',raw);day,month,year=int(ds),int(ms),int(ys)
            if len(ys)==2:
                if full_year is None or full_year%100!=year: return None
                year=full_year
        else: return None
        if not 1800<=year<=2199: return None
        return date(year,month,day).isoformat()
    except ValueError: return None
