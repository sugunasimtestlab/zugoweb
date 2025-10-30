// --- START OF FILE script.js ---

// Get the main container
const container = document.getElementById("container");

// Get the sign-in and sign-up buttons
const signUpButton = document.getElementById("signUp");
const signInButton = document.getElementById("signIn");

// Add event listeners for switching panels
signUpButton.addEventListener("click", () => {
    container.classList.add("right-panel-active");
});

signInButton.addEventListener("click", () => {
    container.classList.remove("right-panel-active");
});