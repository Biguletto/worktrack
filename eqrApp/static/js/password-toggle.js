(function () {
    'use strict';
    function addPasswordToggle(input) {
        if (input.dataset.passwordToggleReady === '1' || input.disabled) return;
        input.dataset.passwordToggleReady = '1';
        const wrapper = document.createElement('span');
        wrapper.className = 'password-input-wrap';
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'password-toggle-button';
        button.textContent = 'Show';
        button.setAttribute('aria-label', 'Show password');
        button.setAttribute('aria-pressed', 'false');
        button.addEventListener('click', function () {
            const reveal = input.type === 'password';
            input.type = reveal ? 'text' : 'password';
            button.textContent = reveal ? 'Hide' : 'Show';
            button.setAttribute('aria-label', reveal ? 'Hide password' : 'Show password');
            button.setAttribute('aria-pressed', reveal ? 'true' : 'false');
        });
        wrapper.appendChild(button);
    }
    function initialize() {
        document.querySelectorAll('input[type="password"]').forEach(addPasswordToggle);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
    else initialize();
})();
