/**
 * formatters.js
 * Utility functions for formatting prices, percentages, dates, and other display values
 */

function formatPrice(price, suffix = '', multiplyBy10k = false) {
    if (!price && price !== 0) return '<span class="no-data">—</span>';
    // Only multiply by 10,000 for main price column (prices stored in 万円)
    const actualPrice = multiplyBy10k ? price * 10000 : price;
    return '¥' + Math.round(actualPrice).toLocaleString() + suffix;
}

function formatPercent(percent) {
    if (percent === undefined || percent === null) return '<span class="no-data">—</span>';
    const formatted = percent.toFixed(1);
    return formatted > 0 ? `+${formatted}%` : `${formatted}%`;
}

function formatDate(dateString) {
    if (!dateString) return '<span class="no-data">—</span>';
    const date = new Date(dateString);
    return date.toLocaleDateString('ja-JP');
}

function formatAge(age) {
    if (age === undefined || age === null) return '<span class="no-data">—</span>';
    return `${age}年`;
}

function formatSize(size) {
    if (!size) return '<span class="no-data">—</span>';
    return `${size}m²`;
}

function formatStation(station) {
    if (!station || station === 'Unknown') return '<span class="no-data">—</span>';
    return station;
}