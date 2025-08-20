/**
 * FavoritesManager.js
 * Handles favorites functionality including loading, adding, removing, and syncing with API
 * FIXED: Proper markdown rendering for analysis
 */

class FavoritesManager {
    constructor(api, state) {
        this.api = api;
        this.state = state;
        this.view = null;
        this.markdownLoaded = false;
    }
    
    setView(view) {
        this.view = view;
    }
    
    setViews(favoritesView, analysisView) {
        this.view = favoritesView;
        this.analysisView = analysisView;
    }
    
    // Load markdown library if not already loaded
    async ensureMarkdownLibrary() {
        if (this.markdownLoaded && window.marked) return;
        
        return new Promise((resolve, reject) => {
            if (window.marked) {
                this.markdownLoaded = true;
                resolve();
                return;
            }
            
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js';
            script.onload = () => {
                this.markdownLoaded = true;
                // Configure marked for better rendering
                window.marked.setOptions({
                    breaks: true,
                    gfm: true,
                    tables: true,
                    sanitize: false,
                    pedantic: false,
                    smartLists: true,
                    smartypants: false
                });
                resolve();
            };
            script.onerror = reject;
            document.head.appendChild(script);
        });
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
        console.log('[DEBUG] User authenticated:', !!this.state.currentUser);
        console.log('[DEBUG] All properties count:', this.state.allProperties.length);
        
        const favoritesList = document.getElementById('favoritesList');
        if (!favoritesList) return;
        
        // For authenticated users, we might need to fetch from API and match with properties
        if (this.state.currentUser) {
            try {
                favoritesList.innerHTML = '<div style="padding:40px; text-align:center; color:#999;">Loading favorites...</div>';
                
                const userFavorites = await this.api.loadUserFavorites(this.state.currentUser.email);
                console.log('[DEBUG] Loaded user favorites:', userFavorites.length);
                
                // Separate regular favorites from comparisons
                const regularFavorites = userFavorites.filter(f => !f.property_id.startsWith('COMPARISON_'));
                const comparisonCards = userFavorites.filter(f => f.property_id.startsWith('COMPARISON_'));
                console.log('[DEBUG] Regular favorites:', regularFavorites.length, 'Comparisons:', comparisonCards.length);
                
                // Debug comparison cards
                if (comparisonCards.length > 0) {
                    console.log('[DEBUG] Comparison cards details:');
                    comparisonCards.forEach((card, index) => {
                        console.log(`  ${index + 1}. ID: ${card.property_id}, Status: ${card.analysis_status}, HasResult: ${!!card.analysis_result}, ResultKeys: ${card.analysis_result ? Object.keys(card.analysis_result) : 'none'}`);
                    });
                }
                
                if (regularFavorites.length === 0 && comparisonCards.length === 0) {
                    favoritesList.innerHTML = '<div class="favorites-empty">No favorites yet. Click the ♡ on properties to add them here.</div>';
                    return;
                }
                
                // Match favorites with properties from allProperties
                const favoritedProperties = [];
                let matchedCount = 0;
                let fallbackCount = 0;
                
                for (const favorite of regularFavorites) {
                    const propertyId = favorite.property_id;
                    let property = this.state.getProperty(propertyId);
                    
                    if (property) {
                        // Merge analysis data from favorite into property
                        property.analysis_status = favorite.analysis_status;
                        property.analysis_result = favorite.analysis_result;
                        favoritedProperties.push(property);
                        matchedCount++;
                    } else {
                        // If property not found in allProperties, use the summary from favorites
                        const summary = favorite.property_summary || {};
                        
                        // Try to get original URL from multiple possible sources
                        const originalUrl = favorite.original_listing_url || 
                                          favorite.listing_url || 
                                          summary.listing_url || 
                                          summary.url ||
                                          '#';
                        
                        // Preserve image data if available
                        const imageData = {
                            image_url: favorite.image_url || summary.image_url,
                            image_key: favorite.image_key || summary.image_key,
                            image_s3_key: favorite.image_s3_key || summary.image_s3_key
                        };
                        
                        console.log(`[DEBUG] Creating fallback property for ${propertyId} with URL: ${originalUrl}`);
                        
                        favoritedProperties.push({
                            property_id: propertyId,
                            price: summary.price || 1,
                            size_sqm: summary.size_sqm || 0,
                            ward: summary.ward || 'Unknown Ward',
                            closest_station: summary.station || 'Unknown Station',
                            verdict: 'favorited',
                            listing_url: originalUrl,
                            analysis_status: favorite.analysis_status,
                            analysis_result: favorite.analysis_result,
                            isFallback: true,
                            ...imageData
                        });
                        fallbackCount++;
                    }
                    
                    // Start polling for properties that are still processing
                    if (!favorite.analysis_result || Object.keys(favorite.analysis_result).length === 0) {
                        this.pollForAnalysisCompletion(propertyId);
                    }
                }
                
                console.log(`[DEBUG] Favorites processing complete - Matched: ${matchedCount}, Fallback: ${fallbackCount}, Total: ${favoritedProperties.length}`);
                
                if (this.view) {
                    await this.view.renderFavorites(favoritedProperties, comparisonCards);
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
            
            // Render favorites (no comparisons for anonymous users)
            if (this.view) {
                await this.view.renderFavorites(favoriteProperties, []);
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
    
    async processAnalysis(propertyId) {
        if (!this.state.currentUser) {
            alert('Please login to process analysis');
            return;
        }
        
        try {
            // Update UI to show processing state
            const processBtn = document.querySelector(`[data-property-id="${propertyId}"] .process-button`);
            if (processBtn) {
                processBtn.disabled = true;
                processBtn.textContent = 'Processing';
                processBtn.classList.remove('pending');
                processBtn.classList.add('processing');
            }
            
            // Trigger analysis by re-adding the favorite (which triggers the analyzer Lambda)
            const response = await fetch(`${this.api.favoritesApiUrl}/favorites`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-User-Email': this.state.currentUser.email
                },
                body: JSON.stringify({ property_id: propertyId })
            });
            
            if (!response.ok) {
                throw new Error(`Failed to trigger analysis: ${response.status}`);
            }
            
            // Poll for completion
            this.pollForAnalysisCompletion(propertyId);
            
        } catch (error) {
            console.error('Failed to trigger analysis:', error);
            alert('Failed to start analysis. Please try again.');
            
            // Reset button state
            const processBtn = document.querySelector(`[data-property-id="${propertyId}"] .process-button`);
            if (processBtn) {
                processBtn.disabled = false;
                processBtn.textContent = 'Process';
                processBtn.classList.remove('processing');
                processBtn.classList.add('pending');
            }
        }
    }
    
    async pollForAnalysisCompletion(propertyId, attempts = 0) {
        const maxAttempts = 30; // 30 attempts = 5 minutes max
        
        if (attempts >= maxAttempts) {
            console.log('Analysis polling timed out');
            return;
        }
        
        try {
            const data = await this.api.fetchFavoriteAnalysis(this.state.currentUser.email, propertyId);
            
            if (data.analysis_result && Object.keys(data.analysis_result).length > 0) {
                // Analysis completed, update UI
                const statusButton = document.querySelector(`[data-property-id="${propertyId}"] .processing-status`);
                if (statusButton) {
                    statusButton.classList.remove('processing');
                    statusButton.classList.add('processed');
                    statusButton.textContent = 'Processed';
                    statusButton.disabled = false;
                    statusButton.setAttribute('onclick', `window.app.favorites.showAnalysisPopup('${propertyId}'); event.stopPropagation();`);
                    statusButton.style.cursor = 'pointer';
                    statusButton.setAttribute('title', 'View Analysis');
                }
                
                // Cache the data
                this.state.setFavoriteAnalysis(propertyId, data);
                return;
            }
            
            // Continue polling
            setTimeout(() => this.pollForAnalysisCompletion(propertyId, attempts + 1), 10000); // Poll every 10 seconds
            
        } catch (error) {
            console.error('Error polling for analysis completion:', error);
            // Continue polling on error
            setTimeout(() => this.pollForAnalysisCompletion(propertyId, attempts + 1), 10000);
        }
    }

    async showAnalysisPopup(propertyId) {
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
        
        await this.showAnalysisModal(data);
    }
    
    async showAnalysisModal(data) {
        // Ensure markdown library is loaded
        await this.ensureMarkdownLibrary();
        
        // Create modal overlay
        const modal = document.createElement('div');
        modal.className = 'analysis-modal-overlay';
        modal.onclick = (e) => {
            if (e.target === modal) {
                document.body.removeChild(modal);
            }
        };
        
        // Format property images
        const images = (data.property_images || []).map(url => 
            `<img src="${url}" class="analysis-modal-img" alt="Property image">`
        ).join('');
        
        // Format property summary
        const summary = data.property_summary || {};
        const price = summary.price ? `¥${(summary.price * 10000).toLocaleString()}` : 'N/A';
        const size = summary.size_sqm ? `${Math.round(summary.size_sqm)}m²` : 'N/A';
        
        // Get the markdown content
        const analysis = data.analysis_result || {};
        const markdownContent = analysis.analysis_markdown || analysis.analysis_text || '';
        
        // Render markdown to HTML
        let renderedContent = '';
        if (markdownContent && window.marked) {
            try {
                // Clean up the markdown content first
                let cleanedMarkdown = markdownContent;
                
                // Fix common markdown issues
                // 1. Ensure proper spacing around headers
                cleanedMarkdown = cleanedMarkdown.replace(/^(#{1,6})\s*/gm, '$1 ');
                
                // 2. Fix table formatting issues (ensure pipes are properly spaced)
                cleanedMarkdown = cleanedMarkdown.replace(/\|([^|]+)\|/g, (match, content) => {
                    return '| ' + content.trim() + ' |';
                });
                
                // 3. Ensure blank lines around tables for proper parsing
                cleanedMarkdown = cleanedMarkdown.replace(/(\n)(\|[^\n]+\|)/g, '$1\n$2');
                cleanedMarkdown = cleanedMarkdown.replace(/(\|[^\n]+\|)(\n)/g, '$1\n$2');
                
                // Parse markdown to HTML
                renderedContent = marked.parse(cleanedMarkdown);
                
                // Post-process the HTML to add styling classes
                renderedContent = renderedContent
                    .replace(/<table>/g, '<table class="analysis-table">')
                    .replace(/<h2>/g, '<h2 class="analysis-section-header">')
                    .replace(/<h3>/g, '<h3 class="analysis-subsection-header">')
                    .replace(/<ul>/g, '<ul class="analysis-list">')
                    .replace(/<strong>/g, '<strong class="analysis-emphasis">');
                    
            } catch (error) {
                console.error('Markdown parsing error:', error);
                // Fallback to displaying raw markdown
                renderedContent = `<pre style="white-space: pre-wrap; font-family: inherit;">${markdownContent}</pre>`;
            }
        } else {
            // Fallback if no markdown library or content
            renderedContent = this.formatAnalysisResults(analysis);
        }
        
        modal.innerHTML = `
            <div class="analysis-modal">
                <div class="analysis-modal-header">
                    <h2>Property Analysis</h2>
                    <button class="analysis-modal-close" onclick="document.body.removeChild(this.closest('.analysis-modal-overlay'))">&times;</button>
                    <div class="property-basic-info">
                        <span class="property-ward">${summary.ward || 'Unknown Ward'}</span>
                        <span class="property-price">${price}</span>
                        <span class="property-size">${size}</span>
                    </div>
                </div>
                
                <div class="analysis-modal-content">
                    <div class="analysis-images">
                        ${images}
                    </div>
                    
                    <div class="analysis-results analysis-markdown-content">
                        ${renderedContent}
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Animate in
        setTimeout(() => modal.classList.add('show'), 10);
    }
    
    formatAnalysisResults(analysis) {
        // Fallback formatting when markdown is not available
        if (!analysis || typeof analysis !== 'object') {
            return '<p class="no-analysis">Analysis data not available</p>';
        }
        
        // Handle both markdown and structured format
        if (analysis.analysis_markdown || analysis.analysis_text) {
            const text = analysis.analysis_markdown || analysis.analysis_text;
            // Basic text to HTML conversion
            return `<div class="analysis-text-fallback">${text.replace(/\n/g, '<br>')}</div>`;
        }
        
        // Legacy structured format handling
        const sections = [];
        
        if (analysis.investment_rating || analysis.final_verdict || analysis.rental_yield_net) {
            sections.push(`
                <div class="analysis-metrics">
                    <h4>Key Metrics</h4>
                    ${analysis.investment_rating ? `<div class="metric"><strong>Investment Rating:</strong> ${analysis.investment_rating}/10</div>` : ''}
                    ${analysis.final_verdict ? `<div class="metric"><strong>Verdict:</strong> ${analysis.final_verdict}</div>` : ''}
                    ${analysis.rental_yield_net ? `<div class="metric"><strong>Net Rental Yield:</strong> ${analysis.rental_yield_net}%</div>` : ''}
                </div>
            `);
        }
        
        return sections.length > 0 ? sections.join('') : '<p class="no-analysis">Detailed analysis not available</p>';
    }
    
    async renderAnalysis() {
        if (!this.analysisView || !this.analysisData) return;
        await this.analysisView.render(this.analysisData);
    }
    
    async compareAllFavorites() {
        if (!this.state.currentUser) {
            alert('Please login to compare favorites');
            return;
        }
        
        try {
            // Get all analyzed favorites
            const userFavorites = await this.api.loadUserFavorites(this.state.currentUser.email);
            const regularFavorites = userFavorites.filter(f => 
                !f.property_id.startsWith('COMPARISON_') &&
                (f.analysis_status === 'completed' || (f.analysis_result && Object.keys(f.analysis_result).length > 0))
            );
            
            if (regularFavorites.length < 2) {
                alert('You need at least 2 analyzed favorites to compare.');
                return;
            }
            
            // Update button state
            const compareBtn = document.getElementById('compareAllFavoritesBtn');
            if (compareBtn) {
                compareBtn.disabled = true;
                compareBtn.textContent = 'COMPARING...';
            }
            
            // Extract property IDs
            const propertyIds = regularFavorites.map(f => f.property_id);
            
            // Call comparison API (now async)
            const result = await this.api.compareAllFavorites(this.state.currentUser.email, propertyIds);
            console.log('Comparison initiated:', result);
            
            // Refresh favorites to show new comparison card with processing status
            await this.loadFavorites();
            
            // Start polling for completion if we have a comparison ID
            if (result.comparison_id) {
                this.pollForComparisonCompletion(result.comparison_id);
            }
            
        } catch (error) {
            console.error('Failed to compare favorites:', error);
            alert('Failed to compare favorites. Please try again.');
        } finally {
            // Reset button state
            const compareBtn = document.getElementById('compareAllFavoritesBtn');
            if (compareBtn) {
                compareBtn.disabled = false;
                // Button text will be reset when favorites reload
            }
        }
    }
    
    async showComparisonResults(comparisonId) {
        if (!this.state.currentUser) return;
        
        console.log(`[DEBUG] showComparisonResults called with comparisonId: ${comparisonId}`);
        
        try {
            const data = await this.api.fetchComparisonAnalysis(this.state.currentUser.email, comparisonId);
            console.log(`[DEBUG] fetchComparisonAnalysis returned:`, {
                hasData: !!data,
                status: data?.analysis_status,
                hasResult: !!data?.analysis_result,
                resultType: typeof data?.analysis_result,
                resultKeys: data?.analysis_result ? Object.keys(data.analysis_result) : [],
                propertyCount: data?.property_count
            });
            
            if (!data.analysis_result || Object.keys(data.analysis_result).length === 0) {
                console.warn(`[DEBUG] Comparison ${comparisonId} has no analysis result yet`);
                alert('Comparison analysis is not ready yet. Please wait for processing to complete.');
                return;
            }
            
            await this.showComparisonModal(data);
        } catch (error) {
            console.error(`[ERROR] Failed to load comparison results for ${comparisonId}:`, error);
            alert(`Failed to load comparison results: ${error.message}. Please try again.`);
        }
    }
    
    async showComparisonModal(data) {
        // Ensure markdown library is loaded
        await this.ensureMarkdownLibrary();
        
        // Create modal overlay
        const modal = document.createElement('div');
        modal.className = 'analysis-modal-overlay';
        modal.onclick = (e) => {
            if (e.target === modal) {
                document.body.removeChild(modal);
            }
        };
        
        // Get the comparison analysis
        const analysis = data.analysis_result || {};
        const markdownContent = analysis.analysis_markdown || analysis.analysis_text || '';
        
        // Format comparison metadata
        const comparisonDate = new Date(data.comparison_date || data.created_at || Date.now());
        const formattedDate = comparisonDate.toLocaleDateString('en-US', { 
            year: 'numeric',
            month: 'long', 
            day: 'numeric',
            hour: '2-digit', 
            minute: '2-digit' 
        });
        const propertyCount = data.property_count || 
                              (data.property_summary && data.property_summary.property_count) || 0;
        
        // Render markdown to HTML
        let renderedContent = '';
        if (markdownContent && window.marked) {
            try {
                // Clean up the markdown content first
                let cleanedMarkdown = markdownContent;
                
                // Fix common markdown issues
                cleanedMarkdown = cleanedMarkdown.replace(/^(#{1,6})\s*/gm, '$1 ');
                cleanedMarkdown = cleanedMarkdown.replace(/\|([^|]+)\|/g, (match, content) => {
                    return '| ' + content.trim() + ' |';
                });
                cleanedMarkdown = cleanedMarkdown.replace(/(\n)(\|[^\n]+\|)/g, '$1\n$2');
                cleanedMarkdown = cleanedMarkdown.replace(/(\|[^\n]+\|)(\n)/g, '$1\n$2');
                
                // Parse markdown to HTML
                renderedContent = marked.parse(cleanedMarkdown);
                
                // Post-process the HTML to add styling classes
                renderedContent = renderedContent
                    .replace(/<table>/g, '<table class="analysis-table">')
                    .replace(/<h2>/g, '<h2 class="analysis-section-header">')
                    .replace(/<h3>/g, '<h3 class="analysis-subsection-header">')
                    .replace(/<ul>/g, '<ul class="analysis-list">')
                    .replace(/<strong>/g, '<strong class="analysis-emphasis">');
                    
            } catch (error) {
                console.error('Markdown parsing error:', error);
                // Fallback to displaying raw markdown
                renderedContent = `<pre style="white-space: pre-wrap; font-family: inherit;">${markdownContent}</pre>`;
            }
        } else {
            // Fallback if no markdown library or content
            renderedContent = '<p class="no-analysis">Comparison analysis not available</p>';
        }
        
        modal.innerHTML = `
            <div class="analysis-modal">
                <div class="analysis-modal-header">
                    <h2>📊 Favorite Comparison Results</h2>
                    <button class="analysis-modal-close" onclick="document.body.removeChild(this.closest('.analysis-modal-overlay'))">&times;</button>
                    <div class="property-basic-info">
                        <span class="comparison-date">${formattedDate}</span>
                        <span class="comparison-count">${propertyCount} Properties Compared</span>
                    </div>
                </div>
                
                <div class="analysis-modal-content">
                    <div class="analysis-results analysis-markdown-content">
                        ${renderedContent}
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Animate in
        setTimeout(() => modal.classList.add('show'), 10);
    }
    
    async pollForComparisonCompletion(comparisonId, attempts = 0) {
        const maxAttempts = 60; // 60 attempts = 10 minutes max
        
        if (attempts >= maxAttempts) {
            console.log(`[DEBUG] Comparison ${comparisonId} polling timed out after ${maxAttempts} attempts`);
            return;
        }
        
        try {
            console.log(`[DEBUG] Polling comparison ${comparisonId}, attempt ${attempts + 1}/${maxAttempts}`);
            const data = await this.api.fetchComparisonAnalysis(this.state.currentUser.email, comparisonId);
            
            console.log(`[DEBUG] Comparison ${comparisonId} polling result:`, {
                status: data.analysis_status,
                hasResult: !!data.analysis_result,
                resultKeys: data.analysis_result ? Object.keys(data.analysis_result) : [],
                resultSize: data.analysis_result ? Object.keys(data.analysis_result).length : 0
            });
            
            // Check if comparison is completed - be more flexible with the check
            const hasAnalysisResult = data.analysis_result && 
                                     (typeof data.analysis_result === 'object' ? 
                                      Object.keys(data.analysis_result).length > 0 : 
                                      data.analysis_result.length > 0);
            
            if (hasAnalysisResult && data.analysis_status === 'completed') {
                // Comparison completed, refresh favorites to show updated card
                console.log(`[SUCCESS] Comparison ${comparisonId} completed, refreshing favorites`);
                await this.loadFavorites();
                return;
            }
            
            // Check if failed
            if (data.analysis_status === 'failed') {
                console.log(`[ERROR] Comparison ${comparisonId} failed:`, data.last_error || 'Unknown error');
                await this.loadFavorites(); // Refresh to show failed state
                return;
            }
            
            // Continue polling if still processing or pending
            console.log(`[DEBUG] Comparison ${comparisonId} still ${data.analysis_status || 'pending'}, continuing to poll...`);
            setTimeout(() => this.pollForComparisonCompletion(comparisonId, attempts + 1), 10000); // Poll every 10 seconds
            
        } catch (error) {
            console.log(`[DEBUG] Comparison ${comparisonId} polling error (attempt ${attempts + 1}):`, error.message);
            // Continue polling on error (comparison might not be ready yet)
            setTimeout(() => this.pollForComparisonCompletion(comparisonId, attempts + 1), 10000);
        }
    }

    async removeComparison(comparisonId) {
        if (!this.state.currentUser) return;
        
        try {
            await this.api.removeComparison(comparisonId, this.state.currentUser.email);
            
            // Animate removal
            const card = document.querySelector(`.comparison-card[data-comparison-id="${comparisonId}"]`);
            if (card) {
                card.style.transition = 'all 0.3s';
                card.style.opacity = '0';
                card.style.transform = 'translateX(-100%)';
                setTimeout(() => {
                    card.remove();
                }, 300);
            }
        } catch (error) {
            console.error('Failed to remove comparison:', error);
            alert('Failed to remove comparison. Please try again.');
        }
    }
    
    async moveToHidden(propertyId) {
        try {
            // First remove from favorites
            if (this.state.currentUser) {
                await this.api.removeFavorite(propertyId, this.state.currentUser.email);
            }
            this.state.removeFavorite(propertyId);
            this.saveFavoritesToStorage();
            
            // Then add to hidden
            if (this.state.currentUser) {
                await this.api.addHidden(propertyId, this.state.currentUser.email);
            }
            this.state.addHidden(propertyId);
            
            // Save hidden to localStorage for anonymous users
            if (!this.state.currentUser) {
                StorageManager.saveHidden(this.state.hidden);
            }
            
            // Update both counts
            this.updateFavoritesCount();
            if (window.app.hidden) {
                window.app.hidden.updateHiddenCount();
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
                        const container = document.querySelector('.favorites-container');
                        if (container) {
                            container.innerHTML = '<div style="padding:40px; text-align:center; color:#999;">No favorites yet</div>';
                        }
                    }
                }, 300);
            }
            
        } catch (error) {
            console.error('Failed to move property to hidden:', error);
            alert('Failed to move property to hidden. Please try again.');
        }
    }
    
    // Debug function for troubleshooting favorites issues
    debugFavorites() {
        console.log('=== FAVORITES DEBUG REPORT ===');
        console.log('1. User authenticated:', !!this.state.currentUser);
        console.log('2. Current favorites count:', this.state.favorites.size);
        console.log('3. All properties loaded:', this.state.allProperties.length);
        console.log('4. Visible favorite cards:', document.querySelectorAll('.favorite-card').length);
        
        // Check for cards with invalid URLs
        const cards = document.querySelectorAll('.favorite-card');
        let invalidUrlCount = 0;
        let noImageCount = 0;
        
        cards.forEach(card => {
            const hasValidUrl = card.getAttribute('onclick') && !card.getAttribute('onclick').includes('#');
            const hasImage = !card.querySelector('.no-image');
            
            if (!hasValidUrl) invalidUrlCount++;
            if (!hasImage) noImageCount++;
        });
        
        console.log('5. Cards with invalid URLs:', invalidUrlCount);
        console.log('6. Cards with no images:', noImageCount);
        console.log('7. Recent console errors related to favorites:');
        
        // Log any recent favorites-related console messages
        const recentLogs = console.memory || 'Console history not available';
        console.log('=== END DEBUG REPORT ===');
        
        return {
            authenticated: !!this.state.currentUser,
            favoritesCount: this.state.favorites.size,
            propertiesLoaded: this.state.allProperties.length,
            visibleCards: cards.length,
            invalidUrls: invalidUrlCount,
            noImages: noImageCount
        };
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