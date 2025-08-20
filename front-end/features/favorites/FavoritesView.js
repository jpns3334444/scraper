/**
 * FavoritesView.js
 * Minimal Sumi-e style favorites rendering - only ward, price, size, and status
 */

class FavoritesView {
    async renderFavorites(favoriteProperties, comparisonCards = []) {
        const favoritesList = document.getElementById('favoritesList');
        if (!favoritesList) return;
        
        // Sort by price descending
        favoriteProperties.sort((a, b) => (b.price || 0) - (a.price || 0));
        
        // Count properties with completed analysis for comparison button
        const completedAnalysis = favoriteProperties.filter(p => 
            p.analysis_status === 'completed' || 
            (p.analysis_result && Object.keys(p.analysis_result).length > 0)
        );
        
        let content = '';
        
        // Add comparison section (button + cards) if needed
        if (completedAnalysis.length >= 2 || (comparisonCards && comparisonCards.length > 0)) {
            content += await this.renderComparisonSection(completedAnalysis.length, comparisonCards);
        }
        
        // Generate card HTML for each property (with async image loading)
        const cardPromises = favoriteProperties.map(property => this.renderFavoriteCard(property));
        const cards = await Promise.all(cardPromises);
        content += cards.join('');
        
        favoritesList.innerHTML = content;
    }
    
    async renderComparisonSection(analyzedCount, comparisonCards = []) {
        let sectionContent = '';
        
        // Add compare button if there are 2+ analyzed properties
        if (analyzedCount >= 2) {
            sectionContent += `
                <button id="compareAllFavoritesBtn" class="compare-all-btn" onclick="window.app.favorites.compareAllFavorites()" title="Compare all analyzed properties">
                    Compare All (${analyzedCount})
                </button>`;
        }
        
        // Add comparison cards if they exist
        if (comparisonCards && comparisonCards.length > 0) {
            const sortedComparisons = comparisonCards.sort((a, b) => 
                new Date(b.comparison_date || b.created_at || 0) - new Date(a.comparison_date || a.created_at || 0)
            );
            const comparisonCardsHtml = await Promise.all(
                sortedComparisons.map(card => this.renderComparisonCard(card))
            );
            sectionContent += comparisonCardsHtml.join('');
        }
        
        return `<div class="comparison-section">${sectionContent}</div>`;
    }
    
    async renderComparisonCard(comparisonData) {
        const comparisonDate = new Date(comparisonData.comparison_date || comparisonData.created_at || Date.now());
        const formattedDate = comparisonDate.toLocaleDateString('en-US', { 
            month: 'short', 
            day: 'numeric'
        });
        const propertyCount = comparisonData.property_count || 
                              (comparisonData.property_summary && comparisonData.property_summary.property_count) || 0;
        
        // Fixed: Always use property_id for comparisons since that's how they're stored in DynamoDB
        const comparisonId = comparisonData.property_id;
        
        console.log(`[DEBUG] Rendering comparison card: ID=${comparisonId}, status=${comparisonData.analysis_status}, hasResult=${!!comparisonData.analysis_result}`);
        
        // Check if comparison is completed - be more flexible with the checks
        const hasAnalysisResult = comparisonData.analysis_result && 
                                 (typeof comparisonData.analysis_result === 'object' ? 
                                  Object.keys(comparisonData.analysis_result).length > 0 : 
                                  comparisonData.analysis_result.length > 0);
        const isCompleted = comparisonData.analysis_status === 'completed' && hasAnalysisResult;
        const isProcessing = comparisonData.analysis_status === 'processing';
        const isFailed = comparisonData.analysis_status === 'failed';
        
        const statusClass = isCompleted ? 'processed' : isProcessing ? 'processing' : 'failed';
        const statusText = isCompleted ? 'View' : isProcessing ? 'Processing...' : isFailed ? 'Failed' : 'Pending';
        const titleText = isCompleted ? 'Results' : isProcessing ? 'Processing' : 'Results';
        const clickable = isCompleted;
        
        return `
            <div class="comparison-card" data-comparison-id="${comparisonId}" ${clickable ? `onclick="window.app.favorites.showComparisonResults('${comparisonId}'); event.stopPropagation();" style="cursor: pointer;"` : 'style="cursor: default;"'}>
                <div class="comparison-icon">📊</div>
                <div class="comparison-details">
                    <div class="comparison-title">${titleText}</div>
                    <div class="comparison-meta">${formattedDate} • ${propertyCount}</div>
                </div>
                <button class="comparison-status ${statusClass}" title="${isCompleted ? 'View Comparison Results' : statusText}" ${!clickable ? 'disabled' : ''}>${statusText}</button>
                <button class="remove-comparison-btn" onclick="event.stopPropagation(); window.app.favorites.removeComparison('${comparisonId}')" title="Remove comparison">
                    <svg width="10" height="10" viewBox="0 0 12 12">
                        <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" stroke-width="1.5"/>
                    </svg>
                </button>
            </div>`;
    }
    
    async renderFavoriteCard(property) {
        // Extract only the data we need
        const ward = property.ward || '—';
        const price = property.price ? `¥${(property.price * 10000).toLocaleString()}` : '—';
        const size = property.size_sqm || property.total_sqm ? 
            `${Math.round(property.size_sqm || property.total_sqm)}m²` : '—';
        
        // URL validation - check if we have a valid URL
        const url = property.listing_url || '#';
        const hasValidUrl = url !== '#' && url && url.startsWith('http');
        
        // Debug logging for URL issues
        if (property.isFallback && !hasValidUrl) {
            console.warn(`[DEBUG] Fallback property ${property.property_id} has invalid URL: ${url}`);
        }
        
        // Get property image
        const imageUrl = await this.getPropertyImage(property);
        const imageHtml = imageUrl ? 
            `<img src="${imageUrl}" alt="Property image" onerror="this.parentElement.classList.add('no-image'); this.parentElement.innerHTML='No Image';">` : 
            '<div class="no-image">No Image</div>';
        
        // Determine processing status - Since analysis starts automatically when favorited, default to processing
        let statusClass = 'processing';
        let statusText = 'Processing';
        let isClickable = false;
        
        if (property.analysis_status === 'completed' || (property.analysis_result && Object.keys(property.analysis_result).length > 0)) {
            statusClass = 'processed';
            statusText = 'Processed';
            isClickable = true;
        } else if (property.analysis_status === 'failed') {
            statusClass = 'failed';
            statusText = 'Failed';
        }
        // Default is already 'processing' for pending or processing states
        
        // Card with image on left, essential information
        // Only make clickable if we have a valid URL
        const cardClickable = hasValidUrl ? `onclick="openListing(event, '${url}')" style="cursor: pointer;"` : 'style="cursor: default;" title="Original listing not available"';
        
        return `
            <div class="favorite-card" data-property-id="${property.property_id}" ${cardClickable}>
                <div class="favorite-image-section">
                    ${imageHtml}
                </div>
                <div class="favorite-details-section">
                    <div class="favorite-ward">${ward}</div>
                    <div class="favorite-price">${price}</div>
                    <div class="favorite-size">${size}</div>
                </div>
                <button class="processing-status ${statusClass}" 
                    ${isClickable ? `onclick="window.app.favorites.showAnalysisPopup('${property.property_id}'); event.stopPropagation();"` : 'disabled'}
                    ${isClickable ? 'style="cursor: pointer;"' : ''}
                    title="${isClickable ? 'View Analysis' : statusText}">${statusText}</button>
                <button class="move-to-hidden-btn" onclick="event.stopPropagation(); window.app.favorites.moveToHidden('${property.property_id}')" title="Move to hidden">
                    <svg width="14" height="14" viewBox="0 0 14 14">
                        <path d="M7 2.5C4 2.5 1.5 5 1.5 7s2.5 4.5 5.5 4.5 5.5-2.5 5.5-4.5S10 2.5 7 2.5z" stroke="currentColor" stroke-width="1.2" fill="none"/>
                        <path d="M2 2L12 12" stroke="currentColor" stroke-width="1.2"/>
                    </svg>
                </button>
                <button class="remove-favorite-btn" onclick="event.stopPropagation(); removeFavorite('${property.property_id}')" title="Remove from favorites">
                    <svg width="12" height="12" viewBox="0 0 12 12">
                        <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" stroke-width="1.5"/>
                    </svg>
                </button>
            </div>`;
    }
    
    async getPropertyImage(property) {
        // Debug logging for fallback properties
        if (property.isFallback) {
            console.log(`[DEBUG] Getting image for fallback property ${property.property_id}:`, {
                image_url: property.image_url,
                image_key: property.image_key,
                image_s3_key: property.image_s3_key
            });
        }
        
        // Check if property has image_url field
        if (property.image_url) {
            return property.image_url;
        } else if (property.image_key || property.image_s3_key) {
            // Generate pre-signed URL via API
            try {
                const response = await fetch(`${API_URL}/properties/${property.property_id}/image-url`);
                if (response.ok) {
                    const data = await response.json();
                    return data.presigned_url || data.image_url;
                } else {
                    console.warn(`Failed to fetch image URL for ${property.property_id}: ${response.status}`);
                }
            } catch (error) {
                console.error(`Failed to get image URL for ${property.property_id}:`, error);
            }
        } else if (property.isFallback) {
            console.log(`[DEBUG] No image data available for fallback property ${property.property_id}`);
        }
        return null;
    }
}