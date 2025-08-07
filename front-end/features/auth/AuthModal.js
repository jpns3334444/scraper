/**
 * AuthModal.js
 * Handles the authentication modal UI and form interactions
 */

class AuthModal {
    constructor() {
        this.isLoginMode = true;
        this.authManager = null;
        this.init();
    }
    
    setAuthManager(authManager) {
        this.authManager = authManager;
    }
    
    init() {
        this.setupEventListeners();
        this.renderModal();
    }
    
    renderModal() {
        const modalContainer = document.getElementById('authModal');
        if (modalContainer) {
            modalContainer.innerHTML = `
                <div class="modal-content">
                    <h2 id="authTitle">Sign In</h2>
                    <form id="authForm">
                        <input type="email" id="email" placeholder="Email" required>
                        <input type="password" id="password" placeholder="Password" required>
                        <button type="submit" id="authSubmit">Sign In</button>
                    </form>
                    <div id="authError" class="error-message"></div>
                    <p class="auth-switch">
                        <span id="authSwitchText">Don't have an account?</span> 
                        <a href="#" id="authSwitchLink">Sign Up</a>
                    </p>
                </div>
            `;
        }
        
        // Re-setup event listeners after rendering
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        // Form submission
        const authForm = document.getElementById('authForm');
        if (authForm) {
            authForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.handleSubmit(e);
            });
        }
        
        // Toggle between login/register
        const authSwitchLink = document.getElementById('authSwitchLink');
        if (authSwitchLink) {
            authSwitchLink.addEventListener('click', (e) => {
                e.preventDefault();
                this.toggleMode();
            });
        }
        
        // Close modal when clicking outside
        const modal = document.getElementById('authModal');
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.hide();
                }
            });
        }
    }
    
    async handleSubmit(e) {
        e.preventDefault();
        
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;
        
        if (!email || !password) {
            this.showError('Please fill in all fields');
            return;
        }
        
        this.clearError();
        
        let result;
        if (this.isLoginMode) {
            result = await this.authManager.login(email, password);
        } else {
            result = await this.authManager.register(email, password);
        }
        
        if (result.success) {
            this.hide();
            this.clearForm();
            
            // Reload favorites and properties for authenticated user
            if (window.app.favorites) {
                await window.app.favorites.loadUserFavorites();
            }
            if (window.app.properties) {
                await window.app.properties.loadAllProperties();
            }
        }
    }
    
    toggleMode() {
        this.isLoginMode = !this.isLoginMode;
        
        const titleElement = document.getElementById('authTitle');
        const submitElement = document.getElementById('authSubmit');
        const switchTextElement = document.getElementById('authSwitchText');
        const switchLinkElement = document.getElementById('authSwitchLink');
        
        if (this.isLoginMode) {
            titleElement.textContent = 'Sign In';
            submitElement.textContent = 'Sign In';
            switchTextElement.textContent = "Don't have an account?";
            switchLinkElement.textContent = 'Sign Up';
        } else {
            titleElement.textContent = 'Sign Up';
            submitElement.textContent = 'Sign Up';
            switchTextElement.textContent = 'Already have an account?';
            switchLinkElement.textContent = 'Sign In';
        }
        
        this.clearError();
    }
    
    show() {
        const modal = document.getElementById('authModal');
        if (modal) {
            modal.style.display = 'block';
        }
    }
    
    hide() {
        const modal = document.getElementById('authModal');
        if (modal) {
            modal.style.display = 'none';
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
    
    clearForm() {
        const emailInput = document.getElementById('email');
        const passwordInput = document.getElementById('password');
        
        if (emailInput) emailInput.value = '';
        if (passwordInput) passwordInput.value = '';
        
        this.clearError();
    }
}

// Global functions for backwards compatibility with onclick handlers
function showAuthModal() {
    if (window.app && window.app.auth && window.app.auth.modal) {
        window.app.auth.modal.show();
    } else {
        const modal = document.getElementById('authModal');
        if (modal) {
            modal.style.display = 'block';
        }
    }
}