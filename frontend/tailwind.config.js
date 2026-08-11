/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        base: {
          950: '#121014',
          900: '#19161C',
          800: '#232028',
          700: '#332D38',
          600: '#4A424F'
        },
        accent: {
          DEFAULT: '#7FA98A',
          dim: '#3E5A48'
        },
        ink: {
          DEFAULT: '#F1EAE2',
          muted: '#9A9088'
        }
      },
      fontFamily: {
        sans: ['Inter Variable', 'Inter', 'system-ui', 'sans-serif']
      }
    }
  },
  plugins: []
};
