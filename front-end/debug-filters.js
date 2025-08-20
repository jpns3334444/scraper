/**
 * Comprehensive filter debugging utilities
 * Paste these functions into browser console for testing
 */

// Run this in browser console to test filter persistence
function testFilterPersistence() {
    console.log('=== FILTER PERSISTENCE TEST ===');
    
    // Check localStorage
    console.log('All localStorage keys:', Object.keys(localStorage));
    console.log('Filter-related keys:');
    Object.keys(localStorage).filter(k => k.includes('filter')).forEach(k => {
        try {
            console.log(`  ${k}:`, JSON.parse(localStorage.getItem(k)));
        } catch (e) {
            console.log(`  ${k}:`, localStorage.getItem(k), '(failed to parse)');
        }
    });
    
    // Check current state
    console.log('Current appState.currentFilters:', window.appState.currentFilters);
    
    // Check actual checkbox states
    ['ward', 'floor', 'primary_light', 'verdict'].forEach(column => {
        const checkboxes = document.querySelectorAll(`#${column}-filter-options input[type="checkbox"]`);
        const checked = Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.value);
        const total = checkboxes.length;
        console.log(`${column} checkboxes: ${checked.length}/${total} checked:`, checked);
    });
    
    console.log('=== END TEST ===');
}

// Test saving filters manually
function testSaveFilters() {
    console.log('=== MANUAL SAVE TEST ===');
    const testFilters = {
        ward: ['Shibuya', 'Minato'],
        floor: ['3'],
        primary_light: ['South'],
        verdict: ['BUY']
    };
    console.log('Test filters to save:', testFilters);
    StorageManager.saveFilters(testFilters);
    console.log('=== END SAVE TEST ===');
}

// Test loading filters manually
function testLoadFilters() {
    console.log('=== MANUAL LOAD TEST ===');
    const loaded = StorageManager.loadFilters();
    console.log('Loaded filters:', loaded);
    console.log('=== END LOAD TEST ===');
}

// Show all debugging info
function fullDebugReport() {
    console.log('=== FULL DEBUG REPORT ===');
    
    console.log('1. localStorage contents:');
    Object.keys(localStorage).forEach(k => {
        console.log(`  ${k}:`, localStorage.getItem(k));
    });
    
    console.log('2. App state:');
    console.log('  appState.currentFilters:', window.appState?.currentFilters);
    console.log('  appState.currentUser:', window.appState?.currentUser);
    
    console.log('3. Storage key generation:');
    console.log('  StorageManager.getFilterStorageKey():', StorageManager.getFilterStorageKey());
    
    console.log('4. Filter persistence test:');
    testFilterPersistence();
    
    console.log('=== END FULL REPORT ===');
}

console.log('Filter debugging functions loaded. Available functions:');
console.log('- testFilterPersistence()');
console.log('- testSaveFilters()');
console.log('- testLoadFilters()');
console.log('- fullDebugReport()');