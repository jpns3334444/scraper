/**
 * HiddenManager.js
 * Manages hidden items functionality using provider pattern
 */

// Canonical ID getter for properties (global)
const getPropertyId = (p) => String(p.listing_id ?? p.property_id ?? p.id);

// Local storage provider for guest users
class LocalProvider {
    constructor() {
        this.key = 'hiddenIds:v1';
    }
    
    async load() {
        try {
            const raw = localStorage.getItem(this.key);
            const ids = Array.isArray(JSON.parse(raw)) ? JSON.parse(raw) : [];
            return { ids: ids.map(String), rev: null };
        } catch {
            return { ids: [], rev: null };
        }
    }
    
    async add(id) {
        const { ids } = await this.load();
        const set = new Set(ids.map(String));
        set.add(String(id));
        localStorage.setItem(this.key, JSON.stringify([...set]));
        return { ids: [...set], rev: null };
    }
    
    async remove(id) {
        const { ids } = await this.load();
        const set = new Set(ids.map(String));
        set.delete(String(id));
        localStorage.setItem(this.key, JSON.stringify([...set]));
        return { ids: [...set], rev: null };
    }
    
    clear() {
        localStorage.removeItem(this.key);
    }
}

// Server provider for logged-in users
class ServerProvider {
    constructor(userId) {
        this.userId = userId;
    }
    
    async load() {
        const response = await fetch(`${FAVORITES_API_URL}/hidden/user/${this.userId}`, {
            headers: { 'X-User-Email': this.userId }
        });
        
        if (!response.ok) {
            throw new Error('hidden GET failed');
        }
        
        const data = await response.json();
        const ids = (data.hidden || []).map(h => String(h.property_id));
        return { ids, rev: data.rev ?? null };
    }
    
    async add(id, rev) {
        const response = await fetch(`${FAVORITES_API_URL}/hidden`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-Email': this.userId,
                ...(rev ? { 'If-Match': rev } : {})
            },
            body: JSON.stringify({ property_id: String(id) })
        });
        
        if (!response.ok) {
            throw new Error('hidden add failed');
        }
        
        const data = await response.json();
        const ids = (data.hidden || []).map(h => String(h.property_id));
        return { ids, rev: data.rev ?? null };
    }
    
    async remove(id, rev) {
        const response = await fetch(`${FAVORITES_API_URL}/hidden/${encodeURIComponent(String(id))}`, {
            method: 'DELETE',
            headers: {
                'X-User-Email': this.userId,
                ...(rev ? { 'If-Match': rev } : {})
            }
        });
        
        if (!response.ok) {
            throw new Error('hidden remove failed');
        }
        
        const data = await response.json();
        const ids = (data.hidden || []).map(h => String(h.property_id));
        return { ids, rev: data.rev ?? null };
    }
}

// Hidden store with provider pattern
let _prov = null;
let _rev = null;
let _set = new Set();
let _loaded = false;
let _subs = new Set();

function _emit() {
    for (const f of _subs) {
        try {
            f();
        } catch (e) {
            console.error('HiddenStore subscriber error:', e);
        }
    }
}

function _setFromIds(ids, rev) {
    _set = new Set(ids.map(String));
    _rev = rev ?? null;
    _loaded = true;
    _emit();
}

const HiddenStore = {
    // Initialize with user context and merge guest->server if needed
    async init({ user }) {
        const local = new LocalProvider();
        
        if (!user) {
            _prov = local;
            const { ids, rev } = await _prov.load();
            _setFromIds(ids, rev);
            return;
        }
        
        // Logged in: server-backed with guest merge
        const server = new ServerProvider(user.email);
        _prov = server;
        
        // Load both in parallel to merge guest -> server
        const [localData, serverData] = await Promise.all([
            local.load(),
            server.load()
        ]);
        
        const union = [...new Set([...localData.ids, ...serverData.ids])];
        
        // If union differs from server, push union and clear local
        if (union.length !== serverData.ids.length || 
            union.some(id => !serverData.ids.includes(id))) {
            
            // Add missing ones to server (idempotent)
            let rev = serverData.rev ?? null;
            for (const id of union) {
                if (!serverData.ids.includes(id)) {
                    try {
                        const res = await server.add(id, rev);
                        serverData.ids = res.ids;
                        rev = res.rev ?? rev;
                    } catch (e) {
                        console.warn('Failed to sync hidden item to server:', id, e);
                    }
                }
            }
            
            local.clear();
            _setFromIds(serverData.ids, rev);
        } else {
            _setFromIds(serverData.ids, serverData.rev ?? null);
            local.clear();
        }
    },
    
    isLoaded() {
        return _loaded;
    },
    
    has(id) {
        return _set.has(String(id));
    },
    
    all() {
        return [..._set];
    },
    
    subscribe(cb) {
        _subs.add(cb);
        return () => _subs.delete(cb);
    },
    
    async add(id) {
        id = String(id);
        if (_set.has(id)) return;
        
        _set.add(id);
        _emit(); // optimistic update
        
        try {
            const { ids, rev } = await _prov.add(id, _rev);
            _setFromIds(ids, rev);
        } catch (error) {
            // Revert optimistic update on failure
            _set.delete(id);
            _emit();
            throw error;
        }
    },
    
    async remove(id) {
        id = String(id);
        if (!_set.has(id)) return;
        
        _set.delete(id);
        _emit(); // optimistic update
        
        try {
            const { ids, rev } = await _prov.remove(id, _rev);
            _setFromIds(ids, rev);
        } catch (error) {
            // Revert optimistic update on failure
            _set.add(id);
            _emit();
            throw error;
        }
    }
};

// Legacy HiddenManager class for compatibility
class HiddenManager {
    constructor(api, state) {
        this.api = api;
        this.state = state;
        this.view = null;
        
        // Subscribe to HiddenStore changes and sync to legacy state
        HiddenStore.subscribe(() => {
            const hiddenIds = HiddenStore.all();
            this.state.setHidden(hiddenIds);
            this.updateHiddenCount();
            
            // If we're currently on the hidden tab, refresh the view
            if (window.app && window.app.router && window.app.router.getCurrentTab() === 'hidden') {
                if (this.view) {
                    this.view.renderHidden();
                }
            }
        });
    }
    
    setView(view) {
        this.view = view;
    }
    
    loadHidden() {
        console.log('[DEBUG] HiddenManager.loadHidden called');
        console.log('[DEBUG] HiddenStore available:', !!HiddenStore);
        console.log('[DEBUG] HiddenStore loaded:', HiddenStore ? HiddenStore.isLoaded() : false);
        console.log('[DEBUG] Hidden count:', HiddenStore ? HiddenStore.all().length : 'N/A');
        
        if (this.view) {
            console.log('[DEBUG] Calling view.renderHidden()');
            // Call the updated renderHidden method that uses HiddenStore internally
            this.view.renderHidden();
        } else {
            console.log('[DEBUG] No view available!');
        }
    }
    
    async loadUserHidden() {
        // This method is now handled by HiddenStore.init()
        // Keep for backwards compatibility but delegate to store
        if (!HiddenStore.isLoaded()) {
            const user = this.state.currentUser;
            await HiddenStore.init({ user });
        }
    }
    
    loadHiddenFromStorage() {
        // This method is now handled by HiddenStore.init()
        // Keep for backwards compatibility
        if (!HiddenStore.isLoaded()) {
            HiddenStore.init({ user: null });
        }
    }
    
    loadFromStorage() {
        this.loadHiddenFromStorage();
    }
    
    updateHiddenCount() {
        const hiddenCount = document.getElementById('hiddenCount');
        if (hiddenCount) {
            hiddenCount.textContent = HiddenStore.all().length.toString();
        }
    }
    
    async addHidden(propertyId) {
        try {
            await HiddenStore.add(getPropertyId({ property_id: propertyId }));
        } catch (error) {
            console.error('Error adding hidden property:', error);
            throw error;
        }
    }
    
    async removeHidden(propertyId) {
        try {
            await HiddenStore.remove(getPropertyId({ property_id: propertyId }));
            
            // Animate removal from hidden view
            const card = document.querySelector(`.hidden-card[data-property-id="${propertyId}"]`);
            if (card) {
                card.style.transition = 'all 0.3s';
                card.style.opacity = '0';
                card.style.transform = 'translateX(-100%)';
                setTimeout(() => {
                    card.remove();
                    // Check if no hidden items left
                    if (document.querySelectorAll('.hidden-card').length === 0) {
                        document.querySelector('.hidden-container').innerHTML = 
                            '<div style="padding:40px; text-align:center; color:#999;">No hidden items.</div>';
                    }
                }, 300);
            } else {
                // Fallback: refresh the hidden list display
                this.loadHidden();
            }
            
            // Refresh properties if on that tab to show restored property
            if (document.getElementById('properties-tab').classList.contains('active')) {
                window.app.properties.applyFilters();
            }
            
        } catch (error) {
            console.error('Error removing hidden property:', error);
            alert('Error removing property from hidden list');
        }
    }
}

// Global function for onclick handlers
function removeHiddenProperty(propertyId) {
    if (window.app && window.app.hidden) {
        window.app.hidden.removeHidden(propertyId);
    }
}

// Make globals available
window.HiddenStore = HiddenStore;
window.getPropertyId = getPropertyId;