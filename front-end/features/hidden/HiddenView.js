/**
 * HiddenView.js
 * Hidden items view matching favorites card style, now with HiddenStore integration
 */

class HiddenView {
    async renderHidden(hiddenProperties = null) {
        const hiddenList = document.getElementById('hiddenList');
        if (!hiddenList) return;
        
        // Change container class to match favorites
        hiddenList.className = 'hidden-container';
        
        // Get HiddenStore and current properties for lookup
        const HiddenStore = window.HiddenStore || (window.app && window.app.HiddenStore);
        const getPropertyId = window.getPropertyId || (window.app && window.app.getPropertyId) || ((p) => String(p.listing_id ?? p.property_id ?? p.id));
        
        console.log('[DEBUG] HiddenView.renderHidden called');
        console.log('[DEBUG] HiddenStore available:', !!HiddenStore);
        console.log('[DEBUG] HiddenStore loaded:', HiddenStore ? HiddenStore.isLoaded() : false);
        
        if (!HiddenStore || !HiddenStore.isLoaded()) {
            console.log('[DEBUG] HiddenStore not ready, showing loading message');
            hiddenList.innerHTML = '<div style="padding:40px; text-align:center; color:#999;">Loading hidden items...</div>';
            return;
        }
        
        // Get all hidden IDs from HiddenStore
        const hiddenIds = HiddenStore.all();
        console.log('[DEBUG] Hidden IDs from HiddenStore:', hiddenIds);
        
        if (hiddenIds.length === 0) {
            hiddenList.innerHTML = '<div style="padding:40px; text-align:center; color:#999;">No hidden items.</div>';
            return;
        }
        
        // Build a lookup map of properties by canonical ID
        const propertyLookup = new Map();
        if (window.app && window.app.state && window.app.state.allProperties) {
            window.app.state.allProperties.forEach(prop => {
                const id = getPropertyId(prop);
                propertyLookup.set(id, prop);
            });
        }
        
        // Create cards for each hidden ID
        const cardPromises = hiddenIds.map(hiddenId => {
            const property = propertyLookup.get(hiddenId);
            if (property) {
                return this.renderHiddenCard(property);
            } else {
                // Render placeholder card for missing property
                return this.renderPlaceholderCard(hiddenId);
            }
        });
        
        const cards = await Promise.all(cardPromises);
        
        // Sort cards by property data (properties first, placeholders last)
        const sortedCards = cards.sort((a, b) => {
            const aIsPlaceholder = a.includes('placeholder-card');
            const bIsPlaceholder = b.includes('placeholder-card');
            if (aIsPlaceholder && !bIsPlaceholder) return 1;
            if (!aIsPlaceholder && bIsPlaceholder) return -1;
            return 0;
        });
        
        hiddenList.innerHTML = sortedCards.join('');
    }
    
    renderPlaceholderCard(hiddenId) {
        return `
            <div class="hidden-card placeholder-card" data-property-id="${hiddenId}" style="opacity: 0.7; border: 2px dashed #ccc;">
                <div class="hidden-image-section">
                    <div class="no-image" style="background: #f5f5f5; color: #999;">Hidden Item</div>
                </div>
                <div class="hidden-details-section">
                    <div class="hidden-ward">ID: ${hiddenId}</div>
                    <div class="hidden-price">Property not in current dataset</div>
                    <div class="hidden-size">—</div>
                </div>
                <button class="restore-btn" onclick="event.stopPropagation(); restoreProperty('${hiddenId}')" title="Restore property">
                    ↺
                </button>
            </div>`;
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

// Add global function for restore using HiddenStore
async function restoreProperty(propertyId) {
    const HiddenStore = window.HiddenStore || (window.app && window.app.HiddenStore);
    const getPropertyId = window.getPropertyId || (window.app && window.app.getPropertyId) || ((p) => String(p.listing_id ?? p.property_id ?? p.id));
    
    try {
        if (HiddenStore && HiddenStore.isLoaded && HiddenStore.isLoaded()) {
            // Use new HiddenStore
            const canonicalId = getPropertyId({ property_id: propertyId });
            await HiddenStore.remove(canonicalId);
            
            // Animate removal from hidden view
            const card = document.querySelector(`.hidden-card[data-property-id="${propertyId}"]`);
            if (card) {
                card.style.transition = 'all 0.3s';
                card.style.opacity = '0';
                card.style.transform = 'translateX(-100%)';
                setTimeout(() => {
                    card.remove();
                    // Check if no hidden items left
                    if (document.querySelectorAll('.hidden-card').length === 0) {
                        const container = document.querySelector('.hidden-container');
                        if (container) {
                            container.innerHTML = '<div style="padding:40px; text-align:center; color:#999;">No hidden items.</div>';
                        }
                    }
                }, 300);
            }
        } else {
            // Fallback to legacy HiddenManager
            if (window.app && window.app.hidden) {
                await window.app.hidden.removeHidden(propertyId);
            }
        }
    } catch (error) {
        console.error('Error restoring property:', error);
        alert('Error restoring property from hidden list');
    }
}