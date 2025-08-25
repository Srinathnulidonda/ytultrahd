// Contact form functionality
document.addEventListener('DOMContentLoaded', () => {
    const contactForm = document.getElementById('contactForm');

    if (contactForm) {
        contactForm.addEventListener('submit', handleContactSubmit);
    }
});

async function handleContactSubmit(e) {
    e.preventDefault();

    const form = e.target;

    // Form validation
    if (!form.checkValidity()) {
        e.stopPropagation();
        form.classList.add('was-validated');
        return;
    }

    // Get form data
    const formData = {
        name: form.name.value.trim(),
        email: form.email.value.trim(),
        subject: form.subject.value,
        message: form.message.value.trim()
    };

    // Disable submit button
    const submitBtn = form.querySelector('button[type="submit"]');
    const originalText = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = `
        <div class="spinner spinner-sm me-2"></div>
        Sending...
    `;

    try {
        // Simulate API call (replace with actual endpoint)
        await sendContactMessage(formData);

        // Show success
        showToast('Message sent successfully! We\'ll get back to you soon.', 'success');

        // Reset form
        form.reset();
        form.classList.remove('was-validated');

    } catch (error) {
        showToast('Failed to send message. Please try again.', 'error');
    } finally {
        // Re-enable button
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }
}

async function sendContactMessage(data) {
    // Simulate API call
    return new Promise((resolve, reject) => {
        setTimeout(() => {
            // Randomly succeed or fail for demo
            if (Math.random() > 0.2) {
                resolve({ success: true });
            } else {
                reject(new Error('Network error'));
            }
        }, 2000);
    });

    // Real implementation:
    // return apiClient.request('/api/contact', {
    //     method: 'POST',
    //     body: JSON.stringify(data)
    // });
}

function showToast(message, type = 'info') {
    // Create toast element
    const toastEl = document.createElement('div');
    toastEl.className = `toast align-items-center text-white bg-${type === 'success' ? 'success' : 'danger'} border-0`;
    toastEl.setAttribute('role', 'alert');
    toastEl.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;

    // Add to container
    const container = document.querySelector('.toast-container') || createToastContainer();
    container.appendChild(toastEl);

    // Initialize and show
    const toast = new bootstrap.Toast(toastEl, { delay: 5000 });
    toast.show();

    // Remove after hidden
    toastEl.addEventListener('hidden.bs.toast', () => {
        toastEl.remove();
    });
}

function createToastContainer() {
    const container = document.createElement('div');
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    container.style.zIndex = '1080';
    document.body.appendChild(container);
    return container;
}