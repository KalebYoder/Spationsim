import re
from pydantic import BaseModel, field_validator


class NationCreateRequest(BaseModel):
    name: str
    currency_name: str
    flag_color: str
    home_territory_id: int

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3 or len(v) > 128:
            raise ValueError("Nation name must be 3–128 characters")
        return v

    @field_validator("currency_name")
    @classmethod
    def validate_currency_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1 or len(v) > 64:
            raise ValueError("Currency name must be 1–64 characters")
        return v

    @field_validator("flag_color")
    @classmethod
    def validate_flag_color(cls, v: str) -> str:
        if not re.match(r"^#[0-9A-Fa-f]{6}$", v):
            raise ValueError("Flag color must be a valid hex color (e.g. #FF5733)")
        return v.upper()


class NationResponse(BaseModel):
    id: int
    name: str
    currency_name: str
    flag_color: str
    home_territory_id: int | None
    minerals: float
    fuel: float

    model_config = {"from_attributes": True}


class TerritoryResponse(BaseModel):
    id: int
    node_key: str
    mineral_richness: float
    fuel_richness: float
    distance_from_center: int

    model_config = {"from_attributes": True}
