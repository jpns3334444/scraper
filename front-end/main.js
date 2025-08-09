/**
 * main.js
 * SIMPLIFIED: Proper initialization order for hidden functionality
 */

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
    
    // Set up event listeners for state changes
    appState.on('hidden', () => {
        // Re-apply filters whenever hidden state changes
        if (window.app && window.app.properties) {
            window.app.properties.applyFilters();
        }
    });
    
    propertiesView.init();
    
    // Make available globally
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
    
    console.log('[DEBUG] Global app object created');
    
    // Add global functions for onclick handlers
    window.showAuthModal = () => authModal.show();
    window.logout = () => authManager.logout();
    window.hideErrorBanner = () => {
        const banner = document.getElementById('errorBanner');
        if (banner) banner.style.display = 'none';
    };
    
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
        // Check authentication first
        authManager.checkAuth();
        
        // Initialize router
        router.init();
        
        // Load user's hidden items FIRST
        console.log('[DEBUG] Loading hidden items...');
        if (authManager.getCurrentUser()) {
            await hiddenManager.loadUserHidden();
        } else {
            hiddenManager.loadHiddenFromStorage();
        }
        console.log('[DEBUG] Hidden items loaded:', appState.hidden.size, 'items');
        
        // Load favorites
        console.log('[DEBUG] Loading favorites...');
        if (authManager.getCurrentUser()) {
            await favoritesManager.loadUserFavorites();
        } else {
            favoritesManager.loadFavoritesFromStorage();
        }
        console.log('[DEBUG] Favorites loaded:', appState.favorites.size, 'items');
        
        // Load properties - they will be filtered automatically
        console.log('[DEBUG] Loading properties...');
        await propertiesManager.loadAllProperties();
        
        // Update counters
        favoritesManager.updateFavoritesCount();
        hiddenManager.updateHiddenCount();
        
        console.log('[DEBUG] App initialization complete!');
        
    } catch (error) {
        console.error('[ERROR] App initialization failed:', error);
        DOMUtils.showErrorBanner('Failed to initialize app. Please refresh the page.');
    }
});

// Add error handler
window.addEventListener('error', (error) => {
    console.error('[GLOBAL ERROR]:', error);
    DOMUtils.showErrorBanner('An unexpected error occurred. Please refresh the page.');
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('[UNHANDLED PROMISE REJECTION]:', event.reason);
    DOMUtils.showErrorBanner('An unexpected error occurred. Please refresh the page.');
});