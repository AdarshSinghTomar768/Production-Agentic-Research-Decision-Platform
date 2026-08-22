"""Structured output of the Planner agent."""

import re

from pydantic import BaseModel, Field, field_validator, model_validator


class SubTask(BaseModel):
    task_id: str = Field(pattern=r"^t\d{1,2}$")
    description: str
    search_query: str  # concrete query string handed to research tools
    needs_web: bool = True
    needs_rag: bool = False
    needs_data: bool = False

    @field_validator("description", "search_query")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class ResearchPlan(BaseModel):
    objective: str  # restated, sharpened version of the user question
    success_criteria: list[str] = Field(min_length=1, max_length=6)
    subtasks: list[SubTask] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _unique_task_ids(self) -> "ResearchPlan":
        ids = [s.task_id for s in self.subtasks]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate task_id values in plan: {ids}")
        if any(not re.match(r"^t\d+$", i) for i in ids):
            raise ValueError("task_ids must look like t1, t2, ...")
        return self
