/**
 * AnalysisView.js
 * Renders property analysis results with images and LLM analysis
 */

class AnalysisView {
    async render(data) {
        const container = document.getElementById('analysisContent');
        if (!container) return;
        
        // Format property images
        const images = (data.property_images || []).map(url => 
            `<img src="${url}" class="analysis-img" alt="Property image">`
        ).join('');
        
        // Format analysis result
        const analysisResult = data.analysis_result || {};
        const analysisJson = JSON.stringify(analysisResult, null, 2);
        
        // Format property summary
        const summary = data.property_summary || {};
        const price = summary.price ? `¥${(summary.price * 10000).toLocaleString()}` : 'N/A';
        const size = summary.size_sqm ? `${Math.round(summary.size_sqm)}m²` : 'N/A';
        
        container.innerHTML = `
            <div class="analysis-container">
                <div class="analysis-header">
                    <h2>Property Analysis</h2>
                    <div class="property-basic-info">
                        <span class="property-ward">${summary.ward || 'Unknown Ward'}</span>
                        <span class="property-price">${price}</span>
                        <span class="property-size">${size}</span>
                    </div>
                </div>
                
                <div class="analysis-images">
                    ${images}
                </div>
                
                <div class="analysis-results">
                    <h3>Investment Analysis</h3>
                    ${this.formatAnalysisResults(analysisResult)}
                </div>
                
                <div class="analysis-raw">
                    <details>
                        <summary>Raw Analysis Data</summary>
                        <pre class="analysis-json">${analysisJson}</pre>
                    </details>
                </div>
            </div>
        `;
    }
    
    formatAnalysisResults(analysis) {
        if (!analysis || typeof analysis !== 'object') {
            return '<p class="no-analysis">Analysis data not available</p>';
        }
        
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
        
        // Market comparison
        if (analysis.market_comparison) {
            sections.push(`
                <div class="analysis-market">
                    <h4>Market Comparison</h4>
                    <p>${analysis.market_comparison}</p>
                </div>
            `);
        }
        
        // Exit strategy
        if (analysis.exit_strategy) {
            sections.push(`
                <div class="analysis-exit">
                    <h4>Exit Strategy</h4>
                    <p>${analysis.exit_strategy}</p>
                </div>
            `);
        }
        
        return sections.length > 0 ? sections.join('') : '<p class="no-analysis">Detailed analysis not available</p>';
    }
}