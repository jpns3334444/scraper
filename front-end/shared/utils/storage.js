/**
 * storage.js
 * localStorage helpers and user ID management
 */

class StorageManager {
    static saveToLocalStorage(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch (error) {
            console.error('Failed to save to localStorage:', error);
        }
    }
    
    static loadFromLocalStorage(key) {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : null;
        } catch (error) {
            console.error('Failed to load from localStorage:', error);
            return null;
        }
    }
    
    static removeFromLocalStorage(key) {
        try {
            localStorage.removeItem(key);
        } catch (error) {
            console.error('Failed to remove from localStorage:', error);
        }
    }
    
    static getUserId() {
        // Use authenticated user email if available, otherwise fallback to anonymous
        if (window.appState && window.appState.currentUser) {
            return window.appState.currentUser.email;
        }
        
        let userId = localStorage.getItem('user_id');
        if (!userId) {
            userId = 'user_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('user_id', userId);
        }
        return userId;
    }
    
    static saveFavorites(favorites) {
        const userId = this.getUserId();
        this.saveToLocalStorage(`favorites_${userId}`, Array.from(favorites));
    }
    
    static loadFavorites() {
        const userId = this.getUserId();
        const saved = this.loadFromLocalStorage(`favorites_${userId}`);
        return saved ? new Set(saved) : new Set();
    }
    
    static saveHidden(hidden) {
        const userId = this.getUserId();
        this.saveToLocalStorage(`hidden_${userId}`, Array.from(hidden));
    }
    
    static loadHidden() {
        const userId = this.getUserId();
        const saved = this.loadFromLocalStorage(`hidden_${userId}`);
        return saved ? new Set(saved) : new Set();
    }
    
    static saveFilters(filters) {
        const userId = this.getUserId();
        this.saveToLocalStorage(`filters_${userId}`, filters);
    }
    
    static loadFilters() {
        const userId = this.getUserId();
        const saved = this.loadFromLocalStorage(`filters_${userId}`);
        // Return default filter structure if nothing saved
        return saved || {
            ward: [],
            floor: [],
            primary_light: [],
            verdict: []
        };
    }
}