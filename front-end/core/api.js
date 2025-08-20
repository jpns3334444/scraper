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
    
    // Hidden API
    async loadUserHidden(userEmail) {
        const response = await fetch(`${this.favoritesApiUrl}/hidden/user/${userEmail}`, {
            headers: { 
                'X-User-Email': userEmail
            }
        });
        
        if (!response.ok) {
            throw new Error(`Failed to load hidden: ${response.status}`);
        }
        
        const data = await response.json();
        return data.hidden || [];
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
        console.log(`[API] Removing favorite: ${propertyId} for user: ${userEmail}`);
        
        const response = await fetch(`${this.favoritesApiUrl}/favorites/${encodeURIComponent(propertyId)}`, {
            method: 'DELETE',
            headers: { 
                'X-User-Email': userEmail
            }
        });
        
        console.log(`[API] Delete response status: ${response.status}`);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error(`[API] Delete failed: ${response.status} - ${errorText}`);
            throw new Error(`Failed to remove favorite: ${response.status}`);
        }
        
        // Log the successful response
        try {
            const responseData = await response.json();
            console.log(`[API] Delete response data:`, responseData);
            
            // Check if the backend indicates the item was actually deleted
            if (responseData.deleted === false) {
                console.warn(`[API] Backend reported no item was deleted for property ${propertyId}`);
            }
            
            return responseData;
        } catch (parseError) {
            console.warn(`[API] Could not parse delete response as JSON:`, parseError);
            return true; // Assume success if we can't parse the response
        }
    }
    
    async toggleFavorite(propertyId, userEmail, isFavorited) {
        if (isFavorited) {
            return await this.removeFavorite(propertyId, userEmail);
        } else {
            return await this.addFavorite(propertyId, userEmail);
        }
    }
    
    async addHidden(propertyId, userEmail) {
        console.log(`[API] Adding to hidden: ${propertyId} for user: ${userEmail}`);
        
        const response = await fetch(`${this.favoritesApiUrl}/hidden`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-User-Email': userEmail
            },
            body: JSON.stringify({ property_id: propertyId })
        });
        
        if (!response.ok) {
            throw new Error(`Failed to add to hidden: ${response.status}`);
        }
        
        return true;
    }
    
    async removeHidden(propertyId, userEmail) {
        console.log(`[API] Removing from hidden: ${propertyId} for user: ${userEmail}`);
        
        const response = await fetch(`${this.favoritesApiUrl}/hidden/${encodeURIComponent(propertyId)}`, {
            method: 'DELETE',
            headers: { 
                'X-User-Email': userEmail
            }
        });
        
        console.log(`[API] Delete hidden response status: ${response.status}`);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error(`[API] Delete hidden failed: ${response.status} - ${errorText}`);
            throw new Error(`Failed to remove from hidden: ${response.status}`);
        }
        
        return true;
    }
    
    async fetchFavoriteAnalysis(userEmail, propertyId) {
        const url = `${this.favoritesApiUrl}/favorites/analysis/${encodeURIComponent(userEmail)}/${encodeURIComponent(propertyId)}`;
        const response = await fetch(url, {
            headers: { 
                'X-User-Email': userEmail
            }
        });
        
        if (!response.ok) {
            throw new Error(`Failed analysis fetch: ${response.status}`);
        }
        
        const data = await response.json();
        return data; // {analysis_result, property_images, property_summary}
    }
    
    // Comparison API methods
    async compareAllFavorites(userEmail, propertyIds) {
        console.log(`[API] Comparing favorites for user: ${userEmail}, properties: ${propertyIds.length}`);
        
        const response = await fetch(`${this.favoritesApiUrl}/favorites/compare`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-Email': userEmail
            },
            body: JSON.stringify({ 
                property_ids: propertyIds,
                user_email: userEmail
            })
        });
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error(`[API] Compare failed: ${response.status} - ${errorText}`);
            throw new Error(`Failed to compare favorites: ${response.status}`);
        }
        
        const data = await response.json();
        console.log('[API] Compare response:', data);
        return data;
    }
    
    async fetchComparisonAnalysis(userEmail, comparisonId) {
        console.log(`[API] fetchComparisonAnalysis: userEmail=${userEmail}, comparisonId=${comparisonId}`);
        
        const url = `${this.favoritesApiUrl}/favorites/analysis/${encodeURIComponent(userEmail)}/${encodeURIComponent(comparisonId)}`;
        console.log(`[API] fetchComparisonAnalysis URL: ${url}`);
        
        const response = await fetch(url, {
            headers: { 
                'X-User-Email': userEmail
            }
        });
        
        console.log(`[API] fetchComparisonAnalysis response status: ${response.status}`);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error(`[API] fetchComparisonAnalysis failed: ${response.status} - ${errorText}`);
            throw new Error(`Failed comparison analysis fetch: ${response.status} - ${errorText}`);
        }
        
        const data = await response.json();
        console.log(`[API] fetchComparisonAnalysis response data:`, {
            hasAnalysisResult: !!data.analysis_result,
            analysisStatus: data.analysis_status,
            propertyCount: data.property_count,
            comparisonDate: data.comparison_date,
            resultKeys: data.analysis_result ? Object.keys(data.analysis_result) : []
        });
        
        return data; // {analysis_result, comparison_date, property_count}
    }
    
    async removeComparison(comparisonId, userEmail) {
        console.log(`[API] Removing comparison: ${comparisonId} for user: ${userEmail}`);
        
        const response = await fetch(`${this.favoritesApiUrl}/favorites/${encodeURIComponent(comparisonId)}`, {
            method: 'DELETE',
            headers: { 
                'X-User-Email': userEmail
            }
        });
        
        console.log(`[API] Delete comparison response status: ${response.status}`);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error(`[API] Delete comparison failed: ${response.status} - ${errorText}`);
            throw new Error(`Failed to remove comparison: ${response.status}`);
        }
        
        return true;
    }
}