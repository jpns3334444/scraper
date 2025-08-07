/**
 * router.js
 * Tab routing and navigation management with fluid ink indicator
 */

class Router {
    constructor() {
        this.currentTab = TABS.PROPERTIES;
        this.tabHandlers = {};
    }
    
    init() {
        this.setupTabNavigation();
        this.setupTabButtons();
    }
    
    setupTabNavigation() {
        const tabContainer = document.getElementById('tabNavigation');
        if (tabContainer) {
            // Preserve the canvas element if it exists
            const existingCanvas = tabContainer.querySelector('#inkCanvas');
            
            tabContainer.innerHTML = `
                <button class="tab-button active" onclick="window.app.router.switchTab('properties')">
                    Properties
                </button>
                <button class="tab-button" onclick="window.app.router.switchTab('favorites')">
                    Favorites <span class="favorites-count" id="favoritesCount">0</span>
                </button>
                <button class="tab-button" onclick="window.app.router.switchTab('hidden')">
                    Hidden <span class="favorites-count" id="hiddenCount" style="background: #999;">0</span>
                </button>
            `;
            
            // Re-append canvas if it existed
            if (existingCanvas) {
                tabContainer.appendChild(existingCanvas);
            }
        }
    }
    
    setupTabButtons() {
        document.querySelectorAll('.tab-button').forEach((button, index) => {
            button.addEventListener('click', (e) => {
                const tabName = this.getTabNameFromButton(e.target);
                if (tabName) {
                    this.switchTab(tabName);
                    
                    // Trigger fluid ink animation
                    if (window.fluidInk) {
                        window.fluidInk.moveToTab(index);
                    }
                }
            });
        });
        
        // Update fluid ink tab positions after setup
        setTimeout(() => {
            if (window.fluidInk) {
                window.fluidInk.updateTabPositions();
            }
        }, 100);
    }
    
    getTabNameFromButton(button) {
        const text = button.textContent.toLowerCase();
        if (text.includes('properties')) return TABS.PROPERTIES;
        if (text.includes('favorites')) return TABS.FAVORITES;
        if (text.includes('hidden')) return TABS.HIDDEN;
        return null;
    }
    
    async switchTab(tabName) {
        console.log(`[DEBUG] ========== SWITCHING TO TAB: ${tabName} ==========`);
        
        // Log state before switching
        console.log('[DEBUG] Tab states BEFORE switch:');
        document.querySelectorAll('.tab-pane').forEach(pane => {
            console.log(`  - ${pane.id}: display=${pane.style.display}, active=${pane.classList.contains('active')}`);
        });
        
        // Remove active class from all panes
        document.querySelectorAll('.tab-pane').forEach(pane => {
            pane.classList.remove('active');
            pane.style.display = 'none'; // Explicitly set display:none
        });
        
        // Remove active from all buttons
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.classList.remove('active');
        });
        
        // Activate the selected tab
        const targetTab = document.getElementById(`${tabName}-tab`);
        console.log(`[DEBUG] Activating tab: ${tabName}-tab`);
        if (targetTab) {
            targetTab.classList.add('active');
            targetTab.style.display = 'block'; // Explicitly set display:block
        }
        
        // Activate the button and trigger fluid ink
        const buttons = Array.from(document.querySelectorAll('.tab-button'));
        const activeButton = buttons.find(btn => {
            const btnTabName = this.getTabNameFromButton(btn);
            return btnTabName === tabName;
        });
        
        if (activeButton) {
            activeButton.classList.add('active');
            
            // Trigger fluid ink animation
            const buttonIndex = buttons.indexOf(activeButton);
            if (window.fluidInk && buttonIndex >= 0) {
                window.fluidInk.moveToTab(buttonIndex);
            }
        }
        
        // Log state after switching
        console.log('[DEBUG] Tab states AFTER switch:');
        document.querySelectorAll('.tab-pane').forEach(pane => {
            console.log(`  - ${pane.id}: display=${pane.style.display}, active=${pane.classList.contains('active')}`);
        });
        
        // Handle tab-specific logic
        await this.handleTabSwitch(tabName);
        
        this.currentTab = tabName;
        console.log(`[DEBUG] ========== TAB SWITCH COMPLETE ==========`);
    }
    
    async handleTabSwitch(tabName) {
        if (tabName === TABS.FAVORITES) {
            console.log('[DEBUG] Loading favorites tab content...');
            DOMUtils.hideElement('tableContainer');
            DOMUtils.hideElement('loading');
            DOMUtils.hideElement('paginationContainer');
            
            if (window.app.favorites) {
                await window.app.favorites.loadFavorites();
            }
            console.log('[DEBUG] Favorites tab loaded');
            
            // Check if content is visible
            const favList = document.getElementById('favoritesList');
            console.log(`[DEBUG] favoritesList element: exists=${!!favList}, innerHTML length=${favList?.innerHTML?.length}`);
            if (favList) {
                console.log(`[DEBUG] favoritesList computed style:`, window.getComputedStyle(favList));
            }
        } else if (tabName === TABS.HIDDEN) {
            console.log('[DEBUG] Loading hidden tab content...');
            DOMUtils.hideElement('tableContainer');
            DOMUtils.hideElement('loading');
            DOMUtils.hideElement('paginationContainer');
            
            if (window.app.hidden) {
                window.app.hidden.loadHidden();
            }
            console.log('[DEBUG] Hidden tab loaded');
            
            // Check if content is visible
            const hiddenList = document.getElementById('hiddenList');
            console.log(`[DEBUG] hiddenList element: exists=${!!hiddenList}, innerHTML length=${hiddenList?.innerHTML?.length}`);
            if (hiddenList) {
                console.log(`[DEBUG] hiddenList computed style:`, window.getComputedStyle(hiddenList));
            }
        } else {
            console.log('[DEBUG] Showing main properties table');
            DOMUtils.showElement('tableContainer');
            DOMUtils.showElement('paginationContainer');
        }
    }
    
    getCurrentTab() {
        return this.currentTab;
    }
    
    registerTabHandler(tabName, handler) {
        this.tabHandlers[tabName] = handler;
    }
}

// Global functions for backwards compatibility with onclick handlers
function switchTab(tabName) {
    if (window.app && window.app.router) {
        window.app.router.switchTab(tabName);
    }
}