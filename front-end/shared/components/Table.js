/**
 * Table.js
 * Table component with sorting and filtering capabilities
 */

class Table {
    constructor(containerId) {
        this.containerId = containerId;
    }
    
    render(headers, rows) {
        const container = document.getElementById(this.containerId);
        if (!container) return;
        
        let html = '<table><thead><tr>';
        
        headers.forEach(header => {
            html += `<th>${header.label}</th>`;
        });
        
        html += '</tr></thead><tbody>';
        
        rows.forEach(row => {
            html += '<tr>';
            row.forEach(cell => {
                html += `<td>${cell}</td>`;
            });
            html += '</tr>';
        });
        
        html += '</tbody></table>';
        container.innerHTML = html;
    }
    
    renderWithTemplate(template) {
        const container = document.getElementById(this.containerId);
        if (container) {
            container.innerHTML = template;
        }
    }
}