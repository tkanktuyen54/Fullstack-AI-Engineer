from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, SecretStr, model_validator


class Course(BaseModel):
  slug: str = Field(pattern=r"^[a-z0-9-]{1,150}$")
  title: str = Field(min_length=1, max_length=200)
  price: Decimal = Field(ge=0, le=999999999999, decimal_places=0)
  level: str = Field(default="Chưa cập nhật", max_length=60)
  category: str = Field(default="", max_length=60)
  description: str = Field(default="", max_length=12000)
  subtitle: str = Field(default="", max_length=300)
  instructor: str = Field(default="", max_length=100)
  hours: float = Field(default=0, ge=0, le=9999)
  outcomes: List[str] = Field(default_factory=list, max_length=30)
  audience: str = Field(default="", max_length=3000)
  prerequisites: str = Field(default="", max_length=3000)

  def document(self) -> str:
    return " ".join(
      [
        self.title,
        self.title,
        self.title,
        self.category,
        self.category,
        self.subtitle,
        self.description,
        " ".join(self.outcomes),
        self.audience,
        self.prerequisites,
      ]
    )


class Turn(BaseModel):
  role: str = Field(pattern=r"^(user|assistant)$")
  content: str = Field(max_length=12000)


class ModelSelection(BaseModel):
  provider: Literal["local", "groq"] = "local"
  model: str = Field(min_length=1, max_length=150, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")
  apiKey: Optional[SecretStr] = Field(default=None, exclude=True, repr=False, max_length=256)

  @model_validator(mode="after")
  def validate_selection(self):
    if self.provider == "local" and self.model.endswith("-cloud"):
      raise ValueError("Chỉ hỗ trợ model Ollama local.")
    if self.provider == "groq" and (
      self.apiKey is None or not self.apiKey.get_secret_value().strip()
    ):
      raise ValueError("Groq cần API key.")
    return self


class AdviceRequest(BaseModel):
  message: str = Field(min_length=1, max_length=2000)
  topic: Literal["courses", "secops"] = "courses"
  courseSlug: Optional[str] = Field(default=None, pattern=r"^[a-z0-9-]{1,150}$")
  history: List[Turn] = Field(default_factory=list, max_length=12)
  courses: List[Course] = Field(default_factory=list, max_length=5000)
  llm: Optional[ModelSelection] = None


class Suggestion(BaseModel):
  slug: str
  title: str
  price: Decimal
  level: str
  reason: str


class DocumentSource(BaseModel):
  title: str
  url: str


class AdviceReply(BaseModel):
  message: str
  intent: str
  courses: List[Suggestion]
  engine: str
  sources: List[DocumentSource] = Field(default_factory=list)
  answerMode: Literal["course", "generated", "extractive", "not_found", "blocked"] = "course"
  fallbackReason: Optional[str] = None
