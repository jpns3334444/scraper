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
    
    loadFromStorage() {
        const hidden = StorageManager.loadHidden();
        this.state.setHidden(hidden);
    }
    
    updateHiddenCount() {
        const hiddenCount = document.getElementById('hiddenCount');
        if (hiddenCount) {
            hiddenCount.textContent = this.state.hidden.size.toString();
        }
    }
    
    async removeHidden(propertyId) {
        if (!confirm('Remove this property from hidden list?')) return;
        
        try {
            // Call API if user is logged in
            if (this.state.currentUser) {
                await this.api.removeHidden(propertyId, this.state.currentUser.email);
            }
            
            // Update local state
            this.state.removeHidden(propertyId);
            this.updateHiddenCount();
            
            // Refresh the hidden list display
            this.loadHidden();
            
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