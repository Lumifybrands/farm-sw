# Simple Loading System Guide

## Overview
The complex global loading system has been replaced with a simple, controlled loading system that only activates when you explicitly add the appropriate CSS classes to your elements.

## How to Use

### For Buttons
Add the class `btn-with-loading` to any button you want to show loading state:

```html
<!-- Submit button with loading -->
<button type="submit" class="btn-with-loading">
    <i class="fas fa-save"></i>
    <span>Save Changes</span>
</button>

<!-- Regular button with loading -->
<button class="btn-with-loading" onclick="someFunction()">
    <i class="fas fa-download"></i>
    <span>Download</span>
</button>
```

### For Links
Add the class `link-with-loading` to any link you want to show loading state:

```html
<!-- Navigation link with loading -->
<a href="{{ url_for('some_route') }}" class="link-with-loading">
    <i class="fas fa-home"></i>
    <span>Go to Dashboard</span>
</a>

<!-- Action link with loading -->
<a href="#" class="link-with-loading" onclick="performAction()">
    <i class="fas fa-trash"></i>
    <span>Delete Item</span>
</a>
```

### For Forms
Add the class `form-with-loading` to any form you want to show loading state:

```html
<form method="POST" class="form-with-loading">
    <!-- form fields -->
    <button type="submit" class="btn-with-loading">
        <i class="fas fa-save"></i>
        <span>Submit</span>
    </button>
</form>
```

## Manual Control (JavaScript)

You can also manually control the loading states using JavaScript:

```javascript
// Show loading on a button
const button = document.querySelector('.my-button');
showButtonLoading(button);

// Hide loading on a button
hideButtonLoading(button);

// Show loading on a link
const link = document.querySelector('.my-link');
showLinkLoading(link);

// Hide loading on a link
hideLinkLoading(link);

// Show loading on a form
const form = document.querySelector('.my-form');
showFormLoading(form);

// Hide loading on a form
hideFormLoading(form);
```

## Error Handling

The loading system automatically handles errors and makes buttons clickable again:

### Automatic Error Handling
- **Fetch Errors**: When any fetch request fails, all loading states are automatically removed
- **Unhandled Promise Rejections**: Loading states are cleared when promises are rejected
- **JavaScript Errors**: Loading states are reset when JavaScript errors occur

### Manual Error Handling
```javascript
// Reset loading for a specific element
const button = document.querySelector('.my-button');
resetLoading(button);

// Reset all loading states
resetAllLoading();

// Remove loading from all elements
removeAllLoading();
```

### Example with Error Handling
```javascript
// Example: Making an API call with error handling
async function saveData() {
    const button = document.querySelector('.save-btn');
    showButtonLoading(button);
    
    try {
        const response = await fetch('/api/save', {
            method: 'POST',
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            throw new Error('Save failed');
        }
        
        // Success - hide loading
        hideButtonLoading(button);
        showSuccessMessage('Data saved successfully!');
        
    } catch (error) {
        // Error - loading is automatically removed, but you can also manually reset
        resetLoading(button);
        showErrorMessage('Failed to save data: ' + error.message);
    }
}
```

## How It Works

1. **Automatic Activation**: When you click on an element with the appropriate class (e.g., `btn-with-loading`), it automatically adds the `loading` class.

2. **Visual Effects**: The `loading` class applies:
   - Reduced opacity (0.7)
   - Disabled pointer events
   - A spinning animation
   - Hidden text content (for buttons)

3. **Manual Control**: You can programmatically show/hide loading states using the provided JavaScript functions.

## CSS Classes Available

- `btn-with-loading` - For buttons
- `link-with-loading` - For links  
- `form-with-loading` - For forms

## Benefits of the New System

1. **Controlled**: Only elements you explicitly mark will show loading states
2. **Simple**: No complex interception or global overlays
3. **Flexible**: You can choose exactly which elements should show loading
4. **Lightweight**: Minimal JavaScript and CSS overhead
5. **Predictable**: No unexpected loading states on elements you didn't intend

## Migration from Old System

If you were using the old system, simply add the appropriate class to elements where you want loading:

- Old: Automatic loading on all buttons/links
- New: Add `btn-with-loading` or `link-with-loading` class to specific elements

## Example Usage

```html
<!-- This button will show loading when clicked -->
<button type="submit" class="btn-with-loading">
    <i class="fas fa-save"></i>
    <span>Save</span>
</button>

<!-- This button will NOT show loading -->
<button type="button">
    <i class="fas fa-cancel"></i>
    <span>Cancel</span>
</button>
``` 