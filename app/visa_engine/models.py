"""Visa confirmation contract. Unknown fields may remain empty."""
from datetime import date
from typing import Literal
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FIELD_NAMES = ('visa_number','visa_type','entries','issue_date','valid_from','valid_until',
               'citizenship','passport_number_if_present','purpose_or_category_if_reliable','issuing_authority_if_reliable')
MAIN_FIELDS = FIELD_NAMES[:6]

class VisaData(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    visa_number: str | None = Field(default=None, min_length=1, max_length=32)
    visa_type: Literal['student','tourist','business','private','work','transit','other','unknown'] = 'unknown'
    entries: Literal['single','double','multiple','unknown'] = 'unknown'
    issue_date: date | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    citizenship: str | None = Field(default=None, min_length=1, max_length=100)
    passport_number_if_present: str | None = Field(default=None, min_length=1, max_length=32)
    purpose_or_category_if_reliable: str | None = Field(default=None, min_length=1, max_length=100)
    issuing_authority_if_reliable: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator('*', mode='before')
    @classmethod
    def clean_text(cls, value):
        if isinstance(value,str) and any(ord(c)<32 or ord(c)==127 for c in value):
            raise ValueError('invalid_text')
        return value

    @field_validator('issue_date','valid_from','valid_until', mode='before')
    @classmethod
    def calendar_only(cls, value):
        if value is not None and not isinstance(value,date) and (not isinstance(value,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value)):
            raise ValueError('invalid_date')
        return value

    @model_validator(mode='after')
    def date_order(self):
        if self.issue_date and self.issue_date>date.today():
            raise ValueError('date_in_future')
        if self.valid_until and any(d and d>self.valid_until for d in (self.issue_date,self.valid_from)):
            raise ValueError('invalid_date_order')
        if not any(v not in (None,'unknown') for v in self.model_dump().values()):
            raise ValueError('empty_confirmation')
        return self

class VisaConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    data: VisaData
