/**
 * HiddenView.js
 * Handles rendering of hidden items list
 */

class HiddenView {
    renderHidden(hiddenProperties) {
        const hiddenList = document.getElementById('hiddenList');
        if (!hiddenList) return;
        
        hiddenList.innerHTML = hiddenProperties.map(property => this.renderHiddenItem(property)).join('');
    }
    
    renderHiddenItem(property) {
        const price = formatPrice(property.price, '', true);
        const ward = property.ward || 'Unknown';
        
        return `
            <li>
                <a href="${property.listing_url}" target="_blank">
                    ${ward} - ${price}
                </a>
                <button class="remove-btn" onclick="this.parentElement.remove()">
                    Remove
                </button>
            </li>
        `;
    }
}