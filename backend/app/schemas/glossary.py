from pydantic import BaseModel
from typing import List, Optional


class GlossaryEntry(BaseModel):
    """名詞解釋條目"""
    id: str
    term: str
    category: str
    importance: str
    content: str  # Markdown 格式，支援 LaTeX 公式
    tags: List[str]


class GlossaryResponse(BaseModel):
    """名詞解釋完整回應"""
    version: str
    last_updated: str
    entries: List[GlossaryEntry]
