from pydantic import BaseModel, field_validator

VALID_PUT_STATUSES = {"war", "neutral"}


class DeclareWarRequest(BaseModel):
    target_nation_id: int


class SetStatusRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_PUT_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(VALID_PUT_STATUSES))}")
        return v


class DiplomacyStatusResponse(BaseModel):
    nation_a: int
    nation_b: int
    status: str
    updated_at: str


class DiplomacyRelationResponse(BaseModel):
    nation_id: int
    nation_name: str
    status: str
    updated_at: str
    requested_by: int | None = None


class WarResponse(BaseModel):
    nation_id: int
    nation_name: str
    status: str
    updated_at: str
