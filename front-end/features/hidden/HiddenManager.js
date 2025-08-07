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
}