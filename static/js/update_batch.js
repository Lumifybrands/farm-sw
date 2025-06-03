// Function to toggle quantity field visibility
function toggleQuantityField(checkbox, quantityFieldId) {
    const quantityField = document.getElementById(quantityFieldId);
    if (!quantityField) return;

    if (checkbox.checked) {
        quantityField.style.display = 'block';
        // When showing it, reset its input to "0" so the user can type a new value
        quantityField.querySelector('input').value = '0';
    } else {
        quantityField.style.display = 'none';
        // Hide it and reset its input back to "0"
        quantityField.querySelector('input').value = '0';
    }
}

// Function to validate schedule quantity (this is usually called from inline onchange on the quantity input)
function validateScheduleQuantity(input, scheduleId, type) {
    const quantity = parseFloat(input.value);
    const checkbox = document.querySelector(
        `input[name="scheduled_items[${type}][${scheduleId}][selected]"]`
    );
    const scheduledItem = input.closest('.scheduled-item');
    
    if (quantity <= 0) {
        // If quantity ≤ 0, uncheck the box, remove highlight, and hide the field again
        input.value = '0';
        if (checkbox) checkbox.checked = false;
        if (scheduledItem) scheduledItem.classList.remove('selected');
        toggleQuantityField(checkbox, `${type}_quantity_${scheduleId}`);
    } else {
        // If user typed a positive number, keep the box checked and highlight the row
        if (scheduledItem) scheduledItem.classList.add('selected');
    }
}

// Function to validate form before submission
function validateForm() {
    // 1) Validate date
    const dateInput = document.querySelector('input[name="date"]');
    if (!dateInput || !dateInput.value) {
        alert('Please select a date.');
        return false;
    }

    // 2) Validate mortality count
    const mortalityCount = document.querySelector('input[name="mortality_count"]');
    if (!mortalityCount || mortalityCount.value === '' || parseFloat(mortalityCount.value) < 0) {
        alert('Please enter a valid mortality count.');
        return false;
    }

    // 3) Validate feed used
    const feedUsed = document.querySelector('input[name="feed_used"]');
    if (!feedUsed || feedUsed.value === '' || parseFloat(feedUsed.value) < 0) {
        alert('Please enter a valid feed quantity.');
        return false;
    }

    // 4) Validate average weight
    const avgWeight = document.querySelector('input[name="avg_weight"]');
    if (!avgWeight || avgWeight.value === '' || parseFloat(avgWeight.value) < 0) {
        alert('Please enter a valid average weight.');
        return false;
    }

    // 5) Validate scheduled items (only those that are checked)
    const medicineSchedules = document.querySelectorAll(
        'input[name^="scheduled_items[medicine]"][name$="[selected]"]:checked'
    );
    for (const checkbox of medicineSchedules) {
        // Extract the schedule ID from the checkbox’s name, e.g. "scheduled_items[medicine][5][selected]"
        const match = checkbox.name.match(/\[medicine\]\[(\d+)\]\[selected\]/);
        if (!match) continue;
        const scheduleId = match[1];
        const quantityInput = document.querySelector(
            `input[name="scheduled_items[medicine][${scheduleId}][quantity]"]`
        );
        if (!quantityInput || !quantityInput.value || parseFloat(quantityInput.value) <= 0) {
            alert('Please enter valid quantities for all selected medicine schedules.');
            return false;
        }
    }

    const healthMaterialSchedules = document.querySelectorAll(
        'input[name^="scheduled_items[health_material]"][name$="[selected]"]:checked'
    );
    for (const checkbox of healthMaterialSchedules) {
        const match = checkbox.name.match(/\[health_material\]\[(\d+)\]\[selected\]/);
        if (!match) continue;
        const scheduleId = match[1];
        const quantityInput = document.querySelector(
            `input[name="scheduled_items[health_material][${scheduleId}][quantity]"]`
        );
        if (!quantityInput || !quantityInput.value || parseFloat(quantityInput.value) <= 0) {
            alert('Please enter valid quantities for all selected health material schedules.');
            return false;
        }
    }

    const vaccineSchedules = document.querySelectorAll(
        'input[name^="scheduled_items[vaccine]"][name$="[selected]"]:checked'
    );
    for (const checkbox of vaccineSchedules) {
        const match = checkbox.name.match(/\[vaccine\]\[(\d+)\]\[selected\]/);
        if (!match) continue;
        const scheduleId = match[1];
        const quantityInput = document.querySelector(
            `input[name="scheduled_items[vaccine][${scheduleId}][quantity]"]`
        );
        if (!quantityInput || !quantityInput.value || parseFloat(quantityInput.value) <= 0) {
            alert('Please enter valid quantities for all selected vaccine schedules.');
            return false;
        }
    }

    // 6) Validate dynamically‐added feed items
    const feedItems = document.querySelectorAll('select[name="feed_id[]"]');
    const feedQuantities = document.querySelectorAll('input[name="feed_quantity[]"]');
    const selectedFeeds = new Set();
    for (let i = 0; i < feedItems.length; i++) {
        if (feedItems[i].value) {
            if (selectedFeeds.has(feedItems[i].value)) {
                alert('Please do not select the same feed multiple times.');
                return false;
            }
            selectedFeeds.add(feedItems[i].value);
            if (!feedQuantities[i].value || parseFloat(feedQuantities[i].value) <= 0) {
                alert('Please enter valid quantities for all selected feed items.');
                return false;
            }
        }
    }

    // If all checks pass, return true (allow form submission)
    return true;
}

// The one-and-only DOMContentLoaded listener:
document.addEventListener('DOMContentLoaded', function() {
    // 1) Attach form validation to the <form> submit event
    const form = document.querySelector('form.update-form');
    if (form) {
        form.addEventListener('submit', function(event) {
            if (!validateForm()) {
                event.preventDefault(); // Stop submission if validation fails
            }
        });
    }

    // 2) Attach toggle logic to every scheduled-item checkbox
    const checkboxes = document.querySelectorAll(
        'input[type="checkbox"][name^="scheduled_items"]'
    );
    checkboxes.forEach(checkbox => {
        // We expect names like: "scheduled_items[medicine][5][selected]"
        const parts = checkbox.name.match(/scheduled_items\[(\w+)\]\[(\d+)\]\[selected\]/);
        if (!parts) return;

        const itemType = parts[1];   // e.g. "medicine" or "health_material" or "vaccine"
        const scheduleId = parts[2]; // e.g. "5"

        // Build the ID of the quantity <div> exactly as in your HTML: id="medicine_quantity_5"
        const quantityFieldId = `${itemType}_quantity_${scheduleId}`;

        checkbox.addEventListener('change', function() {
            toggleQuantityField(this, quantityFieldId);
        });
    });
});
