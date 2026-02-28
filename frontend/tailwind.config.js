/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class', // enable dark mode manually or via system (using 'media' or 'class')
  content: [
    './app/**/*.{js,ts,jsx,tsx}',
    './pages/**/*.{js,ts,jsx,tsx}',
    './components/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        'brand-dark': '#101827',
      }
    },
  },
  plugins: [],
}
