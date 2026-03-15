from pydantic import BaseModel
from typing import List, Optional


class FactorWeight(BaseModel):
    factor: str
    factor_label: str
    coefficient: float
    direction: str          # "bullish" | "bearish"


class EquityCurvePoint(BaseModel):
    date: str
    cumulative_return: float


class RecentAlphaSignal(BaseModel):
    stock_id: str
    stock_name: str
    signal_date: str
    predicted_prob: float
    trigger_factors: List[str]


class StrategyRanking(BaseModel):
    strategy_id: str
    strategy_name: str
    factors: List[str]
    time_dimension: str = "10d"         # "5d" | "10d" | "30d"
    threshold_low: float = 0.03         # 低門檻（訓練 label 用）
    threshold_high: float = 0.05        # 高門檻（報告用）
    win_rate_insample: float
    win_rate_outsample: float           # Top20% 中 > threshold_low 的比例
    win_rate_outsample_hi: float = 0.0  # Top20% 中 > threshold_high 的比例
    loss_rate_outsample: float = 0.0    # Top20% 中 < -threshold_low 的比例
    loss_rate_outsample_hi: float = 0.0 # Top20% 中 < -threshold_high 的比例
    odds_ratio: float = 1.0             # win_rate_lo / loss_rate_lo
    odds_ratio_hi: float = 1.0          # win_rate_hi / loss_rate_hi
    market_win_rate: float = 0.0        # 全市場基準：> threshold_low
    market_win_rate_hi: float = 0.0     # 全市場基準：> threshold_high
    market_loss_rate: float = 0.0       # 全市場基準：< -threshold_low
    market_loss_rate_hi: float = 0.0    # 全市場基準：< -threshold_high
    ic: float                   # Spearman IC（測試集）
    p_value: float
    p_value_corrected: float    # Bonferroni 校正後
    is_significant: bool
    overfit_warning: bool       # |insample - outsample| > 5%
    sample_count_train: int
    sample_count_test: int      # 測試集 Top 20% 訊號數
    integrity_flags: List[str]  # 誠信警示訊息


class StrategyDetail(StrategyRanking):
    equity_curve: List[EquityCurvePoint]
    recent_signals: List[RecentAlphaSignal]
    factor_weights: List[FactorWeight]


class TodaySignal(BaseModel):
    stock_id: str
    stock_name: str
    trigger_count: int          # 幾個顯著策略同時看好
    strategies: List[str]       # 觸發的策略名稱列表
    signal_date: str
    # IC 加權統計
    time_dimension: str = "10d"
    threshold_low: float = 0.03
    threshold_high: float = 0.05
    weighted_odds_ratio: float = 1.0
    weighted_odds_ratio_hi: float = 1.0
    weighted_win_rate: float = 0.0
    weighted_win_rate_hi: float = 0.0
    weighted_loss_rate: float = 0.0
    weighted_loss_rate_hi: float = 0.0
    weighted_market_win_rate: float = 0.0
    weighted_market_win_rate_hi: float = 0.0
    weighted_market_loss_rate: float = 0.0
    weighted_market_loss_rate_hi: float = 0.0


class AlphaMinerResult(BaseModel):
    strategies: List[StrategyRanking]
    last_trained: str
    train_period: str
    test_period: str
    total_combinations_tested: int
    bonferroni_threshold: float
    is_training: bool = False   # 訓練進行中，前端應輪詢
