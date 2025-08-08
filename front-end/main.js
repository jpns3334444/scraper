/**
 * main.js
 * Application initialization and wiring of all components
 */

// Initialize app
document.addEventListener('DOMContentLoaded', async function() {
    console.log('[DEBUG] Initializing Tokyo Real Estate App...');
    
    // Create instances
    const api = new PropertyAPI(API_URL, FAVORITES_API_URL);
    const router = new Router();
    const filterDropdown = new FilterDropdown();
    
    // Initialize managers
    const authManager = new AuthManager(api, appState);
    const authModal = new AuthModal();
    
    const propertiesManager = new PropertiesManager(api, appState);
    const propertiesView = new PropertiesView();
    
    const favoritesManager = new FavoritesManager(api, appState);
    const favoritesView = new FavoritesView();
    const analysisView = new AnalysisView();
    
    const hiddenManager = new HiddenManager(api, appState);
    const hiddenView = new HiddenView();
    
    // Wire up managers with their views
    authManager.setModal(authModal);
    authModal.setAuthManager(authManager);
    
    propertiesManager.setView(propertiesView);
    favoritesManager.setViews(favoritesView, analysisView);
    hiddenManager.setView(hiddenView);
    
    propertiesView.init();
    
    // Make available globally for onclick handlers and debugging
    window.app = {
        auth: authManager,
        properties: propertiesManager,
        favorites: favoritesManager,
        hidden: hiddenManager,
        router: router,
        filterDropdown: filterDropdown,
        api: api,
        state: appState
    };
    
    console.log('[DEBUG] Global app object created:', window.app);
    
    // Add global functions for onclick handlers
    window.showAuthModal = () => authModal.show();
    window.logout = () => authManager.logout();
    window.hideErrorBanner = () => {
        const banner = document.getElementById('errorBanner');
        if (banner) banner.style.display = 'none';
    };
    // goToPage function now defined in PropertiesManager.js
    window.applyColumnFilter = (column) => {
        const checkboxes = document.querySelectorAll(`#${column}-filter-options input[type="checkbox"]:checked`);
        appState.currentFilters[column] = Array.from(checkboxes).map(cb => cb.value);
        propertiesManager.applyFilters();
    };
    window.clearColumnFilter = (column) => {
        appState.currentFilters[column] = [];
        const checkboxes = document.querySelectorAll(`#${column}-filter-options input[type="checkbox"]`);
        checkboxes.forEach(cb => cb.checked = false);
        propertiesManager.applyFilters();
    };
    
    // Initialize components
    try {
        // Check authentication
        authManager.checkAuth();
        
        // Load hidden items (from API for logged-in users, storage for anonymous)
        if (authManager.getCurrentUser()) {
            await hiddenManager.loadUserHidden();
        } else {
            hiddenManager.loadFromStorage();
        }
        
        // Initialize router and tabs
        router.init();
        
        // Load properties first, then favorites to avoid race condition
        await propertiesManager.loadAllProperties();
        
        if (authManager.getCurrentUser()) {
            await favoritesManager.loadUserFavorites();
        } else {
            favoritesManager.loadFavoritesFromStorage();
        }
        
        // Update counters
        favoritesManager.updateFavoritesCount();
        hiddenManager.updateHiddenCount();
        
        // Re-render favorites view if that tab is currently active
        if (router.getCurrentTab() === TABS.FAVORITES) {
            await favoritesManager.loadFavorites();
        }
        
        console.log('[DEBUG] App initialization complete!');
        
    } catch (error) {
        console.error('[ERROR] App initialization failed:', error);
        DOMUtils.showErrorBanner('Failed to initialize app. Please refresh the page.');
    }
});

// Add some global debug functions for backwards compatibility
window.debugFavoritesDisplay = function() {
    console.log('=== FAVORITES DISPLAY DEBUG ===');
    
    // Check tab visibility
    const favTab = document.getElementById('favorites-tab');
    console.log('Favorites Tab:', {
        exists: !!favTab,
        hasActiveClass: favTab?.classList.contains('active'),
        display: favTab?.style.display,
        computedDisplay: favTab ? window.getComputedStyle(favTab).display : null,
        innerHTML: favTab?.innerHTML?.substring(0, 100) + '...'
    });
    
    // Check list element
    const favList = document.getElementById('favoritesList');
    console.log('Favorites List:', {
        exists: !!favList,
        display: favList?.style.display,
        computedDisplay: favList ? window.getComputedStyle(favList).display : null,
        innerHTML: favList?.innerHTML?.substring(0, 100) + '...'
    });
    
    // Check state
    console.log('App State:', {
        favorites: window.app.state.favorites,
        favoriteProperties: window.app.state.getFavoriteProperties()?.length
    });
};

window.debugHiddenDisplay = function() {
    console.log('=== HIDDEN DISPLAY DEBUG ===');
    
    // Check tab visibility
    const hiddenTab = document.getElementById('hidden-tab');
    console.log('Hidden Tab:', {
        exists: !!hiddenTab,
        hasActiveClass: hiddenTab?.classList.contains('active'),
        display: hiddenTab?.style.display,
        computedDisplay: hiddenTab ? window.getComputedStyle(hiddenTab).display : null
    });
    
    // Check list element
    const hiddenList = document.getElementById('hiddenList');
    console.log('Hidden List:', {
        exists: !!hiddenList,
        display: hiddenList?.style.display,
        computedDisplay: hiddenList ? window.getComputedStyle(hiddenList).display : null,
        innerHTML: hiddenList?.innerHTML?.substring(0, 100) + '...'
    });
    
    // Check state
    console.log('App State:', {
        hidden: window.app.state.hidden,
        hiddenProperties: window.app.state.getHiddenProperties()?.length
    });
};

// Expose state for debugging
window.debugState = function() {
    console.log('=== APP STATE DEBUG ===');
    console.log('Current User:', window.app.state.currentUser);
    console.log('All Properties Count:', window.app.state.allProperties.length);
    console.log('Filtered Properties Count:', window.app.state.filteredProperties.length);
    console.log('Favorites Count:', window.app.state.favorites.size);
    console.log('Hidden Count:', window.app.state.hidden.size);
    console.log('Current Sort:', window.app.state.currentSort);
    console.log('Current Filters:', window.app.state.currentFilters);
    console.log('Current Page:', window.app.state.currentPage);
    console.log('Loading:', window.app.state.loading);
    console.log('Background Loading:', window.app.state.isBackgroundLoading);
};

// Add error handler for unhandled errors
window.addEventListener('error', (error) => {
    console.error('[GLOBAL ERROR]:', error);
    DOMUtils.showErrorBanner('An unexpected error occurred. Please refresh the page.');
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('[UNHANDLED PROMISE REJECTION]:', event.reason);
    DOMUtils.showErrorBanner('An unexpected error occurred. Please refresh the page.');
});