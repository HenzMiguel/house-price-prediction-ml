import math

import pytest
from pydantic import ValidationError

from house_price.api.schemas import HousingInstance, PredictionRequest

VALID = {
    "MedInc": 8.3,
    "HouseAge": 41,
    "AveRooms": 6.9,
    "AveBedrms": 1.0,
    "Population": 322,
    "AveOccup": 2.5,
    "Latitude": 37.8,
    "Longitude": -122.2,
}


def test_request_accepts_one_to_one_hundred_strict_instances() -> None:
    assert len(PredictionRequest(instances=[VALID]).instances) == 1
    assert len(PredictionRequest(instances=[VALID] * 100).instances) == 100
    with pytest.raises(ValidationError):
        PredictionRequest(instances=[])
    with pytest.raises(ValidationError):
        PredictionRequest(instances=[VALID] * 101)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("MedInc", -1),
        ("HouseAge", -1),
        ("AveRooms", 0),
        ("AveBedrms", -1),
        ("Population", -1),
        ("AveOccup", 0),
        ("Latitude", 91),
        ("Longitude", -181),
        ("MedInc", math.inf),
    ],
)
def test_invalid_constraints_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        HousingInstance(**{**VALID, field: value})


def test_missing_and_extra_fields_are_rejected() -> None:
    missing = {key: value for key, value in VALID.items() if key != "MedInc"}
    with pytest.raises(ValidationError):
        HousingInstance(**missing)
    with pytest.raises(ValidationError):
        HousingInstance(**VALID, unknown=1)

