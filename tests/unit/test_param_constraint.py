import pytest
from pydantic import ValidationError

from mcp_gateway.policy.models import ParamConstraint


def test_param_constraint_max_length_limit():
    # 4096 is the new limit
    ParamConstraint(type="string", max_length=4096)

    with pytest.raises(ValidationError) as excinfo:
        ParamConstraint(type="string", max_length=4097)
    assert "max_length exceeds ReDoS mitigation limit (4096)" in str(excinfo.value)


def test_param_constraint_type_none_flexibility():
    # type=None should allow pattern and max_length
    pc = ParamConstraint(type=None, pattern=".*", max_length=100)
    assert pc.type is None
    assert pc.pattern == ".*"
    assert pc.max_length == 100


def test_param_constraint_homogeneous_allowed_values_when_type_none():
    # Homogeneous values should pass
    ParamConstraint(type=None, allowed_values=["a", "b", "c"])
    ParamConstraint(type=None, allowed_values=[1, 2, 3])

    # Mixture of types should fail
    with pytest.raises(ValidationError) as excinfo:
        ParamConstraint(type=None, allowed_values=["a", 1])
    assert "allowed_values must be homogeneous when type is None" in str(excinfo.value)


def test_param_constraint_type_string_validation():
    # Valid string constraint
    ParamConstraint(type="string", pattern="^[a-z]+$", max_length=10)

    # Invalid allowed_values type for string
    with pytest.raises(ValidationError) as excinfo:
        ParamConstraint(type="string", allowed_values=[123])
    assert "allowed_values must be string, got int" in str(excinfo.value)


def test_param_constraint_integer_rejects_string_fields():
    # integer should NOT allow pattern or max_length
    with pytest.raises(ValidationError) as excinfo:
        ParamConstraint(type="integer", pattern=".*")
    assert "pattern is only allowed for type='string'" in str(excinfo.value)

    with pytest.raises(ValidationError) as excinfo:
        ParamConstraint(type="integer", max_length=10)
    assert "max_length is only allowed for type='string'" in str(excinfo.value)


def test_param_constraint_number_compatibility():
    # number allows both int and float
    ParamConstraint(type="number", allowed_values=[1, 2.5, 3])

    with pytest.raises(ValidationError) as excinfo:
        ParamConstraint(type="number", allowed_values=["not a number"])
    assert "allowed_values must be number, got str" in str(excinfo.value)
