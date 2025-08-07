/**
 * Pagination.js
 * Pagination component for property listings
 */

class Pagination {
    constructor(containerId) {
        this.containerId = containerId;
    }
    
    render(currentPage, totalPages, onPageChange) {
        const container = document.getElementById(this.containerId);
        if (!container) return;
        
        let paginationHTML = '<div class="pagination">';
        
        // Previous button
        if (currentPage > 1) {
            paginationHTML += `<button onclick="${onPageChange}(${currentPage - 1})">« Previous</button>`;
        }
        
        // Page numbers
        const startPage = Math.max(1, currentPage - 2);
        const endPage = Math.min(totalPages, currentPage + 2);
        
        for (let i = startPage; i <= endPage; i++) {
            const activeClass = i === currentPage ? 'active' : '';
            paginationHTML += `<button class="${activeClass}" onclick="${onPageChange}(${i})">${i}</button>`;
        }
        
        // Next button
        if (currentPage < totalPages) {
            paginationHTML += `<button onclick="${onPageChange}(${currentPage + 1})">Next »</button>`;
        }
        
        paginationHTML += '</div>';
        container.innerHTML = paginationHTML;
    }
}