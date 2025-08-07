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
        
        // Render the table structure with headers
        this.renderTableStructure();
        
        // Render loading skeleton
        this.renderLoadingSkeleton();
    }
    
    renderTableStructure() {
        const tableContainer = document.getElementById('tableContainer');
        if (!tableContainer) return;
        
        // Create the table with headers
        tableContainer.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th style="width: 80px;">♥/✕</th>
                        <th class="sortable" onclick="sortTable('price')">
                            <div class="column-header">
                                Price
                                <span class="sort-arrows" id="sort-price">▲▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('price_per_sqm')">
                            <div class="column-header">
                                Price/m²
                                <span class="sort-arrows" id="sort-price_per_sqm">▲▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('total_monthly_costs')">
                            <div class="column-header">
                                Monthly Cost
                                <span class="sort-arrows" id="sort-total_monthly_costs">▲▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('ward')">
                            <div class="column-header">
                                Ward
                                <span class="sort-arrows" id="sort-ward">▲▼</span>
                                <div class="filter-dropdown">
                                    <button class="filter-btn" onclick="toggleFilterDropdown(event, 'ward')" id="filter-btn-ward">▼</button>
                                    <div class="filter-dropdown-content" id="filter-dropdown-ward">
                                        <div id="ward-filter-options"></div>
                                        <div class="filter-actions">
                                            <button onclick="applyColumnFilter('ward')">Apply</button>
                                            <button onclick="clearColumnFilter('ward')">Clear</button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('ward_discount_pct')">
                            <div class="column-header">
                                Ward Discount %
                                <span class="sort-arrows" id="sort-ward_discount_pct">▲▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('ward_median_price_per_sqm')">
                            <div class="column-header">
                                Ward Median ¥/m²
                                <span class="sort-arrows" id="sort-ward_median_price_per_sqm">▲▼</span>
                            </div>
                        </th>
                        <th>Closest Station</th>
                        <th class="sortable" onclick="sortTable('station_distance_minutes')">
                            <div class="column-header">
                                Walk Time (min)
                                <span class="sort-arrows" id="sort-station_distance_minutes">▲▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('floor')">
                            <div class="column-header">
                                Floor
                                <span class="sort-arrows" id="sort-floor">▲▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('building_age_years')">
                            <div class="column-header">
                                Building Age
                                <span class="sort-arrows" id="sort-building_age_years">▲▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('size_sqm')">
                            <div class="column-header">
                                Size (m²)
                                <span class="sort-arrows" id="sort-size_sqm">▲▼</span>
                            </div>
                        </th>
                        <th>
                            <div class="column-header">
                                Primary Light
                                <div class="filter-dropdown">
                                    <button class="filter-btn" onclick="toggleFilterDropdown(event, 'primary_light')" id="filter-btn-primary_light">▼</button>
                                    <div class="filter-dropdown-content" id="filter-dropdown-primary_light">
                                        <div id="primary_light-filter-options"></div>
                                        <div class="filter-actions">
                                            <button onclick="applyColumnFilter('primary_light')">Apply</button>
                                            <button onclick="clearColumnFilter('primary_light')">Clear</button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </th>
                        <th>
                            <div class="column-header">
                                Verdict
                                <div class="filter-dropdown">
                                    <button class="filter-btn" onclick="toggleFilterDropdown(event, 'verdict')" id="filter-btn-verdict">▼</button>
                                    <div class="filter-dropdown-content" id="filter-dropdown-verdict">
                                        <div id="verdict-filter-options"></div>
                                        <div class="filter-actions">
                                            <button onclick="applyColumnFilter('verdict')">Apply</button>
                                            <button onclick="clearColumnFilter('verdict')">Clear</button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </th>
                    </tr>
                </thead>
                <tbody id="propertiesTable">
                    <!-- Table rows will be populated here -->
                </tbody>
            </table>
        `;
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
            const filterText = appState.hasActiveFilters() ? ' (filtered)' : '';
            resultsCount.innerHTML = `
                Showing ${start.toLocaleString()}-${end.toLocaleString()} of ${total.toLocaleString()} properties${filterText}
                ${appState.isBackgroundLoading ? '<span style="color: #999;"> (loading more...)</span>' : ''}
            `;
        }
    }
    
    renderLoadingSkeleton() {
        const loadingDiv = document.getElementById('loading');
        if (!loadingDiv) return;
        
        loadingDiv.innerHTML = `
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
        `;
    }
}