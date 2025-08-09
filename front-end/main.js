/**
 * main.js
 * FIXED: Proper initialization order to ensure hidden items are loaded before properties
 */

document.addEventListener('DOMContentLoaded', async function() {
    console.log('[DEBUG] ==========================================');
    console.log('[DEBUG] Initializing Tokyo Real Estate App...');
    console.log('[DEBUG] ==========================================');
    
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
        console.log('[DEBUG] Hidden state changed, re-applying filters');
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
        console.log('[DEBUG] ==========================================');
        console.log('[DEBUG] STEP 1: Checking authentication...');
        console.log('[DEBUG] ==========================================');
        
        // Check authentication first
        const isAuthenticated = authManager.checkAuth();
        console.log('[DEBUG] User authenticated:', isAuthenticated);
        console.log('[DEBUG] Current user:', authManager.getCurrentUser());
        
        // Initialize router
        router.init();
        
        console.log('[DEBUG] ==========================================');
        console.log('[DEBUG] STEP 2: Loading user preferences...');
        console.log('[DEBUG] ==========================================');
        
        // CRITICAL: Load hidden items FIRST, before properties
        // This ensures properties are properly filtered from the start
        if (isAuthenticated && authManager.getCurrentUser()) {
            console.log('[DEBUG] User is authenticated, loading from API...');
            
            // Load both hidden and favorites in parallel
            const [hiddenResult, favoritesResult] = await Promise.all([
                hiddenManager.loadUserHidden().catch(err => {
                    console.error('[ERROR] Failed to load hidden items:', err);
                    hiddenManager.loadHiddenFromStorage(); // Fallback
                }),
                favoritesManager.loadUserFavorites().catch(err => {
                    console.error('[ERROR] Failed to load favorites:', err);
                    favoritesManager.loadFavoritesFromStorage(); // Fallback
                })
            ]);
            
            console.log('[DEBUG] User preferences loaded');
            console.log('[DEBUG] Hidden count:', appState.hidden.size);
            console.log('[DEBUG] Favorites count:', appState.favorites.size);
            
        } else {
            console.log('[DEBUG] User not authenticated, loading from localStorage...');
            
            // Load from localStorage for anonymous users
            hiddenManager.loadHiddenFromStorage();
            favoritesManager.loadFavoritesFromStorage();
            
            console.log('[DEBUG] Anonymous preferences loaded');
            console.log('[DEBUG] Hidden count:', appState.hidden.size);
            console.log('[DEBUG] Favorites count:', appState.favorites.size);
        }
        
        // Update counters after loading preferences
        favoritesManager.updateFavoritesCount();
        hiddenManager.updateHiddenCount();
        
        console.log('[DEBUG] ==========================================');
        console.log('[DEBUG] STEP 3: Loading properties...');
        console.log('[DEBUG] ==========================================');
        console.log('[DEBUG] Hidden items that will be filtered:', Array.from(appState.hidden));
        
        // NOW load properties - they will be filtered automatically based on hidden items
        await propertiesManager.loadAllProperties();
        
        console.log('[DEBUG] ==========================================');
        console.log('[DEBUG] App initialization complete!');
        console.log('[DEBUG] Total properties:', appState.allProperties.length);
        console.log('[DEBUG] Visible properties:', appState.filteredProperties.length);
        console.log('[DEBUG] Hidden properties:', appState.hidden.size);
        console.log('[DEBUG] Favorite properties:', appState.favorites.size);
        console.log('[DEBUG] ==========================================');
        
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