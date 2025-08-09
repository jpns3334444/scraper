/**
 * HiddenView.js
 * SIMPLIFIED: Renders hidden items properly
 */

class HiddenView {
    async renderHidden(hiddenProperties) {
        const hiddenList = document.getElementById('hiddenList');
        if (!hiddenList) return;
        
        // Change container class to match favorites style
        hiddenList.className = 'hidden-container';
        
        if (!hiddenProperties || hiddenProperties.length === 0) {
            hiddenList.innerHTML = '<div style="padding:40px; text-align:center; color:#999;">No hidden items.</div>';
            return;
        }
        
        // Sort by price descending
        hiddenProperties.sort((a, b) => (b.price || 0) - (a.price || 0));
        
        // Generate card HTML for each property
        const cardPromises = hiddenProperties.map(property => this.renderHiddenCard(property));
        const cards = await Promise.all(cardPromises);
        
        hiddenList.innerHTML = cards.join('');
    }
    
    async renderHiddenCard(property) {
        // Extract data
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
        
        // Card matching favorite card style
        return `
            <div class="hidden-card" data-property-id="${property.property_id}" onclick="openListing(event, '${url}')" style="cursor: pointer;">
                <div class="hidden-image-section">
                    ${imageHtml}
                </div>
                <div class="hidden-details-section">
                    <div class="hidden-ward">${ward}</div>
                    <div class="hidden-price">${price}</div>
                    <div class="hidden-size">${size}</div>
                </div>
                <button class="restore-btn" onclick="event.stopPropagation(); removeHiddenProperty('${property.property_id}')" title="Restore property">
                    ↺
                </button>
            </div>`;
    }
    
    async getPropertyImage(property) {
        if (property.image_url) {
            return property.image_url;
        } else if (property.image_key || property.image_s3_key) {
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