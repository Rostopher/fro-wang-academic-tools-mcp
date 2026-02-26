from __future__ import annotations

import pytest
from pydantic import ValidationError

from academic_tools.models.structure import SectionList


def test_section_list_rejects_non_object_items() -> None:
    with pytest.raises(ValidationError):
        SectionList.model_validate(["bad", "output"])


def test_section_list_rejects_non_list_subtitles() -> None:
    with pytest.raises(ValidationError):
        SectionList.model_validate(
            [
                {
                    "title": "Intro",
                    "level": 1,
                    "sub_title_list": "not-a-list",
                }
            ]
        )

