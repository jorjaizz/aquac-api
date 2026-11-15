"""Convert API payloads into AquaCrop-OSPy objects and run the model."""
from __future__ import annotations

import os
import re
import time
from typing import Any

os.environ.setdefault("DEVELOPMENT", "True")

import pandas as pd

from aquacrop import (
    CO2,
    AquaCropModel,
    Crop,
    FieldMngt,
    GroundWater,
    InitialWaterContent,
    IrrigationManagement,
    Soil,
)

from api.schemas import (
    CO2Config,
    CropConfig,
    FieldManagementConfig,
    GroundwaterConfig,
    InitialWaterContentConfig,
    IrrigationConfig,
    PlantingDateRequest,
    RotationRequest,
    SeasonSpec,
    SimulationOptions,
    SimulationRequest,
    SoilConfig,
)
from api.services.serialization import dataframe_to_records
from api.services.weather import WeatherError, load_weather


class SimulationError(ValueError):
    """Raised when the model cannot be built or executed."""


def build_soil(config: SoilConfig) -> Soil:
    kwargs = dict(config.parameters)
    if config.dz is not None:
        kwargs["dz"] = list(config.dz)
    try:
        soil = Soil(soil_type=config.soil_type, **kwargs)
    except Exception as exc:  # pragma: no cover - depends on model internals
        raise SimulationError(f"invalid soil configuration: {exc}") from exc

    for layer in config.layers:
        try:
            soil.add_layer(
                thickness=layer.thickness,
                thWP=layer.th_wp,
                thFC=layer.th_fc,
                thS=layer.th_s,
                Ksat=layer.ksat,
                penetrability=layer.penetrability,
            )
        except Exception as exc:  # pragma: no cover - depends on model internals
            raise SimulationError(f"invalid soil layer: {exc}") from exc
    return soil


def build_crop(config: CropConfig) -> Crop:
    try:
        return Crop(
            config.name,
            planting_date=config.planting_date,
            harvest_date=config.harvest_date,
            **config.parameters,
        )
    except Exception as exc:
        raise SimulationError(f"invalid crop configuration: {exc}") from exc


def build_initial_water_content(config: InitialWaterContentConfig) -> InitialWaterContent:
    return InitialWaterContent(
        wc_type=config.wc_type,
        method=config.method,
        depth_layer=list(config.depth_layer),
        value=list(config.value),
    )


def build_irrigation(config: IrrigationConfig) -> IrrigationManagement:
    kwargs: dict[str, Any] = {
        "WetSurf": config.wet_surface,
        "AppEff": config.application_efficiency,
        "MaxIrr": config.max_irrigation,
        "MaxIrrSeason": config.max_irrigation_season,
        "SMT": list(config.smt),
        "IrrInterval": config.interval,
        "NetIrrSMT": config.net_irrigation_smt,
        "depth": config.depth,
    }
    if config.schedule:
        schedule = pd.DataFrame(
            {
                "Date": pd.to_datetime([event.date for event in config.schedule]),
                "Depth": [event.depth for event in config.schedule],
            }
        )
        kwargs["Schedule"] = schedule
    return IrrigationManagement(irrigation_method=config.method, **kwargs)


def build_field_management(config: FieldManagementConfig) -> FieldMngt:
    return FieldMngt(
        mulches=config.mulches,
        bunds=config.bunds,
        curve_number_adj=config.curve_number_adj,
        sr_inhb=config.sr_inhb,
        mulch_pct=config.mulch_pct,
        f_mulch=config.f_mulch,
        z_bund=config.z_bund,
        bund_water=config.bund_water,
        curve_number_adj_pct=config.curve_number_adj_pct,
    )


def build_groundwater(config: GroundwaterConfig) -> GroundWater:
    return GroundWater(
        water_table=config.water_table,
        method=config.method,
        dates=list(config.dates),
        values=list(config.values),
    )


def build_co2(config: CO2Config) -> CO2:
    kwargs: dict[str, Any] = {
        "ref_concentration": config.ref_concentration,
        "current_concentration": config.current_concentration,
        "constant_conc": config.constant_conc,
    }
    if config.scenario:
        kwargs["scenario"] = config.scenario
    try:
        return CO2(**kwargs)
    except Exception as exc:
        raise SimulationError(f"invalid CO2 configuration: {exc}") from exc


def _optional_series(model: AquaCropModel, options: SimulationOptions) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if options.include_water_flux:
        payload["water_flux"] = dataframe_to_records(model.get_water_flux())
    if options.include_water_storage:
        payload["water_storage"] = dataframe_to_records(model.get_water_storage())
    if options.include_crop_growth:
        payload["crop_growth"] = dataframe_to_records(model.get_crop_growth())
    return payload


def _run_model(
    *,
    weather_df: pd.DataFrame,
    soil: Soil,
    crop: Crop,
    initial_water_content: InitialWaterContent,
    irrigation: IrrigationManagement,
    field_management: FieldMngt,
    fallow_field_management: FieldMngt,
    groundwater: GroundWater,
    co2: CO2,
    sim_start_time: str,
    sim_end_time: str,
    off_season: bool,
    options: SimulationOptions,
) -> tuple[AquaCropModel, dict[str, Any], float]:
    try:
        model = AquaCropModel(
            sim_start_time=sim_start_time,
            sim_end_time=sim_end_time,
            weather_df=weather_df,
            soil=soil,
            crop=crop,
            initial_water_content=initial_water_content,
            irrigation_management=irrigation,
            field_management=field_management,
            fallow_field_management=fallow_field_management,
            groundwater=groundwater,
            co2_concentration=co2,
            off_season=off_season,
        )
    except Exception as exc:
        raise SimulationError(f"invalid simulation configuration: {exc}") from exc

    started = time.perf_counter()
    try:
        model.run_model(till_termination=True)
    except Exception as exc:
        raise SimulationError(f"model execution failed: {exc}") from exc
    elapsed = time.perf_counter() - started

    final_stats = dataframe_to_records(model.get_simulation_results())
    payload: dict[str, Any] = {
        "success": True,
        "execution_time_seconds": round(elapsed, 4),
        "final_stats": final_stats,
        **_optional_series(model, options),
    }
    return model, payload, elapsed


def _carried_water_content(model: AquaCropModel) -> InitialWaterContent:
    water_storage = model.get_water_storage()
    th_columns = [column for column in water_storage.columns if re.fullmatch(r"th\d+", str(column))]
    if not th_columns:
        raise SimulationError("model did not report soil water storage for carry-over")

    last = water_storage.iloc[-1]
    profile = model.soil.profile
    midpoints = ((profile["z_top"] + profile["zBot"]) / 2).astype(float).tolist()
    values = [float(last[column]) for column in th_columns]

    if len(midpoints) != len(values):
        raise SimulationError("soil profile and water storage output are inconsistent")

    return InitialWaterContent(
        wc_type="Num",
        method="Depth",
        depth_layer=midpoints,
        value=values,
    )


def _meta(weather_df: pd.DataFrame, sim_start_time: str, sim_end_time: str, final_stats: list[dict]) -> dict[str, Any]:
    start = pd.Timestamp(sim_start_time)
    end = pd.Timestamp(sim_end_time)
    window = weather_df[(weather_df["Date"] >= start) & (weather_df["Date"] <= end)]
    used = window if not window.empty else weather_df
    return {
        "sim_start_time": sim_start_time,
        "sim_end_time": sim_end_time,
        "n_seasons": len(final_stats),
        "n_weather_days": int(len(used)),
        "weather_start": used["Date"].iloc[0].date().isoformat(),
        "weather_end": used["Date"].iloc[-1].date().isoformat(),
    }


def run_simulation(request: SimulationRequest) -> dict[str, Any]:
    try:
        weather_df = load_weather(request.weather)
    except WeatherError as exc:
        raise SimulationError(str(exc)) from exc

    model, payload, _ = _run_model(
        weather_df=weather_df,
        soil=build_soil(request.soil),
        crop=build_crop(request.crop),
        initial_water_content=build_initial_water_content(request.initial_water_content),
        irrigation=build_irrigation(request.irrigation),
        field_management=build_field_management(request.field_management),
        fallow_field_management=build_field_management(request.fallow_field_management),
        groundwater=build_groundwater(request.groundwater),
        co2=build_co2(request.co2),
        sim_start_time=request.sim_start_time,
        sim_end_time=request.sim_end_time,
        off_season=request.off_season,
        options=request.options,
    )
    payload["meta"] = {
        **_meta(weather_df, request.sim_start_time, request.sim_end_time, payload["final_stats"]),
        "crop": request.crop.name,
        "soil": request.soil.soil_type,
    }
    return payload


def _run_season(
    *,
    weather_df: pd.DataFrame,
    soil_config: SoilConfig,
    season: SeasonSpec,
    initial_water_content: InitialWaterContent,
    irrigation_config: IrrigationConfig,
    rotation: RotationRequest,
) -> tuple[AquaCropModel, dict[str, Any], float]:
    irrigation = season.irrigation or irrigation_config
    return _run_model(
        weather_df=weather_df,
        soil=build_soil(soil_config),
        crop=build_crop(season.crop),
        initial_water_content=initial_water_content,
        irrigation=build_irrigation(irrigation),
        field_management=build_field_management(rotation.field_management),
        fallow_field_management=build_field_management(rotation.fallow_field_management),
        groundwater=build_groundwater(rotation.groundwater),
        co2=build_co2(rotation.co2),
        sim_start_time=season.sim_start_time,
        sim_end_time=season.sim_end_time,
        off_season=season.off_season,
        options=rotation.options,
    )


def run_rotation(request: RotationRequest) -> dict[str, Any]:
    try:
        weather_df = load_weather(request.weather)
    except WeatherError as exc:
        raise SimulationError(str(exc)) from exc

    initial_water_content = build_initial_water_content(request.initial_water_content)
    seasons: list[dict[str, Any]] = []
    all_stats: list[dict[str, Any]] = []

    for index, season in enumerate(request.seasons):
        model, payload, elapsed = _run_season(
            weather_df=weather_df,
            soil_config=request.soil,
            season=season,
            initial_water_content=initial_water_content,
            irrigation_config=request.irrigation,
            rotation=request,
        )
        if not payload["final_stats"]:
            raise SimulationError(
                f"season {index + 1} ({season.crop.name}, "
                f"{season.sim_start_time} to {season.sim_end_time}) produced no harvest results"
            )
        display_crop = season.crop.display_name or season.crop.name
        for stat in payload["final_stats"]:
            stat["crop Type"] = display_crop
        all_stats.extend(payload["final_stats"])
        seasons.append(
            {
                "index": index,
                "crop": display_crop,
                "sim_start_time": season.sim_start_time,
                "sim_end_time": season.sim_end_time,
                "execution_time_seconds": round(elapsed, 4),
                "final_stats": payload["final_stats"],
            }
        )
        if request.carry_water_between_seasons:
            initial_water_content = _carried_water_content(model)

    yields = [
        float(record["Dry yield (tonne/ha)"])
        for record in all_stats
        if record.get("Dry yield (tonne/ha)") is not None
    ]
    fresh_yields = [
        float(record["Fresh yield (tonne/ha)"])
        for record in all_stats
        if record.get("Fresh yield (tonne/ha)") is not None
    ]
    irrigation_total = sum(
        float(record["Seasonal irrigation (mm)"])
        for record in all_stats
        if record.get("Seasonal irrigation (mm)") is not None
    )
    summary = {
        "n_seasons": len(seasons),
        "mean_dry_yield_tonne_ha": round(sum(yields) / len(yields), 4) if yields else None,
        "mean_fresh_yield_tonne_ha": round(sum(fresh_yields) / len(fresh_yields), 4) if fresh_yields else None,
        "total_seasonal_irrigation_mm": round(irrigation_total, 4),
        "carry_water_between_seasons": request.carry_water_between_seasons,
    }
    return {"success": True, "seasons": seasons, "summary": summary}


def run_planting_dates(request: PlantingDateRequest) -> dict[str, Any]:
    try:
        weather_df = load_weather(request.weather)
    except WeatherError as exc:
        raise SimulationError(str(exc)) from exc

    results: list[dict[str, Any]] = []
    for planting_date in request.candidate_planting_dates:
        crop_config = request.crop.model_copy(update={"planting_date": planting_date})
        _, payload, elapsed = _run_model(
            weather_df=weather_df,
            soil=build_soil(request.soil),
            crop=build_crop(crop_config),
            initial_water_content=build_initial_water_content(request.initial_water_content),
            irrigation=build_irrigation(request.irrigation),
            field_management=build_field_management(request.field_management),
            fallow_field_management=build_field_management(FieldManagementConfig()),
            groundwater=build_groundwater(request.groundwater),
            co2=build_co2(request.co2),
            sim_start_time=request.sim_start_time,
            sim_end_time=request.sim_end_time,
            off_season=False,
            options=SimulationOptions(),
        )
        results.append(
            {
                "planting_date": planting_date,
                "execution_time_seconds": round(elapsed, 4),
                "final_stats": payload["final_stats"],
            }
        )
    return {"success": True, "results": results}
