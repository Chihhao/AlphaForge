from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.services.glossary_service import GlossaryService
from app.schemas.glossary import GlossaryEntry, GlossaryResponse

router = APIRouter(prefix="/glossary", tags=["glossary"])


@router.get("/", response_model=GlossaryResponse)
def get_all_glossary():
    """取得所有名詞解釋"""
    return GlossaryService.get_all_entries()


@router.get("/search", response_model=List[GlossaryEntry])
def search_glossary(q: str = Query(..., description="搜尋關鍵字")):
    """搜尋名詞解釋"""
    results = GlossaryService.search_entries(q)
    return results


@router.get("/category/{category}", response_model=List[GlossaryEntry])
def get_by_category(category: str):
    """根據類別取得名詞"""
    return GlossaryService.get_entries_by_category(category)


@router.get("/{entry_id}", response_model=GlossaryEntry)
def get_glossary_entry(entry_id: str):
    """根據 ID 取得單一名詞解釋"""
    entry = GlossaryService.get_entry_by_id(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"找不到名詞：{entry_id}")
    return entry
