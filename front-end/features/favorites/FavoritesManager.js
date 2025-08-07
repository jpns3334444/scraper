/**
 * FavoritesManager.js
 * Handles favorites functionality including loading, adding, removing, and syncing with API
 */

class FavoritesManager {
    constructor(api, state) {
        this.api = api;
        this.state = state;
        this.view = null;
    }
    
    setView(view) {
        this.view = view;
    }
    
    async toggleFavorite(propertyId, button) {
        event.stopPropagation();
        button.disabled = true;
        const isFavorited = button.classList.contains('favorited');
        
        try {
            if (!this.state.currentUser) {
                // Anonymous user - use localStorage
                if (isFavorited) {
                    this.state.removeFavorite(propertyId);
                    button.classList.remove('favorited');
                    button.textContent = '♡';
                } else {
                    this.state.addFavorite(propertyId);
                    button.classList.add('favorited');
                    button.textContent = '♥';
                }
                this.saveFavoritesToStorage();
                this.deltaFavorites(isFavorited ? -1 : 1);
            } else {
                // Authenticated user - use API
                try {
                    await this.api.toggleFavorite(propertyId, this.state.currentUser.email, isFavorited);
                    
                    if (isFavorited) {
                        button.classList.remove('favorited');
                        button.textContent = '♡';
                        this.state.removeFavorite(propertyId);
                        this.deltaFavorites(-1);
                    } else {
                        button.classList.add('favorited');
                        button.textContent = '♥';
                        this.state.addFavorite(propertyId);
                        this.deltaFavorites(+1);
                    }
                } catch (error) {
                    console.error('API error:', error);
                    // Revert on error
                }
            }
            
            // Update property status
            const property = this.state.getProperty(propertyId);
            if (property) {
                property.is_favorited = this.state.favorites.has(propertyId);
            }
            
        } catch (error) {
            console.error('Toggle favorite error:', error);
        } finally {
            button.disabled = false;
        }
    }
    
    async loadUserFavorites() {
        if (!this.state.currentUser) {
            this.loadFavoritesFromStorage();
            return;
        }
        
        try {
            const favoritesList = await this.api.loadUserFavorites(this.state.currentUser.email);
            const favoriteIds = favoritesList.map(fav => fav.property_id);
            this.state.setFavorites(favoriteIds);
            this.updateFavoritesCount();
        } catch (error) {
            console.error('Failed to load user favorites:', error);
            this.loadFavoritesFromStorage();
        }
    }
    
    loadFavoritesFromStorage() {
        const favorites = StorageManager.loadFavorites();
        this.state.setFavorites(favorites);
    }
    
    saveFavoritesToStorage() {
        StorageManager.saveFavorites(this.state.favorites);
    }
    
    async loadFavorites() {
        console.log('[DEBUG] Loading favorites tab...');
        
        const favoritesList = document.getElementById('favoritesList');
        if (!favoritesList) return;
        
        const favoriteProperties = this.state.getFavoriteProperties();
        
        if (favoriteProperties.length === 0) {
            favoritesList.innerHTML = '<div class="favorites-empty">No favorites yet. Click the ♡ on properties to add them here.</div>';
            return;
        }
        
        // Render favorites
        if (this.view) {
            this.view.renderFavorites(favoriteProperties);
        }
    }
    
    updateFavoritesCount() {
        const favoritesCount = document.getElementById('favoritesCount');
        if (favoritesCount) {
            favoritesCount.textContent = this.state.favorites.size.toString();
        }
    }
    
    deltaFavorites(delta) {
        const el = document.getElementById('favoritesCount');
        if (el) {
            el.textContent = Math.max(0, (parseInt(el.textContent) || 0) + delta);
        }
    }
}

// Global functions for backwards compatibility with onclick handlers
function toggleFavorite(propertyId, button) {
    if (window.app && window.app.favorites) {
        window.app.favorites.toggleFavorite(propertyId, button);
    }
}