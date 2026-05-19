from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, conint, confloat


BlockType = Literal["text", "table", "sql", "figure"]
Difficulty = Literal["하", "중", "상"]
QuestionFormat = Literal["4지선다", "단답형", "OX"]


class OCRBlock(BaseModel):
    type: BlockType
    bbox: list[int] = Field(min_length=4, max_length=4)
    text: str
    confidence: confloat(ge=0.0, le=1.0) = 1.0


class OCRPage(BaseModel):
    page: conint(ge=1)
    blocks: list[OCRBlock]


class RawOCR(BaseModel):
    source_id: str
    pages: list[OCRPage]


class Topic(BaseModel):
    id: str
    과목: str
    대분류: str
    중분류: str
    소분류: str
    난이도: Difficulty
    format: QuestionFormat
    frequency: conint(ge=0)
    common_distractor_themes: list[str] = Field(default_factory=list)


class TopicMap(BaseModel):
    subject: str
    topics: list[Topic]


class Question(BaseModel):
    id: str
    topic_id: str
    difficulty: Difficulty
    stem: str
    choices: list[str] = Field(min_length=4, max_length=4)
    answer_index: conint(ge=0, le=3)
    explanation: str
    sql_snippet: Optional[str] = None
    syllabus_ref: str
    generated_by: str
    self_critique_passed: bool = False
    derivative_max_similarity: Optional[confloat(ge=0.0, le=1.0)] = None
    round: Optional[conint(ge=1, le=99)] = None
    round_idx: Optional[conint(ge=1, le=999)] = None


class QuestionBank(BaseModel):
    items: list[Question]


class VariantQuestion(Question):
    source_question_id: Optional[str] = None
    variant_type: Literal["paraphrase", "number_swap", "distractor_swap", "format_shift"]


class VariantBank(BaseModel):
    items: list[VariantQuestion]
