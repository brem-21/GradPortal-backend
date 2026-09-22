from pydantic import BaseModel, Field


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Message(BaseModel):
    detail: str
