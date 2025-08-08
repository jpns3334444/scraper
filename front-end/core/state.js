/**
 * state.js
 * Global application state management
 */

class AppState {
    constructor() {
        // Data state
        this.cursor = null;          // null = first page; false = no more pages
        this.allProperties = [];
        this.filteredProperties = [];
        this.favorites = new Set();
        this.hidden = new Set();
        this.favoriteAnalyses = new Map();
        
        // User state
        this.currentUser = null;
        
        // UI state
        this.loading = false;
        this.isBackgroundLoading = false;
        this.needsResort = false;
        this.currentSort = { field: 'price', direction: 'desc' };
        this.currentPage = 1;
        this.itemsPerPage = ITEMS_PER_PAGE;
        
        // Filters
        this.currentFilters = {
            ward: [],
            primary_light: [],
            verdict: []
        };
        
        // Event listeners for state changes
        this.listeners = {
            user: [],
            favorites: [],
            hidden: [],
            properties: [],
            filters: [],
            sort: []
        };
    }
    
    // Event system
    on(event, callback) {
        if (this.listeners[event]) {
            this.listeners[event].push(callback);
        }
    }
    
    emit(event, data) {
        if (this.listeners[event]) {
            this.listeners[event].forEach(callback => callback(data));
        }
    }
    
    // User management
    setUser(user) {
        this.currentUser = user;
        this.emit('user', user);
    }
    
    clearUser() {
        this.currentUser = null;
        this.emit('user', null);
    }
    
    // Properties management
    addProperties(properties) {
        this.allProperties.push(...properties);
        this.emit('properties', this.allProperties);
    }
    
    setProperties(properties) {
        this.allProperties = properties;
        this.filteredProperties = [...properties];
        this.emit('properties', this.allProperties);
    }
    
    clearProperties() {
        this.allProperties = [];
        this.filteredProperties = [];
        this.emit('properties', this.allProperties);
    }
    
    // Favorites management
    toggleFavorite(propertyId) {
        if (this.favorites.has(propertyId)) {
            this.favorites.delete(propertyId);
        } else {
            this.favorites.add(propertyId);
        }
        this.emit('favorites', this.favorites);
    }
    
    setFavorites(favoriteIds) {
        this.favorites = new Set(favoriteIds);
        this.emit('favorites', this.favorites);
    }
    
    addFavorite(propertyId) {
        this.favorites.add(propertyId);
        this.emit('favorites', this.favorites);
    }
    
    removeFavorite(propertyId) {
        this.favorites.delete(propertyId);
        this.emit('favorites', this.favorites);
    }
    
    // Hidden management
    toggleHidden(propertyId) {
        if (this.hidden.has(propertyId)) {
            this.hidden.delete(propertyId);
        } else {
            this.hidden.add(propertyId);
        }
        this.emit('hidden', this.hidden);
    }
    
    setHidden(hiddenIds) {
        this.hidden = new Set(hiddenIds);
        this.emit('hidden', this.hidden);
    }
    
    addHidden(propertyId) {
        this.hidden.add(propertyId);
        this.emit('hidden', this.hidden);
    }
    
    removeHidden(propertyId) {
        this.hidden.delete(propertyId);
        this.emit('hidden', this.hidden);
    }
    
    // Sorting
    setSort(field, direction) {
        this.currentSort = { field, direction };
        this.emit('sort', this.currentSort);
    }
    
    // Filters
    setFilters(filters) {
        this.currentFilters = { ...filters };
        this.emit('filters', this.currentFilters);
    }
    
    hasActiveFilters() {
        return Object.values(this.currentFilters).some(filter => 
            Array.isArray(filter) ? filter.length > 0 : filter
        );
    }
    
    // Pagination
    setPage(page) {
        this.currentPage = page;
    }
    
    setItemsPerPage(count) {
        this.itemsPerPage = count;
    }
    
    // Loading states
    setLoading(loading) {
        this.loading = loading;
    }
    
    setBackgroundLoading(loading) {
        this.isBackgroundLoading = loading;
    }
    
    // Utility methods
    getProperty(propertyId) {
        return this.allProperties.find(p => p.property_id === propertyId);
    }
    
    getFavoriteProperties() {
        return this.allProperties.filter(p => this.favorites.has(p.property_id));
    }
    
    getHiddenProperties() {
        return this.allProperties.filter(p => this.hidden.has(p.property_id));
    }
    
    getVisibleProperties() {
        return this.allProperties.filter(p => !this.hidden.has(p.property_id));
    }
    
    // Favorite analyses management
    setFavoriteAnalysis(propertyId, data) {
        this.favoriteAnalyses.set(propertyId, data);
    }
    
    getFavoriteAnalysis(propertyId) {
        return this.favoriteAnalyses.get(propertyId);
    }
    
    clearFavoriteAnalyses() {
        this.favoriteAnalyses.clear();
    }
}

// Global state instance
const appState = new AppState();