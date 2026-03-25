"""Pydantic schemas for the template plugin."""
from pydantic import BaseModel


class DoThingInput(BaseModel):
    value: str


class DoThingOutput(BaseModel):
    result: str