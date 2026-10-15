"""Manual dates for an individual medical certificate; no medical deadline rules."""
from datetime import date
from pydantic import BaseModel, ConfigDict, model_validator


class MedicalFileDates(BaseModel):
    model_config = ConfigDict(extra='forbid')
    issue_date: date | None = None
    valid_until: date | None = None

    @model_validator(mode='after')
    def check_dates(self):
        if self.issue_date and self.issue_date > date.today():
            raise ValueError('issue_date_in_future')
        if self.issue_date and self.valid_until and self.valid_until < self.issue_date:
            raise ValueError('invalid_date_order')
        return self
