from pydantic import BaseModel, validator, Field


class AddUrlValidation(BaseModel):
    id: int
    path: str
    signature: str
    method: str
    cache: bool | None = False,
    project_id: int
    project_name: str


class AddListUrlValidation(BaseModel):
    data: list


class DeleteUrlValidation(BaseModel):
    id: int


class GetServersResourceValidator(BaseModel):
    resourceToken: str = Field(..., description="Unique identifier of the resource")
    containerNames: list[str] = Field(..., description="Names of the containers")
