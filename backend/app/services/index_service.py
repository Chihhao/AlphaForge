import requests
import json
from typing import List
from app.services.system_logger import SystemLogger

class IndexService:
    """指數成分股服務"""
    
    # 元大投信 0050 成分股 API
    # 這是公開的 JSON 接口，包含成分股代號、名稱、權重等資訊
    YUANTA_0050_URL = "https://www.yuantaetfs.com/api/StkData?FundId=1066"

    @staticmethod
    def get_0050_constituents() -> List[str]:
        """
        從元大投信官網獲取最新的 0050 成分股代號清單
        """
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
            response = requests.get(IndexService.YUANTA_0050_URL, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            # 結構通常是 [{"stk_code": "2330", "stk_name": "台積電", ...}, ...]
            if isinstance(data, list) and len(data) > 0:
                constituents = [item["stk_code"].strip() for item in data if "stk_code" in item]
                if len(constituents) >= 40: # 基本檢查確保抓到的是完整的
                    SystemLogger.info(f"成功自動獲取 0050 成分股清單 (共 {len(constituents)} 檔)", category="index")
                    return constituents
            
            SystemLogger.warning("無法從元大 API 獲取有效的 0050 清單，將回退到硬編碼清單", category="index")
        except Exception as e:
            SystemLogger.error(f"獲取 0050 成分股失敗: {str(e)}", category="index")
        
        # 回退清單 (目前的 0050 主要權值股)
        return [
            "2330", "2454", "2317", "2308", "2382", "2881", "2882", "3711", "2412", "2303",
            "2886", "2891", "2884", "3231", "1216", "2885", "2002", "3034", "3037", "2357",
            "2603", "2892", "2880", "5871", "3008", "2890", "2301", "2207", "3045", "6505",
            "2618", "4938", "2408", "3661", "2327", "2883", "1303", "2609", "1301", "2887",
            "2409", "2912", "9910", "1326", "2801", "1590", "1101", "3481", "1605", "2379"
        ]
