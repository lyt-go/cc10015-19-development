"""领域服务注册表：通用资源路由按模块 key 分派到独立业务服务。"""
from __future__ import annotations

from app.services.base import BaseModuleService
from app.services.cruise_plan import CruisePlanService
from app.services.station_deploy import StationDeployService
from app.services.equipment_manifest import EquipmentManifestService
from app.services.sampling_record import SamplingRecordService
from app.services.hydro_measure import HydroMeasureService
from app.services.bio_trawl import BioTrawlService
from app.services.sediment_sample import SedimentSampleService
from app.services.data_qc import DataQcService
from app.services.crew_schedule import CrewScheduleService
from app.services.weather_obs import WeatherObsService
from app.services.sample_registry import SampleRegistryService
from app.services.analysis_request import AnalysisRequestService
from app.services.cruise_log import CruiseLogService
from app.services.instrument_calib import InstrumentCalibService
from app.services.diving_ops import DivingOpsService
from app.services.duty_confirmation import DutyConfirmationService
from app.services.data_transfer import DataTransferService
from app.services.track_record import TrackRecordService
from app.services.results_compile import ResultsCompileService

SERVICES: dict[str, BaseModuleService] = {
    "cruise_plan": CruisePlanService(),
    "station_deploy": StationDeployService(),
    "equipment_manifest": EquipmentManifestService(),
    "sampling_record": SamplingRecordService(),
    "hydro_measure": HydroMeasureService(),
    "bio_trawl": BioTrawlService(),
    "sediment_sample": SedimentSampleService(),
    "data_qc": DataQcService(),
    "crew_schedule": CrewScheduleService(),
    "weather_obs": WeatherObsService(),
    "sample_registry": SampleRegistryService(),
    "analysis_request": AnalysisRequestService(),
    "cruise_log": CruiseLogService(),
    "instrument_calib": InstrumentCalibService(),
    "diving_ops": DivingOpsService(),
    "duty_confirmation": DutyConfirmationService(),
    "data_transfer": DataTransferService(),
    "track_record": TrackRecordService(),
    "results_compile": ResultsCompileService(),
}


def service_for(module: str) -> BaseModuleService | None:
    return SERVICES.get(module)
