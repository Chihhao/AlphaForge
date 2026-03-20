import requests
import json
import logging
from typing import List, Optional
from datetime import date
from app.services.system_logger import SystemLogger

logger = logging.getLogger(__name__)

class IndexService:
    """指數成分股服務"""
    
    # 元大投信 0050 成分股 API
    # 這是公開的 JSON 接口，包含成分股代號、名稱、權重等資訊
    YUANTA_0050_URL = "https://www.yuantaetfs.com/api/StkData?FundId=1066"

    # 指數資料快取 (含日期校驗)
    _cache_0050: Optional[List[str]] = None
    _cache_date: Optional[date] = None

    @staticmethod
    def get_0050_constituents() -> List[str]:
        """
        從元大投信官網獲取最新的 0050 成分股代號清單 (具備 24 小時效期快取)
        """
        today = date.today()

        # 如果今日已經獲取過 (無論是成功還是回退)，直接回傳
        if IndexService._cache_0050 and IndexService._cache_date == today:
            return IndexService._cache_0050

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*"
            }
            # 增加權威性 Headers 以減少被擋機率
            response = requests.get(IndexService.YUANTA_0050_URL, headers=headers, timeout=5)
            
            if response.status_code == 200 and response.text.strip():
                try:
                    data = response.json()
                    # 結構通常是 [{"stk_code": "2330", "stk_name": "台積電", ...}, ...]
                    if isinstance(data, list) and len(data) > 0:
                        constituents = [item["stk_code"].strip() for item in data if "stk_code" in item]
                        if len(constituents) >= 40:
                            SystemLogger.info(f"成功自動獲取 0050 成分股清單 (共 {len(constituents)} 檔)", category="index")
                            IndexService._cache_0050 = constituents
                            IndexService._cache_date = today
                            return constituents
                except json.JSONDecodeError:
                    # 如果不是 JSON，可能是被導向到錯誤頁面或空本文
                    logger.debug("0050 名單更新延後，使用預設名單")
            else:
                SystemLogger.warning("0050 名單更新延後，系統將繼續使用預設名單", category="index")
        
        except Exception:
            logger.debug("0050 名單更新延後，使用預設名單")
        
        # 硬編碼回退清單 (確保系統始終能運作)
        fallback = [
            "2330", "2454", "2317", "2308", "2382", "2881", "2882", "3711", "2412", "2303",
            "2886", "2891", "2884", "3231", "1216", "2885", "2002", "3034", "3037", "2357",
            "2603", "2892", "2880", "5871", "3008", "2890", "2301", "2207", "3045", "6505",
            "2618", "4938", "2408", "3661", "2327", "2883", "1303", "2609", "1301", "2887",
            "2409", "2912", "9910", "1326", "2801", "1590", "1101", "3481", "1605", "2379"
        ]
        IndexService._cache_0050 = fallback
        IndexService._cache_date = today
        return fallback
