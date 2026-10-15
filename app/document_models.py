"""Structured demo data shared by manual entry and future extraction."""

from datetime import date
from enum import Enum
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class DocumentStatus(str, Enum):
    uploaded = "uploaded"
    processing = "processing"
    processing_error = "processing_error"
    needs_confirmation = "needs_confirmation"
    verified = "verified"
    rejected = "rejected"
    error = "error"


class PassportData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    last_name: str = Field(min_length=1, max_length=100)
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str = Field(default="", max_length=100)
    citizenship: str = Field(min_length=1, max_length=100)
    passport_number: str = Field(min_length=1, max_length=32)
    birth_date: date
    issue_date: date
    expiry_date: date

    @field_validator("last_name", "first_name", "middle_name", "citizenship", "passport_number")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("invalid_text")
        return value

    @field_validator("birth_date", "issue_date", "expiry_date", mode="before")
    @classmethod
    def require_calendar_date(cls, value):
        if isinstance(value, date):
            return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("invalid_date")
        return value

    @field_validator("birth_date", "issue_date")
    @classmethod
    def reject_future_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("date_in_future")
        return value

    @field_validator("expiry_date")
    @classmethod
    def check_expiry_after_issue(cls, value: date, info: ValidationInfo) -> date:
        issue_date = info.data.get("issue_date")
        if issue_date and value <= issue_date:
            raise ValueError("expiry_must_follow_issue")
        return value


class PassportConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # A form opened before delete/re-upload must not confirm a different file.
    document_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    data: PassportData
