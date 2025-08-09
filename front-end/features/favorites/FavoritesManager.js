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
                        // Merge analysis data from favorite into property
                        property.analysis_status = favorite.analysis_status;
                        property.analysis_result = favorite.analysis_result;
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
                            analysis_status: favorite.analysis_status,
                            analysis_result: favorite.analysis_result,
                            isFallback: true
                        });
                    }
                    
                    // Start polling for properties that are still processing
                    if (!favorite.analysis_result || Object.keys(favorite.analysis_result).length === 0) {
                        this.pollForAnalysisCompletion(propertyId);
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
        
        this.showAnalysisModal(data);
    }
    
    showAnalysisModal(data) {
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
                    
                    <div class="analysis-results">
                        <h3>Investment Analysis</h3>
                        ${this.formatAnalysisResults(data.analysis_result || {})}
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Animate in
        setTimeout(() => modal.classList.add('show'), 10);
    }
    
    formatAnalysisResults(analysis) {
        if (!analysis || typeof analysis !== 'object') {
            return '<p class="no-analysis">Analysis data not available</p>';
        }
        
        // Handle new format with analysis_text
        if (analysis.analysis_text) {
            return this.formatAnalysisText(analysis.analysis_text, analysis.analysis_verdict);
        }
        
        // Backwards compatibility - handle old structured format
        const sections = [];
        
        // Key metrics section
        if (analysis.investment_rating || analysis.final_verdict || analysis.rental_yield_net) {
            sections.push(`
                <div class="analysis-metrics">
                    <h4>Key Metrics</h4>
                    ${analysis.investment_rating ? `<div class="metric"><strong>Investment Rating:</strong> ${analysis.investment_rating}/10</div>` : ''}
                    ${analysis.final_verdict ? `<div class="metric"><strong>Verdict:</strong> ${analysis.final_verdict}</div>` : ''}
                    ${analysis.rental_yield_net ? `<div class="metric"><strong>Net Rental Yield:</strong> ${analysis.rental_yield_net}%</div>` : ''}
                    ${analysis.rental_yield_gross ? `<div class="metric"><strong>Gross Rental Yield:</strong> ${analysis.rental_yield_gross}%</div>` : ''}
                </div>
            `);
        }
        
        // Summary section
        if (analysis.summary) {
            sections.push(`
                <div class="analysis-summary">
                    <h4>Summary</h4>
                    <p>${analysis.summary}</p>
                </div>
            `);
        }
        
        // Financial projections
        if (analysis.price_appreciation_5yr || analysis.renovation_cost_estimate) {
            sections.push(`
                <div class="analysis-financial">
                    <h4>Financial Projections</h4>
                    ${analysis.price_appreciation_5yr ? `<div class="metric"><strong>5-Year Price Appreciation:</strong> ${analysis.price_appreciation_5yr}</div>` : ''}
                    ${analysis.renovation_cost_estimate ? `<div class="metric"><strong>Renovation Cost Estimate:</strong> ${analysis.renovation_cost_estimate}</div>` : ''}
                </div>
            `);
        }
        
        // Risks and considerations
        if (analysis.key_risks && Array.isArray(analysis.key_risks)) {
            sections.push(`
                <div class="analysis-risks">
                    <h4>Key Risks</h4>
                    <ul>
                        ${analysis.key_risks.map(risk => `<li>${risk}</li>`).join('')}
                    </ul>
                </div>
            `);
        }
        
        // Action items
        if (analysis.action_items && Array.isArray(analysis.action_items)) {
            sections.push(`
                <div class="analysis-actions">
                    <h4>Action Items</h4>
                    <ul>
                        ${analysis.action_items.map(item => `<li>${item}</li>`).join('')}
                    </ul>
                </div>
            `);
        }
        
        return sections.length > 0 ? sections.join('') : '<p class="no-analysis">Detailed analysis not available</p>';
    }

    formatAnalysisText(analysisText, verdict) {
        if (!analysisText) {
            return '<p class="no-analysis">Analysis data not available</p>';
        }
        
        let html = '<div class="analysis-text-format">';
        
        // Add verdict badge at the top if available
        if (verdict) {
            const verdictClass = verdict.toLowerCase().replace(/\s+/g, '-');
            html += `<div class="analysis-verdict verdict-${verdictClass}">${verdict}</div>`;
        }
        
        // Split text into paragraphs
        const paragraphs = analysisText.split('\n\n');
        
        paragraphs.forEach(paragraph => {
            if (!paragraph.trim()) return;
            
            // Check for numbered sections (e.g., "1) Overall verdict:")
            const numberedSectionMatch = paragraph.match(/^(\d+)\)\s*([^:]+):\s*(.*)/s);
            if (numberedSectionMatch) {
                const [, number, title, content] = numberedSectionMatch;
                html += `<div class="analysis-section">
                    <h4 class="analysis-section-title">${number}) ${title}</h4>
                    <div class="analysis-section-content">${this.formatParagraphContent(content)}</div>
                </div>`;
                return;
            }
            
            // Check for bullet point sections
            if (paragraph.includes('\n-')) {
                const lines = paragraph.split('\n');
                let currentSection = '';
                let bulletPoints = [];
                
                for (const line of lines) {
                    if (line.trim().startsWith('-')) {
                        bulletPoints.push(line.trim().substring(1).trim());
                    } else if (line.trim()) {
                        if (bulletPoints.length > 0) {
                            // Output previous section with bullets
                            html += `<div class="analysis-section">
                                ${currentSection ? `<h5 class="analysis-subsection-title">${currentSection}</h5>` : ''}
                                <ul class="analysis-bullets">
                                    ${bulletPoints.map(point => `<li>${this.formatInlineContent(point)}</li>`).join('')}
                                </ul>
                            </div>`;
                            bulletPoints = [];
                        }
                        currentSection = line.trim();
                    }
                }
                
                // Handle remaining bullets
                if (bulletPoints.length > 0) {
                    html += `<div class="analysis-section">
                        ${currentSection ? `<h5 class="analysis-subsection-title">${currentSection}</h5>` : ''}
                        <ul class="analysis-bullets">
                            ${bulletPoints.map(point => `<li>${this.formatInlineContent(point)}</li>`).join('')}
                        </ul>
                    </div>`;
                }
                return;
            }
            
            // Regular paragraph
            html += `<div class="analysis-paragraph">${this.formatParagraphContent(paragraph)}</div>`;
        });
        
        html += '</div>';
        return html;
    }
    
    formatParagraphContent(content) {
        // Handle key-value pairs like "Shinjuku: 20 min"
        return content.replace(/([A-Za-z][A-Za-z\s]+):\s*([^,\n]+)/g, 
            '<span class="analysis-key-value"><strong>$1:</strong> $2</span>')
            .replace(/\n/g, '<br>');
    }
    
    formatInlineContent(content) {
        // Handle key-value pairs and emphasis
        return content.replace(/([A-Za-z][A-Za-z\s]+):\s*([^,\n]+)/g, 
            '<span class="analysis-key-value"><strong>$1:</strong> $2</span>');
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