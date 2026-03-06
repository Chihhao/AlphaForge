/**
 * 格式化股價
 * 1. 不需要 NT$ (由外部決定不加)
 * 2. 當股價 > 999 時，不顯示小數點
 * 3. 當股價 <= 999 時，預設顯示兩位小數
 */
export const formatPrice = (price: number | undefined | null): string => {
    if (price === undefined || price === null || isNaN(price)) return '---';

    if (price >= 1000) {
        return Math.round(price).toLocaleString(undefined, { maximumFractionDigits: 0 });
    } else if (price >= 100) {
        return price.toFixed(1);
    }

    return price.toFixed(2);
};
