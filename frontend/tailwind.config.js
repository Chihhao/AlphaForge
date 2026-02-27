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
        gold: {
          50: '#fbf8eb',
          100: '#f5efcd',
          200: '#eedf9c',
          300: '#e5ca61',
          400: '#deb532',
          500: '#d19d21', // primary gold
          600: '#b47b19',
          700: '#905b16',
          800: '#774818',
          900: '#653c18',
          950: '#3a200a',
        },
      },
    },
  },
  plugins: [],
}
