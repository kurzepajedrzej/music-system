import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App';
import { LiveStateProvider } from './lib/liveState';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LiveStateProvider>
      <App />
    </LiveStateProvider>
  </StrictMode>
);
