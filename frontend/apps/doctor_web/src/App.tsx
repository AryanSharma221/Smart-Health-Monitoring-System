import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import { DevModeProvider } from './context';
import { AuthProvider } from './auth';
import { AppRoutes } from './routes';
import './styles/global.css';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <DevModeProvider>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </DevModeProvider>
    </BrowserRouter>
  );
};

export default App;
