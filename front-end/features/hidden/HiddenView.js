/**
 * HiddenView.js
 * Hidden items view matching favorites card style
 */

class HiddenView {
    async renderHidden(hiddenProperties) {
        const hiddenList = document.getElementById('hiddenList');
        if (!hiddenList) return;
        
        // Change container class to match favorites
        hiddenList.className = 'hidden-container';
        
        // Sort by price descending
        hiddenProperties.sort((a, b) => (b.price || 0) - (a.price || 0));
        
        // Generate card HTML for each property
        const cardPromises = hiddenProperties.map(property => this.renderHiddenCard(property));
        const cards = await Promise.all(cardPromises);
        
        hiddenList.innerHTML = cards.join('');
    }
    
    async renderHiddenCard(property) {
        // Extract data matching favorites format
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
                <button class="restore-btn" onclick="event.stopPropagation(); restoreProperty('${property.property_id}')" title="Restore property">
                    ↺
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

// Add global function for restore
async function restoreProperty(propertyId) {
    if (window.app && window.app.hidden) {
        await window.app.hidden.removeHidden(propertyId);
    }
}