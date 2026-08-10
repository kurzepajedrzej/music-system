/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	theme: {
		extend: {
			fontFamily: {
				sans: ['Inter Variable', 'Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif']
			}
		}
	},
	plugins: [require('daisyui')],
	daisyui: {
		themes: [
			{
				musiclight: {
					'primary': '#007AFF',
					'primary-content': '#ffffff',
					'secondary': '#5AC8FA',
					'accent': '#0055CC',
					'neutral': '#E5E5EA',
					'base-100': '#F2F2F7',
					'base-200': '#FFFFFF',
					'base-300': '#E5E5EA',
					'base-content': '#1C1C1E',
					'info': '#0A84FF',
					'success': '#30D158',
					'warning': '#FF9F0A',
					'error': '#FF453A'
				}
			},
			{
				musicdark: {
					'primary': '#0A84FF',
					'primary-content': '#ffffff',
					'secondary': '#5AC8FA',
					'accent': '#64B5F6',
					'neutral': '#0F2030',
					'base-100': '#080F18',
					'base-200': '#0C1520',
					'base-300': '#111E2E',
					'base-content': '#F0F9FF',
					'info': '#0A84FF',
					'success': '#30D158',
					'warning': '#FF9F0A',
					'error': '#FF453A'
				}
			}
		],
		darkTheme: 'musicdark'
	}
};
