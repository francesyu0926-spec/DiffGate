import pytest
from pydantic import ValidationError

from app.api.schemas import TestSuiteCreate


def test_test_suite_slug_pattern_ok():
    row = TestSuiteCreate(slug="order-service-cases", name="Order")
    assert row.slug == "order-service-cases"


def test_test_suite_slug_rejects_uppercase():
    with pytest.raises(ValidationError):
        TestSuiteCreate(slug="Order-Service", name="x")