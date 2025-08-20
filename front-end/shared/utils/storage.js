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
    
    static getFilterStorageKey() {
        console.log('[FILTER DEBUG] getFilterStorageKey called');
        console.log('[FILTER DEBUG] localStorage user_email:', localStorage.getItem('user_email'));
        console.log('[FILTER DEBUG] localStorage user_id:', localStorage.getItem('user_id'));
        console.log('[FILTER DEBUG] window.appState:', window.appState);
        console.log('[FILTER DEBUG] window.appState.currentUser:', window.appState?.currentUser);
        
        const savedEmail = localStorage.getItem('user_email');
        if (savedEmail) {
            const key = `filters_${savedEmail}`;
            console.log('[FILTER DEBUG] Using email-based key:', key);
            return key;
        }
        
        let userId = localStorage.getItem('user_id');
        if (!userId) {
            userId = 'user_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('user_id', userId);
            console.log('[FILTER DEBUG] Generated new user_id:', userId);
        } else {
            console.log('[FILTER DEBUG] Using existing user_id:', userId);
        }
        const key = `filters_${userId}`;
        console.log('[FILTER DEBUG] Using user_id-based key:', key);
        return key;
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
        console.log('[FILTER DEBUG] === SAVING FILTERS ===');
        console.log('[FILTER DEBUG] Filters to save:', filters);
        console.log('[FILTER DEBUG] Stack trace:', new Error().stack);
        
        const key = this.getFilterStorageKey();
        console.log('[FILTER DEBUG] Final save key:', key);
        
        this.saveToLocalStorage(key, filters);
        
        // Verify the save
        const saved = this.loadFromLocalStorage(key);
        console.log('[FILTER DEBUG] Verification - actually saved:', saved);
        console.log('[FILTER DEBUG] === END SAVE ===');
    }
    
    static loadFilters() {
        console.log('[FILTER DEBUG] === LOADING FILTERS ===');
        console.log('[FILTER DEBUG] Stack trace:', new Error().stack);
        
        const key = this.getFilterStorageKey();
        console.log('[FILTER DEBUG] Final load key:', key);
        
        const saved = this.loadFromLocalStorage(key);
        console.log('[FILTER DEBUG] Loaded data:', saved);
        
        // Show all filter-related keys in localStorage
        console.log('[FILTER DEBUG] All filter keys in localStorage:');
        Object.keys(localStorage).filter(k => k.includes('filter')).forEach(k => {
            console.log(`  ${k}:`, localStorage.getItem(k));
        });
        
        console.log('[FILTER DEBUG] === END LOAD ===');
        
        return saved || {
            ward: [],
            floor: [],
            primary_light: [],
            verdict: []
        };
    }
}