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
    
    setViews(favoritesView, analysisView) {
        this.view = favoritesView;
        this.analysisView = analysisView;
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
            
            // Refresh favorites tab if active
            if (document.getElementById('favorites-tab').classList.contains('active')) {
                await this.loadFavorites();
            }
            
        } catch (error) {
            console.error('Toggle favorite error:', error);
        } finally {
            button.disabled = false;
        }
    }
    
    async removeFavorite(propertyId) {
        
        try {
            // Call the same toggle function
            const heartBtn = document.querySelector(`button[data-property-id="${propertyId}"]`);
            if (heartBtn && heartBtn.classList.contains('favorited')) {
                await this.toggleFavorite(propertyId, heartBtn);
            } else {
                // Direct removal if not in main view
                if (this.state.currentUser) {
                    await this.api.removeFavorite(propertyId, this.state.currentUser.email);
                }
                this.state.removeFavorite(propertyId);
                this.saveFavoritesToStorage();
                this.updateFavoritesCount();
            }
            
            // Animate removal from favorites view
            const card = document.querySelector(`.favorite-card[data-property-id="${propertyId}"]`);
            if (card) {
                card.style.transition = 'all 0.3s';
                card.style.opacity = '0';
                card.style.transform = 'translateX(-100%)';
                setTimeout(() => {
                    card.remove();
                    // Check if no favorites left
                    if (document.querySelectorAll('.favorite-card').length === 0) {
                        document.querySelector('.favorites-container').innerHTML = 
                            '<div style="padding:40px; text-align:center; color:#999;">No favorites yet</div>';
                    }
                }, 300);
            }
        } catch (error) {
            console.error('Failed to remove favorite:', error);
            alert('Failed to remove favorite. Please try again.');
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
        
        // For authenticated users, we might need to fetch from API and match with properties
        if (this.state.currentUser) {
            try {
                favoritesList.innerHTML = '<div style="padding:40px; text-align:center; color:#999;">Loading favorites...</div>';
                
                const userFavorites = await this.api.loadUserFavorites(this.state.currentUser.email);
                
                if (userFavorites.length === 0) {
                    favoritesList.innerHTML = '<div class="favorites-empty">No favorites yet. Click the ♡ on properties to add them here.</div>';
                    return;
                }
                
                // Match favorites with properties from allProperties
                const favoritedProperties = [];
                
                for (const favorite of userFavorites) {
                    const propertyId = favorite.property_id;
                    let property = this.state.getProperty(propertyId);
                    
                    if (property) {
                        favoritedProperties.push(property);
                    } else {
                        // If property not found in allProperties, use the summary from favorites
                        const summary = favorite.property_summary || {};
                        favoritedProperties.push({
                            property_id: propertyId,
                            price: summary.price || 1,
                            size_sqm: summary.size_sqm || 0,
                            ward: summary.ward || 'Unknown Ward',
                            closest_station: summary.station || 'Unknown Station',
                            verdict: 'favorited',
                            listing_url: '#',
                            isFallback: true
                        });
                    }
                }
                
                if (this.view) {
                    await this.view.renderFavorites(favoritedProperties);
                }
                
            } catch (error) {
                console.error('Failed to load favorites:', error);
                favoritesList.innerHTML = `<div style="padding:40px; text-align:center; color:#999;">Failed to load favorites: ${error.message}</div>`;
            }
        } else {
            // Anonymous user - use localStorage favorites
            const favoriteProperties = this.state.getFavoriteProperties();
            
            if (favoriteProperties.length === 0) {
                favoritesList.innerHTML = '<div class="favorites-empty">No favorites yet. Click the ♡ on properties to add them here.</div>';
                return;
            }
            
            // Render favorites
            if (this.view) {
                await this.view.renderFavorites(favoriteProperties);
            }
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
    
    async showAnalysis(propertyId) {
        if (!this.state.currentUser) return;
        
        let data = this.state.getFavoriteAnalysis(propertyId);
        if (!data) {
            try {
                data = await this.api.fetchFavoriteAnalysis(this.state.currentUser.email, propertyId);
                this.state.setFavoriteAnalysis(propertyId, data);
            } catch (error) {
                console.error('Failed to load analysis:', error);
                alert('Failed to load analysis. Please try again.');
                return;
            }
        }
        
        this.analysisData = data; // cache for renderAnalysis
        await this.renderAnalysis(); // render immediately
        window.app.router.switchTab('analysis');
    }
    
    async renderAnalysis() {
        if (!this.analysisView || !this.analysisData) return;
        await this.analysisView.render(this.analysisData);
    }
}

// Global functions for backwards compatibility with onclick handlers
function toggleFavorite(propertyId, button) {
    if (window.app && window.app.favorites) {
        window.app.favorites.toggleFavorite(propertyId, button);
    }
}

function removeFavorite(propertyId) {
    if (window.app && window.app.favorites) {
        window.app.favorites.removeFavorite(propertyId);
    }
}