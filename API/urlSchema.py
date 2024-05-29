from pydantic import BaseModel, validator, Field


class AddUrlValidation(BaseModel):
    path: str
    signature: str
    method: str
    cache: bool | None = False


class AddListUrlValidation(BaseModel):
    data: list


class DeleteUrlValidation(BaseModel):
    id: int


