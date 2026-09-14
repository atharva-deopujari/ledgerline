"""The one definition of what a phone number is, used wherever one arrives from outside.

Ten digits is what an Indian caller types; E.164 is what anything else looks like. Validating in
code at the boundary means the rest of the app never asks the question again, and a bad number
is a 422 from FastAPI rather than a row keyed on a typo.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Path
from pydantic import Field

PHONE_PATTERN = r"^(?:\d{10}|\+[1-9]\d{7,14})$"

# In a request body.
PhoneField = Field(pattern=PHONE_PATTERN, description="Ten digits, or E.164 with a + prefix.")

# In a path.
PhonePath = Annotated[str, Path(pattern=PHONE_PATTERN)]
