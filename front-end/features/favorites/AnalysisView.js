/**
 * AnalysisView.js
 * Renders property analysis results with images and LLM analysis
 */

class AnalysisView {
    async ensureMarkdownLibs() {
        function load(src) {
            return new Promise((res, rej) => {
                const s = document.createElement('script');
                s.src = src;
                s.onload = res; 
                s.onerror = rej;
                document.head.appendChild(s);
            });
        }
        if (!window.marked) await load('https://cdn.jsdelivr.net/npm/marked/marked.min.js');
        if (!window.DOMPurify) await load('https://cdn.jsdelivr.net/npm/dompurify@3.1.7/dist/purify.min.js');
        
        // Configure marked for better GFM support
        if (window.marked && !window.marked._configured) {
            window.marked.setOptions({ 
                gfm: true, 
                headerIds: false, 
                mangle: false, 
                breaks: false 
            });
            window.marked._configured = true;
        }
    }

    preprocessMarkdown(md) {
        if (!md) return '';
        // Protect fenced code blocks
        const blocks = [];
        const placeholder = i => `__CODE_BLOCK_${i}__`;
        md = md.replace(/```[\s\S]*?```/g, m => { blocks.push(m); return placeholder(blocks.length - 1); });

        // Normalize line endings
        md = md.replace(/\r\n?/g, '\n');

        // Remove uniform leading indentation on non-empty lines
        const lines = md.split('\n');
        const leading = Math.min(...lines.filter(l => l.trim().length)
            .map(l => l.match(/^(\s+)/)?.[1].length || 0));
        if (isFinite(leading) && leading > 0) {
            md = lines.map(l => l.startsWith(' '.repeat(leading)) ? l.slice(leading) : l).join('\n');
        }

        // Fix lists that were turned into indented blocks (4-space -> list)
        md = md
            .replace(/^\s{4,}([-*+]\s+)/gm, '$1')
            .replace(/^\s{4,}(\d+\.\s+)/gm, '$1');

        // Ensure blank line before tables and lists for GFM
        md = md.replace(/([^\n])\n(\|[^\n]*\|)/g, '$1\n\n$2');
        md = md.replace(/([^\n])\n([-*+]\s+)/g, '$1\n\n$2');
        md = md.replace(/([^\n])\n(\d+\.\s+)/g, '$1\n\n$2');

        // Normalize headings with accidental leading spaces
        md = md.replace(/^\s{1,}(#{1,6}\s)/gm, '$1');

        // Restore code blocks
        md = md.replace(/__CODE_BLOCK_(\d+)__/g, (_, i) => blocks[Number(i)]);

        return md.trim();
    }

    renderMarkdownSafe(md, el) {
        const prepped = this.preprocessMarkdown(md || '');
        const html = window.marked.parse(prepped);
        el.innerHTML = window.DOMPurify.sanitize(html);
    }
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
                    <div id="analysis-results-container"></div>
                </div>
                
                <div class="analysis-raw">
                    <details>
                        <summary>Raw Analysis Data</summary>
                        <pre class="analysis-json">${analysisJson}</pre>
                    </details>
                </div>
            </div>
        `;
        
        // Process markdown content after HTML is set
        await this.processMarkdownContent(analysisResult);
    }
    
    async processMarkdownContent(analysisResult) {
        await this.ensureMarkdownLibs();
        
        // Process summary markdown
        const resultsContainer = document.getElementById('analysis-results-container');
        if (resultsContainer) {
            const formattedResults = await this.formatAnalysisResults(analysisResult);
            resultsContainer.innerHTML = formattedResults;
            
            // Find and process any markdown containers
            const markdownContainers = resultsContainer.querySelectorAll('.analysis-text-format');
            for (const container of markdownContainers) {
                if (container.id.startsWith('summary-markdown-') && analysisResult.summary) {
                    container.classList.add('analysis-text-format');
                    container.style.whiteSpace = 'normal';
                    this.renderMarkdownSafe(analysisResult.summary, container);
                }
            }
            
            // Handle other potential markdown sources
            const md = analysisResult.markdown || analysisResult.summary || '';
            const markdownContainer = document.querySelector('#analysis-markdown') || document.querySelector('#analysisContainer');
            if (markdownContainer && md) {
                markdownContainer.classList.add('analysis-text-format');
                markdownContainer.style.whiteSpace = 'normal';
                this.renderMarkdownSafe(md, markdownContainer);
            }
        }
    }
    
    async formatAnalysisResults(analysis) {
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
                    <div class="analysis-text-format" id="summary-markdown-${Date.now()}"></div>
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