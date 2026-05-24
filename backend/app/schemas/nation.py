import re
from pydantic import BaseModel, field_validator


class NationCreateRequest(BaseModel):
    name: str
    currency_name: str
    flag_color: str
    home_territory_id: int
    home_planet_name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3 or len(v) > 128:
            raise ValueError("Nation name must be 3–128 characters")
        return v

    @field_validator("home_planet_name")
    @classmethod
    def validate_home_planet_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1 or len(v) > 128:
            raise ValueError("Planet name must be 1–128 characters")
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
    starfighters: int
    probes_reserve: int

    model_config = {"from_attributes": True}


class ManufactureRequest(BaseModel):
    quantity: int

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Quantity must be at least 1")
        return v


class StarfighterManufactureRequest(BaseModel):
    quantity: int
    territory_id: int

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Quantity must be at least 1")
        return v


class SendFleetRequest(BaseModel):
    from_territory_id: int
    to_territory_id: int
    quantity: int

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Quantity must be at least 1")
        return v


class FleetResponse(BaseModel):
    id: int
    unit_count: int
    status: str
    origin_territory_id: int | None
    origin_node_key: str | None
    origin_name: str | None
    destination_territory_id: int | None
    destination_node_key: str | None
    destination_name: str | None
    arrives_at: str | None

    model_config = {"from_attributes": True}


class UnitStatsResponse(BaseModel):
    type: str
    attack: int
    defense: int
    hp: int
    nodes_per_tick: int
    manufacture_cost_minerals: int
    manufacture_cost_fuel: int


class ProbeStatsResponse(BaseModel):
    nodes_per_tick: int
    reserve: int
    manufacture_cost_minerals: int
    manufacture_cost_fuel: int


class TerritoryResponse(BaseModel):
    id: int
    node_key: str
    name: str | None
    territory_type: str
    mineral_richness: float
    fuel_richness: float
    distance_from_center: int

    model_config = {"from_attributes": True}


class InfrastructureBuildRequest(BaseModel):
    territory_id: int
    type: str

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("mine", "refinery", "fighter_factory", "probe_factory"):
            raise ValueError("Type must be 'mine', 'refinery', 'fighter_factory', or 'probe_factory'")
        return v


class InfrastructureResponse(BaseModel):
    id: int
    territory_id: int
    territory_node_key: str
    territory_name: str | None
    type: str
    level: int
    built_at: str | None

    model_config = {"from_attributes": True}


class TerritoryRenameRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1 or len(v) > 128:
            raise ValueError("Name must be 1–128 characters")
        return v


class TerritoryMapResponse(BaseModel):
    id: int
    node_key: str
    territory_type: str
    distance_from_center: int
    is_colonized: bool
    nation_id: int | None
    nation_name: str | None
    mineral_richness: float
    fuel_richness: float

    model_config = {"from_attributes": True}
