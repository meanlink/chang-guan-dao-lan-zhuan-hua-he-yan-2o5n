from pydantic import BaseModel, Field


class RuleItem(BaseModel):
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)


class VersionInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    note: str = Field(default='', max_length=500)
    rules: list[RuleItem] = Field(min_length=1, max_length=500)
    dataset_ids: list[int] = Field(min_length=1, max_length=50)


class ProgressInput(BaseModel):
    """Reserved for future filtering; kept so the page contract stays explicit."""
    dataset_id: int | None = None
