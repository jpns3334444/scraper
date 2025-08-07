/**
 * api.js
 * API class for handling all backend communication
 */

class PropertyAPI {
    constructor(apiUrl, favoritesApiUrl) {
        this.apiUrl = apiUrl;
        this.favoritesApiUrl = favoritesApiUrl;
    }
    
    // Properties API
    async fetchPropertiesPage(cursor, limit = DEFAULT_LIMIT) {
        const url = `${this.apiUrl}/properties?limit=${limit}` +
                    (cursor ? `&cursor=${encodeURIComponent(JSON.stringify(cursor))}` : '');
        
        const res = await fetch(url, { 
            headers: { 'X-User-Id': StorageManager.getUserId() }
        });
        
        if (!res.ok) {
            console.error('Failed page:', await res.text());
            throw new Error(`Backend returned ${res.status}`);
        }
        
        const data = await res.json();
        // Map API's cursor field to nextCursor for frontend compatibility
        return {
            items: data.items,
            nextCursor: data.cursor || false
        };
    }
    
    async fetchPropertyImageUrl(propertyId) {
        try {
            const response = await fetch(`${this.apiUrl}/properties/${propertyId}/image-url`);
            if (response.ok) {
                const data = await response.json();
                return data.image_url;
            }
        } catch (error) {
            console.error('Failed to fetch image URL:', error);
        }
        return null;
    }
    
    // Authentication API
    async loginUser(email, password) {
        const response = await fetch(this.favoritesApiUrl + '/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        
        const data = await response.json();
        return data;
    }
    
    async registerUser(email, password) {
        const response = await fetch(this.favoritesApiUrl + '/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        
        const data = await response.json();
        return data;
    }
    
    // Favorites API
    async loadUserFavorites(userEmail) {
        const response = await fetch(`${this.favoritesApiUrl}/favorites/user/${userEmail}`, {
            headers: { 
                'X-User-Email': userEmail
            }
        });
        
        if (!response.ok) {
            throw new Error(`Failed to load favorites: ${response.status}`);
        }
        
        const data = await response.json();
        return data.favorites || [];
    }
    
    async addFavorite(propertyId, userEmail) {
        const response = await fetch(`${this.favoritesApiUrl}/favorites`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-Email': userEmail
            },
            body: JSON.stringify({ property_id: propertyId })
        });
        
        if (!response.ok) {
            throw new Error(`Failed to add favorite: ${response.status}`);
        }
        
        return true;
    }
    
    async removeFavorite(propertyId, userEmail) {
        const response = await fetch(`${this.favoritesApiUrl}/favorites/${propertyId}`, {
            method: 'DELETE',
            headers: { 
                'X-User-Email': userEmail
            }
        });
        
        if (!response.ok) {
            throw new Error(`Failed to remove favorite: ${response.status}`);
        }
        
        return true;
    }
    
    async toggleFavorite(propertyId, userEmail, isFavorited) {
        if (isFavorited) {
            return await this.removeFavorite(propertyId, userEmail);
        } else {
            return await this.addFavorite(propertyId, userEmail);
        }
    }
}