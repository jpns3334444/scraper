// This file contains frontend constants
// Values should match .env file in the repository root
// API_URL is dynamically updated during deployment

/**
 * constants.js
 * Application configuration constants
 */

// API Configuration
const API_URL = 'https://whxu6x5b08.execute-api.ap-northeast-1.amazonaws.com/prod';
const FAVORITES_API_URL = API_URL; // Same API endpoint now

// Pagination Configuration
const ITEMS_PER_PAGE = 100;
const PROPERTIES_LIMIT = 300;
const DEFAULT_LIMIT = 300;

// UI Configuration
const ANIMATION_DURATION = 300;
const DEBOUNCE_DELAY = 500;

// Status Constants
const STATUS = {
    PROCESSING: 'processing',
    PROCESSED: 'processed',
    FAILED: 'failed',
    COMPLETED: 'completed'
};

// Verdict Types (should match .env file)
const VERDICT = {
    BUY_CANDIDATE: 'BUY_CANDIDATE',  // VERDICT_BUY_CANDIDATE in .env
    WATCH: 'WATCH',                  // VERDICT_WATCH in .env
    REJECT: 'REJECT',                // VERDICT_REJECT in .env
    BUY: 'BUY',                      // VERDICT_BUY in .env
    HOLD: 'HOLD'                     // VERDICT_HOLD in .env
};

// Sort Directions
const SORT_DIRECTION = {
    ASC: 'asc',
    DESC: 'desc'
};

// Tab Names
const TABS = {
    PROPERTIES: 'properties',
    FAVORITES: 'favorites',
    HIDDEN: 'hidden',
    ANALYSIS: 'analysis'
};

// Local Storage Keys
const STORAGE_KEYS = {
    USER_ID: 'user_id',
    USER_TOKEN: 'user_token',
    FAVORITES_PREFIX: 'favorites_',
    HIDDEN_PREFIX: 'hidden_'
};