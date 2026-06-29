from pydantic import BaseModel, Field
from typing import List, Optional

class WordSchema(BaseModel):
    """Schema representing a single HSK vocabulary word."""
    id: int = Field(..., description="Unique word identifier")
    word: str = Field(..., description="The Chinese characters of the word")
    pinyin: Optional[str] = Field(None, description="Pinyin pronunciation")
    definition: Optional[str] = Field(None, description="English definition / translation")
    definition_th: Optional[str] = Field(None, description="Thai definition / translation")
    level: Optional[int] = Field(None, description="HSK Level (1-6) or Null if not applicable")
    example_sentence: Optional[str] = Field(None, description="An example sentence in Chinese")
    example_pinyin: Optional[str] = Field(None, description="Pinyin pronunciation of the example sentence")

    class Config:
        from_attributes = True

class PaginationMetadata(BaseModel):
    """Metadata detailing the state of pagination."""
    total_records: int = Field(..., description="Total count of matching records")
    total_pages: int = Field(..., description="Total pages based on per_page limit")
    page: int = Field(..., description="The current active page")
    per_page: int = Field(..., description="Count of records returned per page")
    has_next: bool = Field(..., description="Indicates if there is a next page")
    has_previous: bool = Field(..., description="Indicates if there is a previous page")

class PaginatedResponse(BaseModel):
    """Unified paginated response structure wrapper."""
    metadata: PaginationMetadata = Field(..., description="Pagination info")
    data: List[WordSchema] = Field(..., description="List of HSK vocabulary words")

class KeyCreateSchema(BaseModel):
    """Schema representing request body for creating a new API Key."""
    name: str = Field(..., min_length=1, max_length=100, description="The name or label identifying the API Key owner")

class KeyResponseSchema(BaseModel):
    """Schema representing detail parameters of an API Key."""
    id: int = Field(..., description="Unique database ID of the API Key record")
    key: str = Field(..., description="The actual API Key token to use in request headers")
    name: str = Field(..., description="The name/label attached to the API Key")
    is_active: bool = Field(..., description="Indicates if the API Key is active (1 = active, 0 = inactive)")
    created_at: str = Field(..., description="Timestamp of when the API Key was generated")
    revoked_at: Optional[str] = Field(None, description="Timestamp of when the API Key was revoked")

    class Config:
        from_attributes = True
