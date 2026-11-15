"""Pydantic schemas for the AquaCrop-OSPy HTTP API.

The schemas mirror the constructor arguments of the model entities but use
snake_case names and JSON friendly types. Conversion to the model objects
happens in :mod:`api.services.simulation`.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

_DATE_PATTERN = re.compile(r"^\d{4}/\d{2}/\d{2}$")
_MONTH_DAY_PATTERN = re.compile(r"^\d{1,2}/\d{1,2}$")


def _validate_sim_date(value: str) -> str:
    if not _DATE_PATTERN.match(value):
        raise ValueError("date must use the format 'YYYY/MM/DD'")
    return value


def _validate_month_day(value: str) -> str:
    if not _MONTH_DAY_PATTERN.match(value):
        raise ValueError("date must use the format 'MM/DD'")
    return value


class WeatherRecord(BaseModel):
    """One day of weather data in the units expected by AquaCrop-OSPy."""

    date: date
    min_temp: float = Field(description="Minimum air temperature (degC)")
    max_temp: float = Field(description="Maximum air temperature (degC)")
    precipitation: float = Field(ge=0, description="Daily precipitation (mm)")
    reference_et: float = Field(ge=0, description="Reference evapotranspiration ET0 (mm/day)")


class InlineWeather(BaseModel):
    type: Literal["inline"] = "inline"
    records: List[WeatherRecord] = Field(min_length=1)


class BuiltinWeather(BaseModel):
    type: Literal["builtin"] = "builtin"
    name: str = Field(description="File name of a bundled climate file, e.g. 'tunis_climate.txt'")


WeatherInput = Annotated[
    Union[InlineWeather, BuiltinWeather],
    Field(discriminator="type", description="Weather source for the simulation"),
]


class SoilLayer(BaseModel):
    """One soil layer described with physical/hydraulic properties."""

    thickness: float = Field(gt=0, description="Layer thickness (m)")
    th_wp: float = Field(gt=0, lt=1, description="Volumetric water content at wilting point")
    th_fc: float = Field(gt=0, lt=1, description="Volumetric water content at field capacity")
    th_s: float = Field(gt=0, lt=1, description="Volumetric water content at saturation")
    ksat: float = Field(gt=0, description="Saturated hydraulic conductivity (mm/day)")
    penetrability: float = Field(default=100.0, ge=0, le=100)

    @model_validator(mode="after")
    def _check_ordering(self) -> "SoilLayer":
        if not (self.th_wp <= self.th_fc <= self.th_s):
            raise ValueError("soil layer must satisfy th_wp <= th_fc <= th_s")
        return self


class SoilConfig(BaseModel):
    soil_type: str = Field(default="SandyLoam", description="Built-in soil name or 'custom'")
    layers: List[SoilLayer] = Field(default_factory=list)
    dz: Optional[List[float]] = Field(
        default=None,
        description="Optional compartment thicknesses (m). Defaults to 12 x 0.1 m.",
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extra kwargs forwarded to the Soil constructor (cn, rew, ...).",
    )

    @model_validator(mode="after")
    def _check_layers(self) -> "SoilConfig":
        if self.layers:
            if self.soil_type != "custom":
                raise ValueError("layers can only be provided when soil_type='custom'")
            if any(value <= 0 for value in (self.dz or [])):
                raise ValueError("dz values must be positive")
        if self.soil_type == "custom" and not self.layers:
            raise ValueError("soil_type='custom' requires at least one layer")
        return self


class CropConfig(BaseModel):
    name: str = Field(default="Maize", description="Built-in crop name or 'custom'")
    planting_date: str = Field(default="05/01", description="Planting date (MM/DD)")
    harvest_date: Optional[str] = Field(default=None, description="Latest harvest date (MM/DD)")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional crop parameter overrides (Crop kwargs).",
    )

    @field_validator("planting_date")
    @classmethod
    def _check_planting_date(cls, value: str) -> str:
        return _validate_month_day(value)

    @field_validator("harvest_date")
    @classmethod
    def _check_harvest_date(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return _validate_month_day(value)


class InitialWaterContentConfig(BaseModel):
    wc_type: Literal["Prop", "Num", "Pct"] = "Prop"
    method: Literal["Layer", "Depth"] = "Layer"
    depth_layer: List[float] = Field(default_factory=lambda: [1.0])
    value: List[Union[str, float]] = Field(default_factory=lambda: ["FC"])

    @model_validator(mode="after")
    def _check_lengths(self) -> "InitialWaterContentConfig":
        if len(self.depth_layer) != len(self.value):
            raise ValueError("depth_layer and value must have the same length")
        if not self.depth_layer:
            raise ValueError("depth_layer cannot be empty")
        return self


class IrrigationEvent(BaseModel):
    date: str = Field(description="Irrigation date (YYYY/MM/DD)")
    depth: float = Field(ge=0, description="Irrigation depth (mm)")

    @field_validator("date")
    @classmethod
    def _check_date(cls, value: str) -> str:
        return _validate_sim_date(value)


class IrrigationConfig(BaseModel):
    method: int = Field(default=0, ge=0, le=5, description="0 rainfed, 1 SMT, 2 interval, 3 schedule, 4 net, 5 depth")
    wet_surface: float = Field(default=100.0, ge=0, le=100)
    application_efficiency: float = Field(default=100.0, gt=0, le=100)
    max_irrigation: float = Field(default=25.0, ge=0)
    max_irrigation_season: float = Field(default=10_000.0, ge=0)
    smt: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    interval: int = Field(default=0, ge=0)
    net_irrigation_smt: float = Field(default=80.0, ge=0, le=100)
    depth: float = Field(default=0.0, ge=0)
    schedule: List[IrrigationEvent] = Field(default_factory=list)


class FieldManagementConfig(BaseModel):
    mulches: bool = False
    bunds: bool = False
    curve_number_adj: bool = False
    sr_inhb: bool = False
    mulch_pct: float = Field(default=50.0, ge=0, le=100)
    f_mulch: float = Field(default=0.5, ge=0, le=1)
    z_bund: float = Field(default=0.0, ge=0)
    bund_water: float = Field(default=0.0, ge=0)
    curve_number_adj_pct: float = 0.0


class GroundwaterConfig(BaseModel):
    water_table: Literal["Y", "N"] = "N"
    method: Literal["Constant", "Variable"] = "Constant"
    dates: List[str] = Field(default_factory=list)
    values: List[float] = Field(default_factory=list)

    @field_validator("dates")
    @classmethod
    def _check_dates(cls, values: List[str]) -> List[str]:
        for value in values:
            _validate_sim_date(value)
        return values

    @model_validator(mode="after")
    def _check_lengths(self) -> "GroundwaterConfig":
        if self.water_table == "Y" and len(self.dates) != len(self.values):
            raise ValueError("groundwater dates and values must have the same length")
        return self


class CO2Config(BaseModel):
    ref_concentration: float = 369.41
    current_concentration: float = 0.0
    constant_conc: bool = False
    scenario: Optional[str] = Field(default=None, description="e.g. ssp245; defaults to Mauna Loa")


class SimulationOptions(BaseModel):
    include_water_flux: bool = False
    include_water_storage: bool = False
    include_crop_growth: bool = False


class SimulationRequest(BaseModel):
    sim_start_time: str
    sim_end_time: str
    weather: WeatherInput
    soil: SoilConfig = Field(default_factory=SoilConfig)
    crop: CropConfig = Field(default_factory=CropConfig)
    initial_water_content: InitialWaterContentConfig = Field(default_factory=InitialWaterContentConfig)
    irrigation: IrrigationConfig = Field(default_factory=IrrigationConfig)
    field_management: FieldManagementConfig = Field(default_factory=FieldManagementConfig)
    fallow_field_management: FieldManagementConfig = Field(default_factory=FieldManagementConfig)
    groundwater: GroundwaterConfig = Field(default_factory=GroundwaterConfig)
    co2: CO2Config = Field(default_factory=CO2Config)
    off_season: bool = False
    options: SimulationOptions = Field(default_factory=SimulationOptions)

    @field_validator("sim_start_time", "sim_end_time")
    @classmethod
    def _check_dates(cls, value: str) -> str:
        return _validate_sim_date(value)


class SeasonSpec(BaseModel):
    sim_start_time: str
    sim_end_time: str
    crop: CropConfig
    irrigation: Optional[IrrigationConfig] = None
    off_season: bool = False

    @field_validator("sim_start_time", "sim_end_time")
    @classmethod
    def _check_dates(cls, value: str) -> str:
        return _validate_sim_date(value)


class RotationRequest(BaseModel):
    weather: WeatherInput
    soil: SoilConfig = Field(default_factory=SoilConfig)
    seasons: List[SeasonSpec] = Field(min_length=1)
    initial_water_content: InitialWaterContentConfig = Field(default_factory=InitialWaterContentConfig)
    irrigation: IrrigationConfig = Field(default_factory=IrrigationConfig)
    field_management: FieldManagementConfig = Field(default_factory=FieldManagementConfig)
    fallow_field_management: FieldManagementConfig = Field(default_factory=FieldManagementConfig)
    groundwater: GroundwaterConfig = Field(default_factory=GroundwaterConfig)
    co2: CO2Config = Field(default_factory=CO2Config)
    carry_water_between_seasons: bool = True
    options: SimulationOptions = Field(default_factory=SimulationOptions)


class PlantingDateRequest(BaseModel):
    sim_start_time: str
    sim_end_time: str
    weather: WeatherInput
    soil: SoilConfig = Field(default_factory=SoilConfig)
    crop: CropConfig
    candidate_planting_dates: List[str] = Field(min_length=1)
    initial_water_content: InitialWaterContentConfig = Field(default_factory=InitialWaterContentConfig)
    irrigation: IrrigationConfig = Field(default_factory=IrrigationConfig)
    field_management: FieldManagementConfig = Field(default_factory=FieldManagementConfig)
    groundwater: GroundwaterConfig = Field(default_factory=GroundwaterConfig)
    co2: CO2Config = Field(default_factory=CO2Config)

    @field_validator("sim_start_time", "sim_end_time")
    @classmethod
    def _check_dates(cls, value: str) -> str:
        return _validate_sim_date(value)

    @field_validator("candidate_planting_dates")
    @classmethod
    def _check_candidates(cls, values: List[str]) -> List[str]:
        for value in values:
            _validate_month_day(value)
        return values


class SimulationResponse(BaseModel):
    success: bool = True
    execution_time_seconds: float
    final_stats: List[Dict[str, Any]] = Field(default_factory=list)
    water_flux: Optional[List[Dict[str, Any]]] = None
    water_storage: Optional[List[Dict[str, Any]]] = None
    crop_growth: Optional[List[Dict[str, Any]]] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class RotationSeasonResult(BaseModel):
    index: int
    crop: str
    sim_start_time: str
    sim_end_time: str
    execution_time_seconds: float
    final_stats: List[Dict[str, Any]] = Field(default_factory=list)


class RotationResponse(BaseModel):
    success: bool = True
    seasons: List[RotationSeasonResult] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)


class PlantingDateResult(BaseModel):
    planting_date: str
    execution_time_seconds: float
    final_stats: List[Dict[str, Any]] = Field(default_factory=list)


class PlantingDateResponse(BaseModel):
    success: bool = True
    results: List[PlantingDateResult] = Field(default_factory=list)
