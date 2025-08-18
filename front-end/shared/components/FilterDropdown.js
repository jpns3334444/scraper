/**
 * FilterDropdown.js
 * Column filter dropdown component
 */

class FilterDropdown {
    constructor() {
        this.activeDropdown = null;
        
        // Close dropdowns when clicking outside
        document.addEventListener('click', (event) => {
            if (!event.target.closest('.filter-dropdown')) {
                this.closeAll();
            }
        });
    }
    
    closeAll() {
        document.querySelectorAll('.filter-dropdown-content').forEach(dropdown => {
            dropdown.style.display = 'none';
        });
        this.activeDropdown = null;
    }
    
    toggle(event, column) {
        event.stopPropagation();
        
        // Close other dropdowns
        document.querySelectorAll('.filter-dropdown-content').forEach(dropdown => {
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
    
}

// Global functions for backwards compatibility with onclick handlers
function toggleFilterDropdown(event, column) {
    if (window.app && window.app.filterDropdown) {
        window.app.filterDropdown.toggle(event, column);
    }
}