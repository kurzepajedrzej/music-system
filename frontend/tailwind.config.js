/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Spotify's actual palette: black sidebar, #121212 content area,
        // #181818 cards, #282828 hover, #1DB954 brand green, #B3B3B3 muted text.
        base: {
          950: '#121212',
          900: '#000000',
          800: '#181818',
          700: '#282828',
          600: '#3E3E3E'
        },
        accent: {
          DEFAULT: '#1DB954',
          dim: '#1AA34A'
        },
        ink: {
          DEFAULT: '#FFFFFF',
          muted: '#B3B3B3'
        }
      },
      fontFamily: {
        sans: ['Inter Variable', 'Inter', 'system-ui', 'sans-serif']
      }
    }
  },
  plugins: []
};
