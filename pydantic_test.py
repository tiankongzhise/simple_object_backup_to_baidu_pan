from pydantic import BaseModel, field_validator
from pathlib import Path
from typing import Literal

class TestFormatData(BaseModel):
    object_path: str
    name: str

    @field_validator("object_path")
    def validate_object_path(cls, v):
        print(f"Validator called with: {repr(v)}")
        if not Path(v).exists():
            raise ValueError(f"Path {v} not exist")
        return v

# Test 1: Normal case
print("=== Test 1: Normal string ===")
try:
    data = TestFormatData(object_path="C:/", name="test")
    print(f"Success: {data}")
except Exception as e:
    print(f"Error: {e}")

# Test 2: None value
print("\n=== Test 2: None value ===")
try:
    data = TestFormatData(object_path=None, name="test")
    print(f"Success: {data}")
except Exception as e:
    print(f"Error: {e}")

# Test 3: Empty string
print("\n=== Test 3: Empty string ===")
try:
    data = TestFormatData(object_path="", name="test")
    print(f"Success: {data}")
except Exception as e:
    print(f"Error: {e}")
