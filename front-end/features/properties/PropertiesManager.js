/**
 * PropertiesManager.js
 * Fixed sorting functionality
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
            // 1️⃣ Fetch the first page
            const firstPage = await this.api.fetchPropertiesPage(cursor);
            
            // Items are now filtered server-side for price < 3000万円
            const filteredFirstPage = firstPage.items || [];
            
            this.state.addProperties(filteredFirstPage);
            
            // Update favorite status
            this.updateFavoriteStatus(this.state.allProperties);
            
            this.state.filteredProperties = [...this.state.allProperties];
            
            // Hide loading and show table immediately
            DOMUtils.hideElement('loading');
            DOMUtils.showElement('tableContainer');
            
            // Apply initial sort and render first page
            this.applySort();
            this.renderCurrentPage();
            this.populateColumnFilters();
            
            cursor = firstPage.nextCursor; // may be null / false
            
            // 2️⃣ Fire-and-forget the rest with recursive loading
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
            return;
        }
        
        this.state.setBackgroundLoading(true);
        console.log('Loading page with cursor:', cursor);
        
        try {
            const page = await this.api.fetchPropertiesPage(cursor);
            console.log('Loaded page, next cursor:', page.nextCursor);
            console.log('Page items count:', page.items?.length || 0);
            
            const filteredItems = page.items || [];
            
            console.log('Filtered items count:', filteredItems.length);
            
            // Update favorite status for new items
            this.updateFavoriteStatus(filteredItems);
            
            this.state.addProperties(filteredItems);
            console.log('Total properties loaded so far:', this.state.allProperties.length);
            
            // Update filtered properties if no filters are active
            if (!this.state.hasActiveFilters()) {
                this.state.filteredProperties.push(...filteredItems);
                // Mark that a resort is needed but don't do it immediately during background loading
                this.state.needsResort = true;
                
                // Only update UI subtly during background loading
                if (document.getElementById('properties-tab').classList.contains('active')) {
                    // Just update the count without re-rendering
                    this.updateResultsInfo();
                    
                    // If user is on page 1, don't re-render at all to avoid flicker
                    // If on later pages, only update pagination
                    if (this.state.currentPage > 1) {
                        this.renderPagination();
                    }
                }
            }
            
            // Continue loading next page recursively
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
    
    sortTable(field) {
        // Toggle direction if same field, otherwise start with desc
        if (this.state.currentSort.field === field) {
            const newDirection = this.state.currentSort.direction === 'asc' ? 'desc' : 'asc';
            this.state.setSort(field, newDirection);
        } else {
            this.state.setSort(field, 'desc');
        }
        
        // Apply deferred sort if needed
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
            
            // Special handling for year_built field
            if (field === 'year_built') {
                valA = a.building_age_years !== undefined ? new Date().getFullYear() - a.building_age_years : null;
                valB = b.building_age_years !== undefined ? new Date().getFullYear() - b.building_age_years : null;
            } else {
                valA = a[field];
                valB = b[field];
            }
            
            // Handle null/undefined values
            if (valA == null && valB == null) return 0;
            if (valA == null) return 1;
            if (valB == null) return -1;
            
            // Convert to numbers for numeric fields
            if (typeof valA === 'string' && !isNaN(valA)) valA = parseFloat(valA);
            if (typeof valB === 'string' && !isNaN(valB)) valB = parseFloat(valB);
            
            let result = 0;
            if (valA < valB) result = -1;
            else if (valA > valB) result = 1;
            
            return direction === 'asc' ? result : -result;
        });
    }
    
    updateSortArrows() {
        // Reset all arrows to default state
        document.querySelectorAll('.sort-arrows').forEach(arrow => {
            arrow.classList.remove('active');
            arrow.textContent = '▼';
        });
        
        // Set active arrow with proper direction
        const activeArrow = document.getElementById(`sort-${this.state.currentSort.field}`);
        if (activeArrow) {
            activeArrow.classList.add('active');
            activeArrow.textContent = this.state.currentSort.direction === 'asc' ? '▲' : '▼';
        }
    }
    
    renderCurrentPage() {
        // Don't re-render during background loading if user is on first page to avoid flicker
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
        
        // Previous button
        html += `<button onclick="goToPage(${this.state.currentPage - 1})" ${this.state.currentPage === 1 ? 'disabled' : ''}>Previous</button>`;
        
        // Page numbers
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
        
        // Next button
        html += `<button onclick="goToPage(${this.state.currentPage + 1})" ${this.state.currentPage === totalPages ? 'disabled' : ''}>Next</button>`;
        
        paginationDiv.innerHTML = html;
    }
    
    populateColumnFilters() {
        // Implementation for populating dropdown filters
        // This would extract unique values from properties for each filterable column
        const wards = [...new Set(this.state.allProperties.map(p => p.ward).filter(Boolean))];
        const lights = [...new Set(this.state.allProperties.map(p => p.primary_light).filter(Boolean))];
        const verdicts = [...new Set(this.state.allProperties.map(p => p.verdict || p.recommendation).filter(Boolean))];
        
        // Store in state for use by filter components
        this.state.availableFilters = { wards, lights, verdicts };
    }
    
    applyFilters() {
        const filters = this.state.currentFilters;
        
        this.state.filteredProperties = this.state.allProperties.filter(property => {
            // Ward filter
            if (filters.ward.length > 0 && !filters.ward.includes(property.ward)) {
                return false;
            }
            
            // Light filter
            if (filters.primary_light.length > 0 && !filters.primary_light.includes(property.primary_light)) {
                return false;
            }
            
            // Verdict filter
            const verdict = property.verdict || property.recommendation;
            if (filters.verdict.length > 0 && !filters.verdict.includes(verdict)) {
                return false;
            }
            
            // Hide hidden properties
            if (this.state.hidden.has(property.property_id)) {
                return false;
            }
            
            return true;
        });
        
        this.state.setPage(1);
        this.applySort();
        this.renderCurrentPage();
    }
    
    async toggleHidden(propertyId, button) {
        event.stopPropagation();
        
        this.state.toggleHidden(propertyId);
        
        // Save to storage
        StorageManager.saveHidden(this.state.hidden);
        
        // Update UI
        this.updateHiddenCount();
        
        // Re-apply filters to hide the property
        this.applyFilters();
    }
    
    updateHiddenCount() {
        const hiddenCount = document.getElementById('hiddenCount');
        if (hiddenCount) {
            hiddenCount.textContent = this.state.hidden.size.toString();
        }
    }
}

// Global functions for backwards compatibility with onclick handlers
function sortTable(field) {
    if (window.app && window.app.properties) {
        window.app.properties.sortTable(field);
    }
}

function toggleHidden(propertyId, button) {
    if (window.app && window.app.properties) {
        window.app.properties.toggleHidden(propertyId, button);
    }
}

function goToPage(page) {
    if (window.app && window.app.properties) {
        window.app.properties.state.setPage(page);
        window.app.properties.renderCurrentPage();
    }
}

function openListing(event, url) {
    // Don't open if clicking on buttons or other interactive elements
    if (event.target.tagName === 'BUTTON' || event.target.closest('button')) {
        return;
    }
    window.open(url, '_blank');
}