from __future__ import annotations

import json
from datetime import datetime
from typing import List, Union, Optional

from pydantic import BaseModel, Field


class Validation(BaseModel):
    success: Optional[bool] = Field(alias="Success", default=False)
    forest_version: Optional[str] = Field(alias="Forest version", default="unknown")
    lotus_version: Optional[str] = Field(alias="Lotus version", default="unknown")
    validation_date: Optional[datetime] = Field(alias="Validation date", default=None)

    model_config = dict(populate_by_name=True)


class BuildInformation(BaseModel):
    epoch: Optional[int] = Field(alias="Epoch", default=0)
    epoch_date: Optional[datetime] = Field(alias="Epoch date", default=None)
    build_path: Optional[str] = Field(alias="Build path", default="")
    build_timestamp: Optional[str] = Field(alias="Build timestamp", default="")
    build_date: Optional[datetime] = Field(alias="Build date", default=None)  # ISO8601 string
    validation: Optional[Validation] = Field(alias="Validation", default_factory=Validation)

    model_config = dict(populate_by_name=True)


class Snapshot(BaseModel):
    snapshot_version: str = Field(alias="Snapshot version")
    head_tipset: Union[str, List[str]] = Field(alias="Head Tipset")
    f3_data: Optional[str] = Field(alias="F3 data", default=None)
    f3_snapshot_version: Optional[str] = Field(alias="F3 snapshot version", default=None)
    f3_snapshot_first_instance: Optional[int] = Field(alias="F3 snapshot first instance", default=None)
    f3_snapshot_last_instance: Optional[int] = Field(alias="F3 snapshot last instance", default=None)
    car_format: str = Field(alias="CAR format")
    network: str = Field(alias="Network")
    epoch: int = Field(alias="Epoch")
    state_roots: int = Field(alias="State-roots")
    sha256: Optional[str] = Field(alias="Sha256", default=None)
    messages_sets: int = Field(alias="Messages sets")
    index_size: str = Field(alias="Index size")

    model_config = dict(populate_by_name=True)


class SnapshotMetadata(BaseModel):
    snapshot: Snapshot = Field(alias="Snapshot")
    build_information: Optional[BuildInformation] = Field(alias="Build Information", default_factory=BuildInformation)

    model_config = dict(populate_by_name=True)

    # ---------- Helper methods ----------
    @classmethod
    def from_json(cls, raw: Union[str, dict]) -> "SnapshotMetadata":
        """
        Create a SnapshotMetadata object from a JSON string or a Python dict.
        """
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw
        return cls.model_validate(data)

    def to_json(self, *, by_alias: bool = True, indent: int = 2) -> str:
        """
        Dump the object back to a JSON string.
        Set by_alias=False to use snake_case field names instead.
        """
        return self.model_dump_json(by_alias=by_alias, indent=indent)
