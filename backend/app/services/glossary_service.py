import json
import os
from typing import List, Optional

from app.schemas.glossary import GlossaryEntry, GlossaryResponse

# glossary.json 的路徑
GLOSSARY_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'glossary.json'
)


class GlossaryService:
    """名詞解釋字典服務"""

    @staticmethod
    def _load_glossary() -> dict:
        """讀取 glossary.json"""
        abs_path = os.path.abspath(GLOSSARY_PATH)
        with open(abs_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def get_all_entries() -> GlossaryResponse:
        """取得所有名詞解釋"""
        data = GlossaryService._load_glossary()
        entries = [GlossaryEntry(**entry) for entry in data['entries']]
        return GlossaryResponse(
            version=data['version'],
            last_updated=data['last_updated'],
            entries=entries
        )

    @staticmethod
    def get_entry_by_id(entry_id: str) -> Optional[GlossaryEntry]:
        """根據 ID 取得單一名詞解釋"""
        data = GlossaryService._load_glossary()
        for entry in data['entries']:
            if entry['id'] == entry_id:
                return GlossaryEntry(**entry)
        return None

    @staticmethod
    def search_entries(keyword: str) -> List[GlossaryEntry]:
        """搜尋名詞（比對 term、content、tags）"""
        data = GlossaryService._load_glossary()
        results = []
        keyword_lower = keyword.lower()
        for entry in data['entries']:
            if (keyword_lower in entry['term'].lower() or
                keyword_lower in entry['content'].lower() or
                any(keyword_lower in tag.lower() for tag in entry['tags'])):
                results.append(GlossaryEntry(**entry))
        return results

    @staticmethod
    def get_entries_by_category(category: str) -> List[GlossaryEntry]:
        """根據類別過濾名詞"""
        data = GlossaryService._load_glossary()
        return [
            GlossaryEntry(**entry)
            for entry in data['entries']
            if entry['category'] == category
        ]
