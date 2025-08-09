/**
 * AuthManager.js
 * Handles user authentication, login, registration, and user session management
 */

class AuthManager {
    constructor(api, state) {
        this.api = api;
        this.state = state;
        this.modal = null;
    }
    
    setModal(modal) {
        this.modal = modal;
    }
    
    checkAuth() {
        const savedEmail = localStorage.getItem('user_email');
        const savedToken = localStorage.getItem('auth_token');
        
        if (savedEmail && savedToken) {
            const user = { email: savedEmail, token: savedToken };
            this.state.setUser(user);
            this.hideAuthModal();
            this.showUserInfo(savedEmail);
            this.hideSignInPrompt();
            return true;
        } else {
            // Don't force login - show sign in button instead
            this.hideAuthModal();
            this.hideUserInfo();
            this.showSignInPrompt();
            return false;
        }
    }
    
    async login(email, password) {
        try {
            const data = await this.api.loginUser(email, password);
            
            if (data.success) {
                const user = { email, token: data.token || email };
                
                // Save to localStorage
                localStorage.setItem('user_email', email);
                localStorage.setItem('auth_token', data.token || email);
                
                // Update state
                this.state.setUser(user);
                
                // Update UI
                this.hideAuthModal();
                this.showUserInfo(email);
                this.hideSignInPrompt();
                this.clearError();
                
                // Clear old anonymous data
                this.clearAnonymousData();
                
                return { success: true, user };
            } else {
                this.showError(data.error || 'Authentication failed');
                return { success: false, error: data.error };
            }
        } catch (error) {
            console.error('Login error:', error);
            this.showError('Network error. Please try again.');
            return { success: false, error: 'Network error' };
        }
    }
    
    async register(email, password) {
        try {
            const data = await this.api.registerUser(email, password);
            
            if (data.success) {
                const user = { email, token: data.token || email };
                
                // Save to localStorage
                localStorage.setItem('user_email', email);
                localStorage.setItem('auth_token', data.token || email);
                
                // Update state
                this.state.setUser(user);
                
                // Update UI
                this.hideAuthModal();
                this.showUserInfo(email);
                this.hideSignInPrompt();
                this.clearError();
                
                // Clear old anonymous data
                this.clearAnonymousData();
                
                return { success: true, user };
            } else {
                this.showError(data.error || 'Registration failed');
                return { success: false, error: data.error };
            }
        } catch (error) {
            console.error('Registration error:', error);
            this.showError('Network error. Please try again.');
            return { success: false, error: 'Network error' };
        }
    }
    
    logout() {
        localStorage.clear();
        this.state.clearUser();
        location.reload();
    }
    
    showAuthModal() {
        const modal = document.getElementById('authModal');
        if (modal) {
            modal.style.display = 'block';
        }
    }
    
    hideAuthModal() {
        const modal = document.getElementById('authModal');
        if (modal) {
            modal.style.display = 'none';
        }
    }
    
    showUserInfo(email) {
        const userInfo = document.getElementById('userInfo');
        const userEmail = document.getElementById('userEmail');
        if (userInfo && userEmail) {
            userEmail.textContent = email;
            userInfo.style.display = 'flex';
        }
    }
    
    hideUserInfo() {
        const userInfo = document.getElementById('userInfo');
        if (userInfo) {
            userInfo.style.display = 'none';
        }
    }
    
    showSignInPrompt() {
        const signInPrompt = document.getElementById('signInPrompt');
        if (signInPrompt) {
            signInPrompt.style.display = 'flex';
        }
    }
    
    hideSignInPrompt() {
        const signInPrompt = document.getElementById('signInPrompt');
        if (signInPrompt) {
            signInPrompt.style.display = 'none';
        }
    }
    
    showError(message) {
        const errorElement = document.getElementById('authError');
        if (errorElement) {
            errorElement.textContent = message;
        }
    }
    
    clearError() {
        const errorElement = document.getElementById('authError');
        if (errorElement) {
            errorElement.textContent = '';
        }
    }
    
    clearAnonymousData() {
        // Get the anonymous user ID before clearing it
        const anonymousUserId = localStorage.getItem('user_id');
        if (anonymousUserId) {
            localStorage.removeItem(`favorites_${anonymousUserId}`);
            localStorage.removeItem(`hidden_${anonymousUserId}`);
        }
        
        // Also remove any old format keys
        localStorage.removeItem('favorites');
        localStorage.removeItem('hidden');
        localStorage.removeItem('user_id');
        
        this.state.setFavorites(new Set());
        this.state.setHidden(new Set());
        
        // Trigger properties re-filtering after clearing hidden state
        if (window.app && window.app.properties) {
            window.app.properties.applyFilters();
        }
    }
    
    getCurrentUser() {
        return this.state.currentUser;
    }
    
    isAuthenticated() {
        return this.state.currentUser !== null;
    }
}

// Global functions for backwards compatibility with onclick handlers
function logout() {
    if (window.app && window.app.auth) {
        window.app.auth.logout();
    }
}