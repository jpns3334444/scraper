/**
 * FavoritesView.js
 * Handles rendering of favorites list
 */

class FavoritesView {
    renderFavorites(favoriteProperties) {
        const favoritesList = document.getElementById('favoritesList');
        if (!favoritesList) return;
        
        favoritesList.innerHTML = favoriteProperties.map(property => this.renderFavoriteCard(property)).join('');
    }
    
    renderFavoriteCard(property) {
        const price = formatPrice(property.price, '', true);
        const ward = property.ward || 'Unknown';
        const size = property.size_sqm || property.total_sqm ? 
            `${Math.round(property.size_sqm || property.total_sqm)}m²` : 'N/A';
        
        return `
            <div class="favorite-card" onclick="openListing(event, '${property.listing_url}')">
                <button class="remove-favorite-btn" onclick="window.app.favorites.toggleFavorite('${property.property_id}', this)">
                    ×
                </button>
                <div class="favorite-image-section">
                    <div class="image-placeholder">🏠</div>
                </div>
                <div class="favorite-details-section">
                    <div class="favorite-ward">${ward}</div>
                    <div class="favorite-price">${price}</div>
                    <div class="favorite-size">${size}</div>
                </div>
                <div class="favorite-status-section">
                    <span class="processing-status processed">View</span>
                </div>
            </div>
        `;
    }
}