/**
 * FavoritesView.js
 * Minimal Sumi-e style favorites rendering - only ward, price, size, and status
 */

class FavoritesView {
    async renderFavorites(favoriteProperties) {
        const favoritesList = document.getElementById('favoritesList');
        if (!favoritesList) return;
        
        // Sort by price descending
        favoriteProperties.sort((a, b) => (b.price || 0) - (a.price || 0));
        
        // Generate card HTML for each property
        const cards = favoriteProperties.map(property => this.renderFavoriteCard(property));
        
        favoritesList.innerHTML = cards.join('');
    }
    
    renderFavoriteCard(property) {
        // Extract only the data we need
        const ward = property.ward || '—';
        const price = property.price ? `¥${(property.price * 10000).toLocaleString()}` : '—';
        const size = property.size_sqm || property.total_sqm ? 
            `${Math.round(property.size_sqm || property.total_sqm)}m²` : '—';
        const url = property.listing_url || '#';
        
        // Determine processing status
        let statusClass = 'processing';
        let statusText = 'Processing';
        if (property.analysis_status === 'completed' || property.verdict) {
            statusClass = 'processed';
            statusText = 'Processed';
        } else if (property.analysis_status === 'failed') {
            statusClass = 'failed';
            statusText = 'Failed';
        }
        
        // Minimal card with only essential information
        return `
            <div class="favorite-card" data-property-id="${property.property_id}" onclick="openListing(event, '${url}')" style="cursor: pointer;">
                <div class="favorite-details-section">
                    <div class="favorite-ward">${ward}</div>
                    <div class="favorite-price">${price}</div>
                    <div class="favorite-size">${size}</div>
                </div>
                <span class="processing-status ${statusClass}">${statusText}</span>
                <button class="remove-favorite-btn" onclick="event.stopPropagation(); removeFavorite('${property.property_id}')" title="Remove from favorites">
                    <svg width="12" height="12" viewBox="0 0 12 12">
                        <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" stroke-width="1.5"/>
                    </svg>
                </button>
            </div>`;
    }
}