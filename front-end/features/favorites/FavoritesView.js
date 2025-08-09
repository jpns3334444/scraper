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
        
        // Generate card HTML for each property (with async image loading)
        const cardPromises = favoriteProperties.map(property => this.renderFavoriteCard(property));
        const cards = await Promise.all(cardPromises);
        
        favoritesList.innerHTML = cards.join('');
    }
    
    async renderFavoriteCard(property) {
        // Extract only the data we need
        const ward = property.ward || '—';
        const price = property.price ? `¥${(property.price * 10000).toLocaleString()}` : '—';
        const size = property.size_sqm || property.total_sqm ? 
            `${Math.round(property.size_sqm || property.total_sqm)}m²` : '—';
        const url = property.listing_url || '#';
        
        // Get property image
        const imageUrl = await this.getPropertyImage(property);
        const imageHtml = imageUrl ? 
            `<img src="${imageUrl}" alt="Property image" onError="this.parentElement.classList.add('no-image'); this.parentElement.innerHTML='No Image';">` : 
            '<div class="no-image">No Image</div>';
        
        // Determine processing status - Since analysis starts automatically when favorited, default to processing
        let statusClass = 'processing';
        let statusText = 'Processing';
        let isClickable = false;
        
        if (property.analysis_status === 'completed' || (property.analysis_result && Object.keys(property.analysis_result).length > 0)) {
            statusClass = 'processed';
            statusText = 'Processed';
            isClickable = true;
        } else if (property.analysis_status === 'failed') {
            statusClass = 'failed';
            statusText = 'Failed';
        }
        // Default is already 'processing' for pending or processing states
        
        // Card with image on left, essential information
        return `
            <div class="favorite-card" data-property-id="${property.property_id}" onclick="openListing(event, '${url}')" style="cursor: pointer;">
                <div class="favorite-image-section">
                    ${imageHtml}
                </div>
                <div class="favorite-details-section">
                    <div class="favorite-ward">${ward}</div>
                    <div class="favorite-price">${price}</div>
                    <div class="favorite-size">${size}</div>
                </div>
                <button class="processing-status ${statusClass}" 
                    ${isClickable ? `onclick="window.app.favorites.showAnalysisPopup('${property.property_id}'); event.stopPropagation();"` : 'disabled'}
                    ${isClickable ? 'style="cursor: pointer;"' : ''}
                    title="${isClickable ? 'View Analysis' : statusText}">${statusText}</button>
                <button class="remove-favorite-btn" onclick="event.stopPropagation(); removeFavorite('${property.property_id}')" title="Remove from favorites">
                    <svg width="12" height="12" viewBox="0 0 12 12">
                        <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" stroke-width="1.5"/>
                    </svg>
                </button>
            </div>`;
    }
    
    async getPropertyImage(property) {
        // Check if property has image_url or image_key field
        if (property.image_url) {
            return property.image_url;
        } else if (property.image_key || property.image_s3_key) {
            // Generate pre-signed URL via API
            try {
                const response = await fetch(`${API_URL}/properties/${property.property_id}/image-url`);
                if (response.ok) {
                    const data = await response.json();
                    return data.presigned_url || data.image_url;
                }
            } catch (error) {
                console.error('Failed to get image URL:', error);
            }
        }
        return null;
    }
}