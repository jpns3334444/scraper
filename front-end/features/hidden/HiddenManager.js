/**
 * HiddenManager.js
 * Manages hidden items functionality
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
    
    loadHidden() {
        console.log('[DEBUG] Loading hidden tab...');
        
        const hiddenList = document.getElementById('hiddenList');
        if (!hiddenList) return;
        
        const hiddenProperties = this.state.getHiddenProperties();
        
        if (hiddenProperties.length === 0) {
            hiddenList.innerHTML = '<li class="hidden-empty">No hidden items.</li>';
            return;
        }
        
        if (this.view) {
            this.view.renderHidden(hiddenProperties);
        }
    }
    
    async loadUserHidden() {
        if (!this.state.currentUser) {
            this.loadHiddenFromStorage();
            return;
        }
        
        try {
            const hiddenList = await this.api.loadUserHidden(this.state.currentUser.email);
            const hiddenIds = hiddenList.map(hidden => hidden.property_id);
            this.state.setHidden(hiddenIds);
            this.updateHiddenCount();
        } catch (error) {
            console.error('Failed to load user hidden properties:', error);
            this.loadHiddenFromStorage();
        }
    }
    
    loadHiddenFromStorage() {
        const hidden = StorageManager.loadHidden();
        this.state.setHidden(hidden);
    }
    
    loadFromStorage() {
        this.loadHiddenFromStorage();
    }
    
    updateHiddenCount() {
        const hiddenCount = document.getElementById('hiddenCount');
        if (hiddenCount) {
            hiddenCount.textContent = this.state.hidden.size.toString();
        }
    }
    
    async removeHidden(propertyId) {
        
        try {
            // Call API if user is logged in
            if (this.state.currentUser) {
                await this.api.removeHidden(propertyId, this.state.currentUser.email);
            }
            
            // Update local state
            this.state.removeHidden(propertyId);
            StorageManager.saveHidden(this.state.hidden);
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
                        document.querySelector('.hidden-container').innerHTML = 
                            '<div style="padding:40px; text-align:center; color:#999;">No hidden items.</div>';
                    }
                }, 300);
            } else {
                // Fallback: refresh the hidden list display
                this.loadHidden();
            }
            
            // Refresh properties if on that tab to show restored property
            if (document.getElementById('properties-tab').classList.contains('active')) {
                window.app.properties.applyFilters();
            }
            
        } catch (error) {
            console.error('Error removing hidden property:', error);
            alert('Error removing property from hidden list');
        }
    }
}

// Global function for onclick handlers
function removeHiddenProperty(propertyId) {
    if (window.app && window.app.hidden) {
        window.app.hidden.removeHidden(propertyId);
    }
}