/**
 * PropertiesView.js
 * Simple, clean properties table view with proper alignment
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
        const tableContainer = document.getElementById('propertiesTable');
        if (!tableContainer) return;

        // Create simple, clean table structure with proper headers
        tableContainer.innerHTML = `
            <thead>
                <tr>
                    <th style="width: 80px;">
                        <div class="column-header">Actions</div>
                    </th>
                    <th class="sortable" onclick="sortTable('price')" style="text-align: right;">
                        <div class="column-header">
                            Price
                            <span class="sort-arrows" id="sort-price">▼</span>
                        </div>
                    </th>
                    <th class="sortable" onclick="sortTable('price_per_sqm')" style="text-align: right;">
                        <div class="column-header">
                            ¥/m²
                            <span class="sort-arrows" id="sort-price_per_sqm">▼</span>
                        </div>
                    </th>
                    <th class="sortable" onclick="sortTable('total_monthly_costs')" style="text-align: right;">
                        <div class="column-header">
                            Monthly
                            <span class="sort-arrows" id="sort-total_monthly_costs">▼</span>
                        </div>
                    </th>
                    <th>
                        <div class="column-header">
                            <span onclick="sortTable('ward')" style="cursor: pointer; flex: 1;">
                                Ward
                                <span class="sort-arrows" id="sort-ward">▼</span>
                            </span>
                            <div class="filter-dropdown" onclick="event.stopPropagation();">
                                <button class="filter-btn" onclick="toggleFilterDropdown(event, 'ward')" id="filter-btn-ward">▿</button>
                                <div class="filter-dropdown-content" id="wardFilter" onclick="event.stopPropagation();">
                                    <div class="filter-select-actions">
                                        <button onclick="event.stopPropagation(); selectAllColumnFilter('ward')">Select All</button>
                                        <button onclick="event.stopPropagation(); deselectAllColumnFilter('ward')">Deselect All</button>
                                    </div>
                                    <div id="ward-filter-options"></div>
                                    <div class="filter-actions">
                                        <button onclick="event.stopPropagation(); applyColumnFilter('ward')">Apply</button>
                                        <button onclick="event.stopPropagation(); clearColumnFilter('ward')">Clear</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </th>
                    <th class="sortable" onclick="sortTable('ward_discount_pct')" style="text-align: center;">
                        <div class="column-header">
                            Disc %
                            <span class="sort-arrows" id="sort-ward_discount_pct">▼</span>
                        </div>
                    </th>
                    <th class="sortable" onclick="sortTable('ward_median_price_per_sqm')" style="text-align: right;">
                        <div class="column-header">
                            Ward Med
                            <span class="sort-arrows" id="sort-ward_median_price_per_sqm">▼</span>
                        </div>
                    </th>
                    <th class="sortable" onclick="sortTable('station_distance_minutes')" style="text-align: center;">
                        <div class="column-header">
                            Walk
                            <span class="sort-arrows" id="sort-station_distance_minutes">▼</span>
                        </div>
                    </th>
                    <th class="sortable" style="text-align: center;">
                        <div class="column-header">
                            <span onclick="sortTable('floor')" style="cursor: pointer; flex: 1;">
                                Floor
                                <span class="sort-arrows" id="sort-floor">▼</span>
                            </span>
                            <div class="filter-dropdown" onclick="event.stopPropagation();">
                                <button class="filter-btn" onclick="toggleFilterDropdown(event, 'floor')" id="filter-btn-floor">▿</button>
                                <div class="filter-dropdown-content" id="floorFilter" onclick="event.stopPropagation();">
                                    <div class="filter-select-actions">
                                        <button onclick="event.stopPropagation(); selectAllColumnFilter('floor')">Select All</button>
                                        <button onclick="event.stopPropagation(); deselectAllColumnFilter('floor')">Deselect All</button>
                                    </div>
                                    <div id="floor-filter-options"></div>
                                    <div class="filter-actions">
                                        <button onclick="event.stopPropagation(); applyColumnFilter('floor')">Apply</button>
                                        <button onclick="event.stopPropagation(); clearColumnFilter('floor')">Clear</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </th>
                    <th class="sortable" onclick="sortTable('year_built')" style="text-align: center;">
                        <div class="column-header">
                            Year
                            <span class="sort-arrows" id="sort-year_built">▼</span>
                        </div>
                    </th>
                    <th class="sortable" onclick="sortTable('size_sqm')" style="text-align: center;">
                        <div class="column-header">
                            m²
                            <span class="sort-arrows" id="sort-size_sqm">▼</span>
                        </div>
                    </th>
                    <th>
                        <div class="column-header">
                            Light
                            <div class="filter-dropdown" onclick="event.stopPropagation();">
                                <button class="filter-btn" onclick="toggleFilterDropdown(event, 'primary_light')" id="filter-btn-primary_light">▿</button>
                                <div class="filter-dropdown-content" id="primary_lightFilter" onclick="event.stopPropagation();">
                                    <div class="filter-select-actions">
                                        <button onclick="event.stopPropagation(); selectAllColumnFilter('primary_light')">Select All</button>
                                        <button onclick="event.stopPropagation(); deselectAllColumnFilter('primary_light')">Deselect All</button>
                                    </div>
                                    <div id="primary_light-filter-options"></div>
                                    <div class="filter-actions">
                                        <button onclick="event.stopPropagation(); applyColumnFilter('primary_light')">Apply</button>
                                        <button onclick="event.stopPropagation(); clearColumnFilter('primary_light')">Clear</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </th>
                    <th>
                        <div class="column-header">
                            Verdict
                            <div class="filter-dropdown" onclick="event.stopPropagation();">
                                <button class="filter-btn" onclick="toggleFilterDropdown(event, 'verdict')" id="filter-btn-verdict">▿</button>
                                <div class="filter-dropdown-content" id="verdictFilter" onclick="event.stopPropagation();">
                                    <div class="filter-select-actions">
                                        <button onclick="event.stopPropagation(); selectAllColumnFilter('verdict')">Select All</button>
                                        <button onclick="event.stopPropagation(); deselectAllColumnFilter('verdict')">Deselect All</button>
                                    </div>
                                    <div id="verdict-filter-options"></div>
                                    <div class="filter-actions">
                                        <button onclick="event.stopPropagation(); applyColumnFilter('verdict')">Apply</button>
                                        <button onclick="event.stopPropagation(); clearColumnFilter('verdict')">Clear</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </th>
                </tr>
            </thead>
            <tbody>
                <!-- Table rows will be populated here -->
            </tbody>
        `;
    }
    
    renderTable(properties, currentPage, itemsPerPage) {
        const tbody = document.querySelector('.properties-table tbody');
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
        const walkTime = property.station_distance_minutes 
            ? `${property.station_distance_minutes}min`
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
                <td class="actions">
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
        const resultsInfo = document.getElementById('resultsInfo');
        
        if (resultsCount && resultsInfo) {
            const filterText = appState.hasActiveFilters() ? ' (filtered)' : '';
            resultsCount.innerHTML = `
                Showing ${start.toLocaleString()}-${end.toLocaleString()} of ${total.toLocaleString()} properties${filterText}
                ${appState.isBackgroundLoading ? '<span style="color: var(--ink-light); font-size: 12px;"> ・ loading...</span>' : ''}
            `;
            
            // Show results info
            resultsInfo.style.display = 'block';
        }
    }
    
    renderLoadingSkeleton() {
        const loadingDiv = document.getElementById('loading');
        if (!loadingDiv) return;
        
        // Simple loading text - no complex skeleton
        loadingDiv.innerHTML = `
            <div style="text-align: center; padding: 60px 0; color: var(--ink-light);">
                <div style="font-size: 14px; letter-spacing: 0.1em; margin-bottom: 20px;">読込中...</div>
                <div style="font-size: 12px; opacity: 0.6;">Loading properties...</div>
            </div>
        `;
    }
}