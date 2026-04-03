/**
 * 格式化股價
 * 1. 不需要 NT$ (由外部決定不加)
 * 2. 當股價 > 999 時，不顯示小數點
 * 3. 當股價 <= 999 時，預設顯示兩位小數
 */
/** 返回下一個交易日的 M/D 格式，跳過週六日和台灣國定假日 */
export const todayLabel = (): string => {
    return nextTradingDayLabel();
};

/** 返回下一個交易日的 M/D，跳過週末和已知國定假日 */
export const nextTradingDayLabel = (): string => {
    const d = new Date();
    // 台灣國定假日（MM-DD 格式，每年需更新）
    const holidays2026 = [
        '01-01', '01-26', '01-27', '01-28', '01-29', '01-30',  // 元旦、春節
        '02-27',                                                  // 228 補假
        '04-03', '04-04',                                         // 清明+兒童節
        '04-07',                                                  // 清明補假
        '05-01',                                                  // 勞動節
        '05-31',                                                  // 端午
        '10-06',                                                  // 中秋
        '10-10',                                                  // 國慶
    ];
    const isHoliday = (date: Date) => {
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        return holidays2026.includes(`${mm}-${dd}`);
    };
    // 從明天開始找下一個交易日
    d.setDate(d.getDate() + 1);
    for (let i = 0; i < 10; i++) {
        const day = d.getDay();
        if (day !== 0 && day !== 6 && !isHoliday(d)) {
            return `${d.getMonth() + 1}/${d.getDate()}`;
        }
        d.setDate(d.getDate() + 1);
    }
    return `${d.getMonth() + 1}/${d.getDate()}`;
};

/** 返回 M/D 格式的明日日期，如 "3/30" */
export const tomorrowLabel = (): string => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return `${d.getMonth() + 1}/${d.getDate()}`;
};

export const formatPrice = (price: number | undefined | null): string => {
    if (price === undefined || price === null || isNaN(price)) return '---';

    if (price >= 1000) {
        return Math.round(price).toLocaleString(undefined, { maximumFractionDigits: 0 });
    } else if (price >= 100) {
        return price.toFixed(1);
    }

    return price.toFixed(2);
};
