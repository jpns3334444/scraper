/**
 * PropertiesView.js
 * Properties table with properly aligned headers for Sumi-e design
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

        // Create the table with properly aligned headers
        tableContainer.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th>
                            <div class="column-header">
                                ♥/✕
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('price')">
                            <div class="column-header">
                                Price
                                <span class="sort-arrows" id="sort-price">▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('price_per_sqm')">
                            <div class="column-header">
                                Price/m²
                                <span class="sort-arrows" id="sort-price_per_sqm">▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('total_monthly_costs')">
                            <div class="column-header">
                                Monthly
                                <span class="sort-arrows" id="sort-total_monthly_costs">▼</span>
                            </div>
                        </th>
                        <th onclick="sortTable('ward')">
                            <div class="column-header">
                                Ward
                                <span class="sort-arrows" id="sort-ward">▼</span>
                                <div class="filter-dropdown">
                                    <button class="filter-btn" onclick="toggleFilterDropdown(event, 'ward')" id="filter-btn-ward">▿</button>
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
                                Disc %
                                <span class="sort-arrows" id="sort-ward_discount_pct">▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('ward_median_price_per_sqm')">
                            <div class="column-header">
                                Median
                                <span class="sort-arrows" id="sort-ward_median_price_per_sqm">▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('station_distance_minutes')">
                            <div class="column-header">
                                Walk
                                <span class="sort-arrows" id="sort-station_distance_minutes">▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('floor')">
                            <div class="column-header">
                                Floor
                                <span class="sort-arrows" id="sort-floor">▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('year_built')">
                            <div class="column-header">
                                Year Built
                                <span class="sort-arrows" id="sort-year_built">▼</span>
                            </div>
                        </th>
                        <th class="sortable" onclick="sortTable('size_sqm')">
                            <div class="column-header">
                                m²
                                <span class="sort-arrows" id="sort-size_sqm">▼</span>
                            </div>
                        </th>
                        <th>
                            <div class="column-header">
                                Light
                                <div class="filter-dropdown">
                                    <button class="filter-btn" onclick="toggleFilterDropdown(event, 'primary_light')" id="filter-btn-primary_light">▿</button>
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
                                    <button class="filter-btn" onclick="toggleFilterDropdown(event, 'verdict')" id="filter-btn-verdict">▿</button>
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
        const yearBuilt = property.building_age_years !== undefined 
            ? `${new Date().getFullYear() - property.building_age_years}`
            : '<span class="no-data">—</span>';
        const size = property.size_sqm || property.total_sqm 
            ? `${Math.round(property.size_sqm || property.total_sqm)}`
            : '<span class="no-data">—</span>';
        const primaryLight = property.primary_light || '<span class="no-data">—</span>';
        const verdict = property.verdict || property.recommendation || 'pass';
        const hasLink = property.listing_url && property.listing_url.trim();
        const isFavorited = appState.favorites.has(property.property_id);
        
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
                <td class="numeric">${walkTime}</td>
                <td class="numeric">${floor}</td>
                <td class="numeric">${yearBuilt}</td>
                <td class="numeric">${size}</td>
                <td>${primaryLight}</td>
                <td>
                    <span class="verdict verdict-${verdict.toLowerCase().replace('_', '-')}">${verdict.toUpperCase()}</span>
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
                ${appState.isBackgroundLoading ? '<span style="color: var(--ink-light); font-size: 12px;"> ・ loading...</span>' : ''}
            `;
        }
    }
    
    renderLoadingSkeleton() {
        const loadingDiv = document.getElementById('loading');
        if (!loadingDiv) return;
        
        loadingDiv.innerHTML = `
            ${Array(8).fill().map(() => `
                <div class="skeleton-row">
                    <div class="skeleton-cell" style="width: 60px;"></div>
                    <div class="skeleton-cell" style="width: 85px;"></div>
                    <div class="skeleton-cell" style="width: 75px;"></div>
                    <div class="skeleton-cell" style="width: 75px;"></div>
                    <div class="skeleton-cell" style="width: 90px;"></div>
                    <div class="skeleton-cell" style="width: 60px;"></div>
                    <div class="skeleton-cell" style="width: 75px;"></div>
                    <div class="skeleton-cell" style="width: 50px;"></div>
                    <div class="skeleton-cell" style="width: 45px;"></div>
                    <div class="skeleton-cell" style="width: 70px;"></div>
                    <div class="skeleton-cell" style="width: 45px;"></div>
                    <div class="skeleton-cell" style="width: 60px;"></div>
                    <div class="skeleton-cell" style="width: 85px;"></div>
                </div>
            `).join('')}
        `;
    }
}