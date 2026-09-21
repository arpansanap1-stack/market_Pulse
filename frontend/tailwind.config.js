/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        market: {
          dark: '#0b0e14',
          card: '#121824',
          border: '#1e293b',
          up: '#10b981',      // Emerald 500
          upGlow: '#059669',
          down: '#ef4444',    // Red 500
          downGlow: '#dc2626',
          accent: '#38bdf8',  // Sky 400
          textMuted: '#94a3b8',
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Courier New', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      keyframes: {
        flashGreen: {
          '0%': { backgroundColor: 'rgba(16, 185, 129, 0.25)' },
          '100%': { backgroundColor: 'transparent' },
        },
        flashRed: {
          '0%': { backgroundColor: 'rgba(239, 68, 68, 0.25)' },
          '100%': { backgroundColor: 'transparent' },
        },
      },
      animation: {
        flashUp: 'flashGreen 0.6s ease-out',
        flashDown: 'flashRed 0.6s ease-out',
      }
    },
  },
  plugins: [],
}
