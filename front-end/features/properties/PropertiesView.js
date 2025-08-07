/**
 * PropertiesView.js
 * Handles rendering of the properties table and related UI elements
 */

class PropertiesView {
    constructor() {
        this.tableContainer = null;
        this.resultsContainer = null;
    }
    
    init() {
        this.tableContainer = document.getElementById('propertiesTable');
        this.resultsContainer = document.getElementById('resultsCount');
    }
    
    renderTable(properties, currentPage, itemsPerPage) {
        const tbody = document.getElementById('propertiesTable');
        if (!tbody) return;
        
        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const pageItems = properties.slice(start, end);
        
        tbody.innerHTML = pageItems.map(property => this.renderRow(property)).join('');
    }
    
    renderRow(property) {
        const price = formatPrice(property.price, '', true);
        const pricePerSqm = formatPrice(property.price_per_sqm);
        const monthyCost = formatPrice(property.total_monthly_costs);
        const ward = property.ward || '<span class="no-data">—</span>';
        const wardDiscount = formatPercent(property.ward_discount_pct);
        const wardMedian = formatPrice(property.ward_median_price_per_sqm);
        const closestStation = property.closest_station || '<span class="no-data">—</span>';
        const walkTime = property.station_distance_minutes 
            ? `${property.station_distance_minutes}`
            : '<span class="no-data">—</span>';
        const floor = property.floor || '<span class="no-data">—</span>';
        const buildingAge = property.building_age_years !== undefined 
            ? `${property.building_age_years} years`
            : '<span class="no-data">—</span>';
        const size = property.size_sqm || property.total_sqm 
            ? `${Math.round(property.size_sqm || property.total_sqm)}`
            : '<span class="no-data">—</span>';
        const primaryLight = property.primary_light || '<span class="no-data">—</span>';
        const verdict = property.verdict || property.recommendation || 'pass';
        const hasLink = property.listing_url && property.listing_url.trim();
        const isFavorited = appState.favorites.has(property.property_id);
        const isHidden = appState.hidden.has(property.property_id);
        
        return `
            <tr ${hasLink ? `onclick="openListing(event, '${property.listing_url}')"` : 'class="no-link"'} data-property-id="${property.property_id}">
                <td style="text-align: center; white-space: nowrap;">
                    <button class="heart-btn ${isFavorited ? 'favorited' : ''}" 
                            onclick="window.app.favorites.toggleFavorite('${property.property_id}', this)"
                            data-property-id="${property.property_id}">
                        ${isFavorited ? '♥' : '♡'}
                    </button>
                    <button class="hide-btn" 
                            onclick="toggleHidden('${property.property_id}', this)"
                            data-property-id="${property.property_id}">
                        ✕
                    </button>
                </td>
                <td class="price">${price}</td>
                <td class="price">${pricePerSqm}</td>
                <td class="price">${monthyCost}</td>
                <td>${ward}</td>
                <td class="percent">${wardDiscount}</td>
                <td class="price">${wardMedian}</td>
                <td>${closestStation}</td>
                <td class="numeric">${walkTime}</td>
                <td class="numeric">${floor}</td>
                <td class="age">${buildingAge}</td>
                <td class="numeric">${size}</td>
                <td>${primaryLight}</td>
                <td>
                    <span class="verdict verdict-${verdict}">${verdict.toUpperCase()}</span>
                </td>
            </tr>
        `;
    }
    
    updateResultsInfo(start, end, total) {
        const resultsCount = document.getElementById('resultsCount');
        if (resultsCount) {
            resultsCount.innerHTML = `
                Showing ${start.toLocaleString()} - ${end.toLocaleString()} of ${total.toLocaleString()} properties
                ${appState.isBackgroundLoading ? '<span style="color: #999;"> (loading more...)</span>' : ''}
            `;
        }
    }
    
    renderTableHeader() {
        return `
            <thead>
                <tr>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('is_favorited')">
                            <span>⭐</span>
                            <span class="sort-arrows">▲▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('price')">
                            <span>Price</span>
                            <span class="sort-arrows active">▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('price_per_sqm')">
                            <span>¥/m²</span>
                            <span class="sort-arrows">▲▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('total_monthly_costs')">
                            <span>Monthly</span>
                            <span class="sort-arrows">▲▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('ward')">
                            <span>Ward</span>
                            <span class="sort-arrows">▲▼</span>
                            <div class="filter-dropdown-container">
                                <button class="filter-btn" onclick="toggleFilterDropdown(event, 'ward')">▼</button>
                                <div class="filter-dropdown" id="wardFilter"></div>
                            </div>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('ward_discount_pct')">
                            <span>Ward %</span>
                            <span class="sort-arrows">▲▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('ward_median_price_per_sqm')">
                            <span>Ward Med.</span>
                            <span class="sort-arrows">▲▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('closest_station')">
                            <span>Station</span>
                            <span class="sort-arrows">▲▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('station_distance_minutes')">
                            <span>Walk</span>
                            <span class="sort-arrows">▲▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('floor')">
                            <span>Floor</span>
                            <span class="sort-arrows">▲▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('building_age_years')">
                            <span>Age</span>
                            <span class="sort-arrows">▲▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('size_sqm')">
                            <span>Size</span>
                            <span class="sort-arrows">▲▼</span>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('primary_light')">
                            <span>Light</span>
                            <span class="sort-arrows">▲▼</span>
                            <div class="filter-dropdown-container">
                                <button class="filter-btn" onclick="toggleFilterDropdown(event, 'primary_light')">▼</button>
                                <div class="filter-dropdown" id="primary_lightFilter"></div>
                            </div>
                        </div>
                    </th>
                    <th class="sortable">
                        <div class="column-header" onclick="sortTable('verdict')">
                            <span>Verdict</span>
                            <span class="sort-arrows">▲▼</span>
                            <div class="filter-dropdown-container">
                                <button class="filter-btn" onclick="toggleFilterDropdown(event, 'verdict')">▼</button>
                                <div class="filter-dropdown" id="verdictFilter"></div>
                            </div>
                        </div>
                    </th>
                </tr>
            </thead>
        `;
    }
    
    renderLoadingSkeleton() {
        return `
            <div class="loading" id="loading">
                <div class="skeleton-row">
                    <div class="skeleton-cell numeric skeleton" style="width: 40px;"></div>
                    <div class="skeleton-cell price skeleton"></div>
                    <div class="skeleton-cell price skeleton"></div>
                    <div class="skeleton-cell price skeleton"></div>
                    <div class="skeleton-cell ward skeleton"></div>
                    <div class="skeleton-cell percent skeleton"></div>
                    <div class="skeleton-cell price skeleton"></div>
                    <div class="skeleton-cell station skeleton"></div>
                    <div class="skeleton-cell numeric skeleton"></div>
                    <div class="skeleton-cell numeric skeleton"></div>
                    <div class="skeleton-cell age skeleton"></div>
                    <div class="skeleton-cell numeric skeleton"></div>
                    <div class="skeleton-cell light skeleton"></div>
                    <div class="skeleton-cell verdict skeleton"></div>
                </div>
                ${Array(5).fill().map(() => `
                    <div class="skeleton-row">
                        <div class="skeleton-cell numeric skeleton" style="width: 40px;"></div>
                        <div class="skeleton-cell price skeleton"></div>
                        <div class="skeleton-cell price skeleton"></div>
                        <div class="skeleton-cell price skeleton"></div>
                        <div class="skeleton-cell ward skeleton"></div>
                        <div class="skeleton-cell percent skeleton"></div>
                        <div class="skeleton-cell price skeleton"></div>
                        <div class="skeleton-cell station skeleton"></div>
                        <div class="skeleton-cell numeric skeleton"></div>
                        <div class="skeleton-cell numeric skeleton"></div>
                        <div class="skeleton-cell age skeleton"></div>
                        <div class="skeleton-cell numeric skeleton"></div>
                        <div class="skeleton-cell light skeleton"></div>
                        <div class="skeleton-cell verdict skeleton"></div>
                    </div>
                `).join('')}
            </div>
        `;
    }
}