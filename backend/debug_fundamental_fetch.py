import requests
import pandas as pd
import json
from datetime import datetime

def fetch_twse_bwibbu_all(date_str=None):
    """
    抓取證交所個股日本益比、殖利率及個股價淨值比 (全市場)
    URL: https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={date}&selectType=ALL&response=json
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')
    
    print(f"正在抓取 TWSE 全市場個股基本面數據 (日期: {date_str})...")
    
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={date_str}&selectType=ALL&response=json"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://www.twse.com.tw/zh/page/trading/indices/bwibbu-day.html'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"HTTP 錯誤: {response.status_code}")
            return None
            
        data = response.json()
        if data.get('stat') != 'OK':
            print(f"數據狀態不符: {data.get('stat', '未知錯誤')}")
            return None
            
        # 欄位說明 (實際觀察所得): 
        # 0:證券代號, 1:證券名稱, 2:收盤價, 3:殖利率(%), 4:股利年度, 5:本益比, 6:股價淨值比, 7:財報年/季
        fields = data.get('fields', [])
        rows = data.get('data', [])
        
        # 建立 DataFrame
        df = pd.DataFrame(rows, columns=fields)
        
        # 轉換數值
        def clean_val(val):
            if val == '-' or val == 'N/A' or val == '': return 0.0
            try:
                return float(str(val).replace(',', ''))
            except:
                return 0.0

        # 正確對應欄位
        df['Price'] = df.iloc[:, 2].apply(clean_val)
        df['Yield'] = df.iloc[:, 3].apply(clean_val)
        df['PE'] = df.iloc[:, 5].apply(clean_val)
        df['PB'] = df.iloc[:, 6].apply(clean_val)
        
        return df
        
    except Exception as e:
        print(f"請求發生錯誤: {e}")
        return None

def test_fundamental_fetch():
    # 測試 2024-03-21 (已知數據) 或 2026-03-06 (最近交易日)
    for target_date in ["20260306", "20240321"]:
        df = fetch_twse_bwibbu_all(target_date)
        
        if df is not None:
            print(f"\n--- 成功抓取全市場基本面快照 ({target_date}) ---")
            print(f"總筆數: {len(df)}")
            
            # 測試條件: 殖利率 > 5%, P/B < 3
            filtered = df[(df['Yield'] > 5) & (df['PB'] < 3) & (df['PB'] > 0)]
            
            print(f"符合「殖利率 > 5% 且 P/B < 3」的檔數: {len(filtered)}")
            print("\n前 5 檔符合標的:")
            print(filtered.iloc[:, [0, 1, 3, 5]].head(5))
            
            # 檢查特定標的
            target_ids = ['1535', '1615', '1777']
            specific = df[df.iloc[:, 0].isin(target_ids)]
            if not specific.empty:
                print("\n--- 檢查特定標的 ---")
                print(specific.iloc[:, [0, 1, 3, 5]])
            break
        else:
            print(f"{target_date} 數據獲取失敗，嘗試下一個日期...")

if __name__ == "__main__":
    test_fundamental_fetch()
