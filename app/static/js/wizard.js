/**
 * PGSM Create Server Wizard - step navigation
 */
const TOTAL_STEPS = 3;
let currentStep = 1;

function wizardGo(step) {
    if (step < 1 || step > TOTAL_STEPS) return;

    // Hide current panel
    const currentPanel = document.getElementById('panel-' + currentStep);
    if (currentPanel) currentPanel.classList.remove('active');

    // Show target panel
    const targetPanel = document.getElementById('panel-' + step);
    if (targetPanel) targetPanel.classList.add('active');

    // Update step indicators
    for (let i = 1; i <= TOTAL_STEPS; i++) {
        const ind = document.getElementById('step-ind-' + i);
        if (!ind) continue;
        ind.classList.remove('active', 'done');
        if (i < step) {
            ind.classList.add('done');
        } else if (i === step) {
            ind.classList.add('active');
        }
    }

    currentStep = step;
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Initialize: show step 1
document.addEventListener('DOMContentLoaded', function () {
    wizardGo(1);
});
