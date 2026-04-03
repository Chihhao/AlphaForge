/**
 * 格式化股價
 * 1. 不需要 NT$ (由外部決定不加)
 * 2. 當股價 > 999 時，不顯示小數點
 * 3. 當股價 <= 999 時，預設顯示兩位小數
 */
/** 返回「下一個操作日」的 M/D 標籤，跳過週末。
 *  實際是否為交易日由後端資料決定，前端只做基本的週末跳過。 */
export const todayLabel = (): string => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    for (let i = 0; i < 10; i++) {
        const day = d.getDay();
        if (day !== 0 && day !== 6) {
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
