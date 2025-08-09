/**
 * HiddenManager.js
 * FIXED: Simplified hidden items functionality with proper ID handling
 */

class HiddenManager {
    constructor(api, state) {
        this.api = api;
        this.state = state;
        this.view = null;
    }
    
    setView(view) {
        this.view = view;
    }
    
    async toggleHidden(propertyId, button) {
        event.stopPropagation();
        button.disabled = true;
        
        try {
            const isCurrentlyHidden = this.state.hidden.has(propertyId);
            
            if (isCurrentlyHidden) {
                // Remove from hidden
                if (this.state.currentUser) {
                    await this.api.removeHidden(propertyId, this.state.currentUser.email);
                }
                this.state.removeHidden(propertyId);
            } else {
                // Add to hidden
                if (this.state.currentUser) {
                    await this.api.addHidden(propertyId, this.state.currentUser.email);
                }
                this.state.addHidden(propertyId);
            }
            
            // Save to localStorage for anonymous users
            if (!this.state.currentUser) {
                this.saveHiddenToStorage();
            }
            
            // Update count
            this.updateHiddenCount();
            
            // Re-filter properties to hide/show the property immediately
            if (window.app && window.app.properties) {
                window.app.properties.applyFilters();
            }
            
            // If on hidden tab, refresh the view
            if (window.app.router.getCurrentTab() === 'hidden') {
                this.loadHidden();
            }
            
        } catch (error) {
            console.error('Error toggling hidden property:', error);
            alert('Error updating hidden status');
        } finally {
            button.disabled = false;
        }
    }
    
    async loadUserHidden() {
        if (!this.state.currentUser) {
            this.loadHiddenFromStorage();
            return;
        }
        
        try {
            const hiddenList = await this.api.loadUserHidden(this.state.currentUser.email);
            const hiddenIds = hiddenList.map(h => h.property_id);
            this.state.setHidden(hiddenIds);
            this.updateHiddenCount();
        } catch (error) {
            console.error('Failed to load user hidden:', error);
            this.loadHiddenFromStorage();
        }
    }
    
    loadHiddenFromStorage() {
        const hidden = StorageManager.loadHidden();
        this.state.setHidden(hidden);
        this.updateHiddenCount();
    }
    
    saveHiddenToStorage() {
        StorageManager.saveHidden(this.state.hidden);
    }
    
    loadHidden() {
        console.log('[DEBUG] Loading hidden tab...');
        
        const hiddenList = document.getElementById('hiddenList');
        if (!hiddenList) return;
        
        // Change class to match favorites style
        hiddenList.className = 'hidden-container';
        
        const hiddenProperties = this.state.getHiddenProperties();
        
        if (hiddenProperties.length === 0) {
            hiddenList.innerHTML = '<div style="padding:40px; text-align:center; color:#999;">No hidden items.</div>';
            return;
        }
        
        if (this.view) {
            this.view.renderHidden(hiddenProperties);
        }
    }
    
    async removeHidden(propertyId) {
        try {
            if (this.state.currentUser) {
                await this.api.removeHidden(propertyId, this.state.currentUser.email);
            }
            
            this.state.removeHidden(propertyId);
            this.saveHiddenToStorage();
            this.updateHiddenCount();
            
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
            
            // Refresh properties to show the restored item
            if (window.app.router.getCurrentTab() === 'properties') {
                window.app.properties.applyFilters();
            }
            
        } catch (error) {
            console.error('Error removing hidden property:', error);
            alert('Error removing property from hidden list');
        }
    }
    
    updateHiddenCount() {
        const hiddenCount = document.getElementById('hiddenCount');
        if (hiddenCount) {
            hiddenCount.textContent = this.state.hidden.size.toString();
        }
    }
}

// Global functions for backwards compatibility
function toggleHidden(propertyId, button) {
    if (window.app && window.app.hidden) {
        window.app.hidden.toggleHidden(propertyId, button);
    }
}

function removeHiddenProperty(propertyId) {
    if (window.app && window.app.hidden) {
        window.app.hidden.removeHidden(propertyId);
    }
}