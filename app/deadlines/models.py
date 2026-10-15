"""University procedure contracts. No OCR or university-specific code."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

DayType = Literal['calendar_days', 'business_days']
DocumentKind = Literal['passport','visa','migration_card','registration','medical_examination','fingerprinting','dms']


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Source(Model):
    title: str
    url: HttpUrl
    last_verified_at: date


class RequiredDocument(Model):
    title: str
    conditions: dict[str, str] = Field(default_factory=dict)


class DeadlineRule(Model):
    rule_id: str
    version: str
    title: str
    university_id: str
    country_of_study: str
    procedure_type: str
    document_type: DocumentKind
    student_category: list[str]
    entry_regime: list[str]
    trigger_type: Literal['document_expiry','entry_date','visa_issue_date','new_visa_received','enrollment_event','custom']
    trigger_date_field: str
    offset_days: int = Field(ge=0, le=3650)
    day_type: DayType
    direction: Literal['before','after']
    recommended_buffer_days: int = Field(default=0, ge=0, le=365)
    submission_place: str | None = None
    address: str | None = None
    appointment_required: bool | None = None
    online_service_name: str | None = None
    required_documents: list[RequiredDocument] = Field(default_factory=list)
    processing_time_days: int | None = Field(default=None, ge=0)
    processing_time_type: DayType | None = None
    official_source_title: str
    official_source_url: HttpUrl
    source_last_verified_at: date
    valid_from: date | None = None
    valid_to: date | None = None
    trigger_valid_from: date | None = None
    notes: str = ''
    conditions: dict[str, str] = Field(default_factory=dict)
    review_status: Literal['verified','requires_clarification'] = 'verified'
    review_reason: str = ''
    related_sources: list[Source] = Field(default_factory=list)
    counting_convention: Literal['exclude_trigger'] = 'exclude_trigger'


# A procedure and its deadline are one record in this MVP.
UniversityProcedure = DeadlineRule


class DocumentDates(Model):
    document_type: DocumentKind
    issue_date: date | None = None
    expiry_date: date | None = None
    entry_date: date | None = None
    completed_at: date | None = None
    received_at: date | None = None
    next_required_at: date | None = None


class MedicalExamination(Model):
    status: str = 'unknown'
    completed_at: date | None = None
    expires_at: date | None = None
    next_action_date: date | None = None
    days_remaining: int | None = None
    provider: str | None = None
    official_source: Source | None = None


class Fingerprinting(MedicalExamination):
    status: Literal['not_completed','completed','requires_update_if_applicable','unknown'] = 'unknown'


class Insurance(MedicalExamination):
    policy_number: str | None = Field(default=None, max_length=100)
    valid_from: date | None = None
    valid_until: date | None = None

    @model_validator(mode='after')
    def check_period(self):
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError('invalid_insurance_period')
        return self


class MedicalCertificates(Model):
    status: Literal['unknown','confirmed'] = 'unknown'
    completed_at: date | None = None
    valid_until: date | None = None
    next_required_at: date | None = None
    days_remaining: int | None = None
    # Opaque document IDs only. Never filesystem paths or file contents.
    files: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def check_dates(self):
        if self.completed_at and self.completed_at > date.today():
            raise ValueError('medical_date_in_future')
        if self.completed_at and self.valid_until and self.valid_until < self.completed_at:
            raise ValueError('invalid_medical_period')
        if self.status == 'confirmed' and not self.completed_at:
            raise ValueError('medical_completed_at_required')
        # Derived values cannot be supplied by the client as trusted deadlines.
        self.next_required_at = None
        self.days_remaining = None
        self.files = []
        return self


MedicalDocuments = MedicalCertificates


DMS = Insurance


class ServiceLocation(Model):
    name: str
    service_types: list[str]
    city: str
    address: str
    phone: str | None = None
    appointment_required: bool | None = None
    price_if_verified: str | None = None
    working_hours: str | None = None
    official_source: HttpUrl
    last_verified_at: date


class DeadlinePolicy(Model):
    urgent_days: int = Field(default=3, ge=0)
    attention_days: int = Field(default=10, ge=0)
    status_day_type: DayType = 'calendar_days'
    source_max_age_days: int = Field(default=90, ge=0)


class StudentContext(Model):
    university_id: str = Field(max_length=80, pattern=r'^[a-z0-9_-]+$')
    country_of_study: Literal['RU'] = 'RU'
    citizenship: str = Field(default='unknown', max_length=80)
    student_category: Literal['foreign_student','other','unknown'] = 'unknown'
    entry_regime: Literal['visa_required','visa_free','unknown'] = 'unknown'
    residence: Literal['university_dormitory','other','unknown'] = 'unknown'
    visa_type: Literal['multiple_entry','other','unknown'] = 'unknown'
    age_category: Literal['adult','minor','unknown'] = 'unknown'
    visa_expiry: date | None = None
    stay_expiry: date | None = None
    new_visa_received: date | None = None
    entry_date: date | None = None

    medical_certificates: MedicalCertificates = Field(default_factory=MedicalCertificates)
    fingerprinting: Fingerprinting = Field(default_factory=Fingerprinting)
    insurance: Insurance = Field(default_factory=Insurance)

    @model_validator(mode='after')
    def resolve_entry_regime(self):
        from .entry_regimes import entry_regime_for
        resolved = entry_regime_for(self.citizenship)
        if resolved != 'unknown':
            self.entry_regime = resolved
        return self
