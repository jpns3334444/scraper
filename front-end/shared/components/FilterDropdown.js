/**
 * FilterDropdown.js
 * Column filter dropdown component
 */

class FilterDropdown {
    constructor() {
        this.activeDropdown = null;
    }
    
    toggle(event, column) {
        event.stopPropagation();
        
        // Close other dropdowns
        document.querySelectorAll('.filter-dropdown').forEach(dropdown => {
            if (dropdown.id !== `${column}Filter`) {
                dropdown.style.display = 'none';
            }
        });
        
        // Toggle current dropdown
        const dropdown = document.getElementById(`${column}Filter`);
        if (dropdown) {
            dropdown.style.display = dropdown.style.display === 'block' ? 'none' : 'block';
            this.activeDropdown = dropdown.style.display === 'block' ? column : null;
        }
    }
    
    populateFilter(column, values) {
        const dropdown = document.getElementById(`${column}Filter`);
        if (!dropdown) return;
        
        let html = `
            <div class="filter-options">
                <label><input type="checkbox" class="filter-all" onchange="this.toggleAll('${column}')"> All</label>
        `;
        
        values.forEach(value => {
            html += `
                <label>
                    <input type="checkbox" value="${value}" onchange="this.applyFilter('${column}')">
                    ${value}
                </label>
            `;
        });
        
        html += `
                <div class="filter-actions">
                    <button onclick="this.clearFilter('${column}')">Clear</button>
                    <button onclick="this.applyFilter('${column}')">Apply</button>
                </div>
            </div>
        `;
        
        dropdown.innerHTML = html;
    }
    
    applyFilter(column) {
        // Implementation would trigger filter application
        console.log(`Applying filter for column: ${column}`);
    }
    
    clearFilter(column) {
        // Implementation would clear filter
        console.log(`Clearing filter for column: ${column}`);
    }
}

// Global functions for backwards compatibility with onclick handlers
function toggleFilterDropdown(event, column) {
    if (window.app && window.app.filterDropdown) {
        window.app.filterDropdown.toggle(event, column);
    }
}