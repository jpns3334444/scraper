/**
 * PropertiesManager.js
 * FIXED: Properly filters out hidden properties
 */

class PropertiesManager {
    constructor(api, state) {
        this.api = api;
        this.state = state;
        this.view = null;
    }
    
    setView(view) {
        this.view = view;
    }

    async loadAllProperties() {
        this.state.setLoading(true);
        let cursor = null;
        
        try {
            console.log('[DEBUG] Starting to load properties...');
            
            // IMPORTANT: Wait for hidden items to be loaded first
            // This ensures we filter them out from the beginning
            console.log('[DEBUG] Waiting for hidden items to be fully loaded...');
            
            // Load first page
            const firstPage = await this.api.fetchPropertiesPage(cursor);
            const filteredFirstPage = firstPage.items || [];
            
            console.log('[DEBUG] Loaded first page with', filteredFirstPage.length, 'properties');
            console.log('[DEBUG] Current hidden items count:', this.state.hidden.size);
            console.log('[DEBUG] Hidden IDs:', Array.from(this.state.hidden));
            
            this.state.addProperties(filteredFirstPage);
            this.updateFavoriteStatus(this.state.allProperties);
            this.state.filteredProperties = [...this.state.allProperties];
            
            DOMUtils.hideElement('loading');
            DOMUtils.showElement('tableContainer');
            
            // First populate the filter dropdowns with checkboxes
            // This will also restore the checked state from saved filters
            this.populateColumnFilters();
            
            // Then apply filters INCLUDING hidden filter
            // Use skipSave=true on initial load to avoid overwriting just-restored filters
            this.applyFilters(true);
            
            this.applySort();
            this.renderCurrentPage();
            
            cursor = firstPage.nextCursor;
            
            // Load remaining pages in background
            this.loadRemainingPages(cursor);
            
        } catch (error) {
            console.error('Error loading properties:', error);
            DOMUtils.showErrorBanner('Connection error. Please refresh the page.');
        } finally {
            this.state.setLoading(false);
        }
    }
    
    async loadRemainingPages(cursor) {
        if (!cursor) {
            console.log('No more pages to load');
            this.state.setBackgroundLoading(false);
            this.applyFilters();
            return;
        }
        
        this.state.setBackgroundLoading(true);
        
        try {
            const page = await this.api.fetchPropertiesPage(cursor);
            const filteredItems = page.items || [];
            
            this.updateFavoriteStatus(filteredItems);
            this.state.addProperties(filteredItems);
            
            // Re-apply filters to include new items (but exclude hidden)
            if (!this.state.hasActiveFilters()) {
                // Filter out hidden properties from new items
                const visibleItems = filteredItems.filter(property => 
                    !this.state.hidden.has(property.property_id)
                );
                this.state.filteredProperties.push(...visibleItems);
                this.state.needsResort = true;
                
                if (document.getElementById('properties-tab').classList.contains('active')) {
                    this.updateResultsInfo();
                    if (this.state.currentPage > 1) {
                        this.renderPagination();
                    }
                }
            } else {
                this.state.needsResort = true;
            }
            
            // Continue loading
            await this.loadRemainingPages(page.nextCursor);
            
        } catch (error) {
            console.error('Background loading error:', error);
            this.state.setBackgroundLoading(false);
        }
    }
    
    updateFavoriteStatus(properties) {
        properties.forEach(property => {
            property.is_favorited = this.state.favorites.has(property.property_id);
        });
    }
    
    applyFilters(skipSave = false) {
        const filters = this.state.currentFilters;
        
        // Save filters to localStorage (unless we're just restoring them)
        if (!skipSave) {
            StorageManager.saveFilters(filters);
        }
        
        console.log('[DEBUG] Applying filters, hidden count:', this.state.hidden.size);
        console.log('[DEBUG] Hidden IDs:', Array.from(this.state.hidden));
        console.log('[DEBUG] Current filters:', filters);
        
        this.state.filteredProperties = this.state.allProperties.filter(property => {
            // Ward filter
            if (filters.ward.length > 0 && !filters.ward.includes(property.ward)) {
                return false;
            }
            
            // Light filter
            if (filters.primary_light.length > 0 && !filters.primary_light.includes(property.primary_light)) {
                return false;
            }
            
            // Floor filter
            if (filters.floor.length > 0 && !filters.floor.includes(property.floor)) {
                return false;
            }
            
            // Verdict filter
            const verdict = property.verdict || property.recommendation;
            if (filters.verdict.length > 0 && !filters.verdict.includes(verdict)) {
                return false;
            }
            
            // CRITICAL: Hide hidden properties
            if (this.state.hidden.has(property.property_id)) {
                console.log('[DEBUG] Filtering out hidden property:', property.property_id);
                return false;
            }
            
            return true;
        });
        
        console.log('[DEBUG] Properties after filtering:', this.state.filteredProperties.length, 'visible,', 
            this.state.allProperties.length - this.state.filteredProperties.length, 'filtered out');
        
        this.state.setPage(1);
        this.applySort();
        this.renderCurrentPage();
    }
    
    sortTable(field) {
        if (this.state.currentSort.field === field) {
            const newDirection = this.state.currentSort.direction === 'asc' ? 'desc' : 'asc';
            this.state.setSort(field, newDirection);
        } else {
            this.state.setSort(field, 'desc');
        }
        
        if (this.state.needsResort) {
            this.state.needsResort = false;
        }
        
        this.applySort();
        this.state.setPage(1);
        this.renderCurrentPage();
        this.updateSortArrows();
    }
    
    applySort() {
        const { field, direction } = this.state.currentSort;
        
        this.state.filteredProperties.sort((a, b) => {
            let valA, valB;
            
            if (field === 'year_built') {
                valA = a.building_age_years !== undefined ? new Date().getFullYear() - a.building_age_years : null;
                valB = b.building_age_years !== undefined ? new Date().getFullYear() - b.building_age_years : null;
            } else {
                valA = a[field];
                valB = b[field];
            }
            
            if (valA == null && valB == null) return 0;
            if (valA == null) return 1;
            if (valB == null) return -1;
            
            if (typeof valA === 'string' && !isNaN(valA)) valA = parseFloat(valA);
            if (typeof valB === 'string' && !isNaN(valB)) valB = parseFloat(valB);
            
            let result = 0;
            if (valA < valB) result = -1;
            else if (valA > valB) result = 1;
            
            return direction === 'asc' ? result : -result;
        });
    }
    
    updateSortArrows() {
        document.querySelectorAll('.sort-arrows').forEach(arrow => {
            arrow.classList.remove('active');
            arrow.textContent = '▼';
        });
        
        const activeArrow = document.getElementById(`sort-${this.state.currentSort.field}`);
        if (activeArrow) {
            activeArrow.classList.add('active');
            activeArrow.textContent = this.state.currentSort.direction === 'asc' ? '▲' : '▼';
        }
    }
    
    renderCurrentPage() {
        if (this.state.isBackgroundLoading && this.state.currentPage === 1) {
            return;
        }
        
        if (this.view) {
            this.view.renderTable(this.state.filteredProperties, this.state.currentPage, this.state.itemsPerPage);
        }
        
        this.updateResultsInfo();
        this.renderPagination();
    }
    
    updateResultsInfo() {
        if (this.view) {
            const start = (this.state.currentPage - 1) * this.state.itemsPerPage + 1;
            const end = Math.min(start + this.state.itemsPerPage - 1, this.state.filteredProperties.length);
            const total = this.state.filteredProperties.length;
            this.view.updateResultsInfo(start, end, total);
        }
    }
    
    renderPagination() {
        const totalPages = Math.ceil(this.state.filteredProperties.length / this.state.itemsPerPage);
        const paginationDiv = document.getElementById('pagination');
        const paginationContainer = document.getElementById('paginationContainer');
        
        if (!paginationDiv || totalPages <= 1) {
            if (paginationContainer) paginationContainer.style.display = 'none';
            return;
        }
        
        paginationContainer.style.display = 'block';
        
        let html = '';
        
        html += `<button onclick="goToPage(${this.state.currentPage - 1})" ${this.state.currentPage === 1 ? 'disabled' : ''}>Previous</button>`;
        
        const maxVisiblePages = 7;
        let startPage = Math.max(1, this.state.currentPage - Math.floor(maxVisiblePages / 2));
        let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);
        
        if (endPage - startPage < maxVisiblePages - 1) {
            startPage = Math.max(1, endPage - maxVisiblePages + 1);
        }
        
        if (startPage > 1) {
            html += `<button onclick="goToPage(1)">1</button>`;
            if (startPage > 2) html += '<span class="page-info">...</span>';
        }
        
        for (let i = startPage; i <= endPage; i++) {
            html += `<button onclick="goToPage(${i})" class="${i === this.state.currentPage ? 'active' : ''}">${i}</button>`;
        }
        
        if (endPage < totalPages) {
            if (endPage < totalPages - 1) html += '<span class="page-info">...</span>';
            html += `<button onclick="goToPage(${totalPages})">${totalPages}</button>`;
        }
        
        html += `<button onclick="goToPage(${this.state.currentPage + 1})" ${this.state.currentPage === totalPages ? 'disabled' : ''}>Next</button>`;
        
        paginationDiv.innerHTML = html;
    }
    
    populateColumnFilters() {
        const wards = [...new Set(this.state.allProperties.map(p => p.ward).filter(Boolean))].sort();
        const floors = [...new Set(this.state.allProperties.map(p => p.floor).filter(Boolean))].sort();
        const lights = [...new Set(this.state.allProperties.map(p => p.primary_light).filter(Boolean))].sort();
        const verdicts = [...new Set(this.state.allProperties.map(p => p.verdict || p.recommendation).filter(Boolean))].sort();
        
        this.state.availableFilters = { wards, floors, lights, verdicts };
        
        // Populate the dropdown HTML
        this.populateFilterDropdown('ward', wards);
        this.populateFilterDropdown('floor', floors);
        this.populateFilterDropdown('primary_light', lights);
        this.populateFilterDropdown('verdict', verdicts);
    }
    
    populateFilterDropdown(column, values) {
        const optionsContainer = document.getElementById(`${column}-filter-options`);
        if (!optionsContainer || !values.length) return;
        
        // Get saved filters to know which checkboxes to check
        const savedFilters = this.state.currentFilters[column] || [];
        
        let html = '';
        values.forEach(value => {
            const isChecked = savedFilters.includes(value) ? 'checked' : '';
            html += `
                <label>
                    <input type="checkbox" value="${value}" ${isChecked}>
                    ${value}
                </label>
            `;
        });
        
        optionsContainer.innerHTML = html;
    }
}

// Global functions
function sortTable(field) {
    if (window.app && window.app.properties) {
        window.app.properties.sortTable(field);
    }
}

function goToPage(page) {
    if (window.app && window.app.properties) {
        window.app.properties.state.setPage(page);
        window.app.properties.renderCurrentPage();
    }
}

function openListing(event, url) {
    if (event.target.tagName === 'BUTTON' || event.target.closest('button')) {
        return;
    }
    window.open(url, '_blank');
}