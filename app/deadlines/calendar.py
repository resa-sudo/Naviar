"""Explicit annual calendars. No inferred holiday transfers."""
from datetime import date, timedelta
import json
from pathlib import Path
import re

CALENDAR_DIRECTORY = Path(__file__).resolve().parents[2] / 'config' / 'calendars'


class CalendarMissing(ValueError):
    pass


class BusinessCalendar:
    def __init__(self, country='RU', directory=CALENDAR_DIRECTORY):
        if not re.fullmatch(r'[A-Z]{2}', country):
            raise ValueError('invalid_country')
        self.country = country
        self.directory = Path(directory)
        self.years = {}

    def year(self, year):
        if year not in self.years:
            path = self.directory / self.country / f'{year}.json'
            if not path.is_file():
                raise CalendarMissing(f'calendar_missing:{year}')
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if data['year'] != year or data['country'] != self.country or data['status'] != 'verified':
                raise CalendarMissing(f'calendar_requires_update:{year}')
            self.years[year] = data
        return self.years[year]

    def is_business_day(self, day: date):
        data = self.year(day.year)
        if day.isoformat() in data['working_weekends']:
            return True
        return day.weekday() not in data['weekend_weekdays'] and day.isoformat() not in data['non_working_dates']

    def shift(self, start: date, days: int):
        self.year(start.year)
        result = start
        remaining = abs(days)
        step = timedelta(days=1 if days >= 0 else -1)
        while remaining:
            result += step
            if self.is_business_day(result):
                remaining -= 1
        return result

    def between(self, start: date, end: date):
        # Signed count, excluding the earlier boundary and including the later.
        self.year(start.year)
        self.year(end.year)
        if end < start:
            return -self.between(end, start)
        count = 0
        cursor = start
        while cursor < end:
            cursor += timedelta(days=1)
            count += self.is_business_day(cursor)
        return count
